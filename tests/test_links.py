# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Resolving shortened links."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import Run, results
from make_archives import make_twitter, tweet

from aipress24_client.cli import links as links_module
from aipress24_client.cli.links import Link, expand, find_links, is_short, resolve


class Web:
    """Answers by URL, and the URLs that were asked."""

    def __init__(self, **answers: tuple[int, str] | BaseException) -> None:
        self.answers = {f"https://bit.ly/{key}": each for key, each in answers.items()}
        self.asked: list[str] = []

    def __call__(self, url: str) -> tuple[int, str]:
        self.asked.append(url)
        answer = self.answers[url]
        if isinstance(answer, BaseException):
            raise answer
        return answer


@pytest.mark.parametrize(
    ("answer", "target", "note"),
    [
        ((301, "https://x.test/a?b=c"), "https://x.test/a?b=c", ""),
        ((302, "http://x.test/"), "http://x.test/", ""),
        ((404, ""), "", "dead: HTTP 404"),
        ((410, ""), "", "dead: HTTP 410"),
        ((200, ""), "", "a page"),
        ((301, ""), "", "no usable redirection"),
        ((301, "javascript:alert(1)"), "", "no usable redirection"),
        ((301, "file:///etc/passwd"), "", "no usable redirection"),
        ((301, "https://[x"), "", "no usable redirection"),
        ((503, ""), "", "failed: HTTP 503"),
        ((429, ""), "", "failed: HTTP 429"),
        (TimeoutError("timed out"), "", "failed: timed out"),
    ],
)
def test_resolve(
    monkeypatch: pytest.MonkeyPatch,
    answer: tuple[int, str] | BaseException,
    target: str,
    note: str,
) -> None:
    link = "https://bit.ly/a"
    use(monkeypatch, Web(a=answer))
    found = resolve(link)
    assert found == Link(link, target, note)
    assert found.is_settled == (not note.startswith("failed"))


def test_only_shorteners_are_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    web = Web(
        a=(301, "/b"),
        b=(301, "http://127.0.0.1/admin"),
    )
    use(monkeypatch, web)
    assert resolve("https://bit.ly/a").target == "http://127.0.0.1/admin"
    assert web.asked == ["https://bit.ly/a", "https://bit.ly/b"]


def test_a_loop_is_survived(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, Web(a=(301, "https://bit.ly/b"), b=(301, "https://bit.ly/a")))
    assert resolve("https://bit.ly/a").note == "redirects in circles"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://bit.ly/a", True),
        ("http://BIT.LY/a", True),
        ("https://bit.ly/", False),
        ("https://bit.ly.evil.test/a", False),
        ("https://evil.test/bit.ly", False),
        ("https://bit.ly:8080/a", False),
        ("https://me@bit.ly/a", False),
        ("ftp://bit.ly/a", False),
        ("https://[x", False),
        ("https://youtu.be/a", False),
    ],
)
def test_is_short(url: str, expected: bool) -> None:
    assert is_short(url) == expected


def test_links_of_a_text() -> None:
    text = "(https://bit.ly/a), https://x.test/ http://bit.ly/b. https://bit.ly/a"
    assert find_links([text]) == ["https://bit.ly/a", "http://bit.ly/b"]
    known = {
        "https://bit.ly/a": Link("https://bit.ly/a", "https://y.test/?q=1&r"),
        "http://bit.ly/b": Link("http://bit.ly/b", "", "dead: HTTP 404"),
    }
    assert expand(text, known) == (
        "(https://y.test/?q=1&r), https://x.test/ http://bit.ly/b. https://y.test/?q=1&r"
    )


def test_a_link_which_starts_another_is_not_replaced_in_it() -> None:
    known = {"https://bit.ly/a": Link("https://bit.ly/a", "https://y.test/")}
    assert expand("https://bit.ly/ab", known) == "https://bit.ly/ab"


# --- the command -----------------------------------------------------------


@pytest.fixture
def catalog(tmp_path: Path, run: Run, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(links_module, "DELAY", 0)
    archive = make_twitter(
        tmp_path / "t.zip",
        tweet("1", "Un https://bit.ly/a"),
        tweet("2", "Deux https://bit.ly/b"),
        tweet("3", "@x https://bit.ly/c"),
    )
    path = tmp_path / "posts.csv"
    run("catalog", "create", archive, "-o", path)
    return path


def use(monkeypatch: pytest.MonkeyPatch, web: Web) -> None:
    monkeypatch.setattr(links_module, "ask", web)


def test_resolve_a_catalog(
    catalog: Path, run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    web = Web(a=(301, "https://x.test/long"), b=TimeoutError("timed out"))
    use(monkeypatch, web)
    _, lines, _ = run("post", "check", catalog)
    assert "https://bit.ly/a" in lines[0]["warnings"][0]

    status, lines, _ = run("catalog", "resolve", catalog)
    assert (status, results(lines)) == (1, ["resolved", "kept"])
    # The links of what is not to be published are not asked.
    assert web.asked == ["https://bit.ly/a", "https://bit.ly/b"]

    _, lines, _ = run("post", "check", catalog)
    assert lines[0]["title"] == "Un https://x.test/long"
    assert lines[0]["warnings"] == []
    assert "https://bit.ly/b" in lines[1]["warnings"][0]

    # Only what failed is asked again.
    web = Web(b=(404, ""))
    use(monkeypatch, web)
    status, lines, _ = run("catalog", "resolve", catalog)
    assert (status, results(lines)) == (0, ["kept"])
    assert run("catalog", "resolve", catalog)[1] == []
    assert web.asked == ["https://bit.ly/b"]


def test_a_correction_is_kept(
    catalog: Path, run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = links_module.links_path(catalog)
    path.write_text(
        "link,target,note\n"
        "https://bit.ly/a,https://web.archive.org/x,\n"
        "https://bit.ly/b,javascript:alert(1),\n"
    )
    web = Web(b=(404, ""))
    use(monkeypatch, web)
    run("catalog", "resolve", catalog)
    assert web.asked == ["https://bit.ly/b"]
    _, lines, _ = run("post", "check", catalog)
    assert lines[0]["title"] == "Un https://web.archive.org/x"
    assert "javascript" not in path.read_text()


def test_what_was_found_before_an_interruption_is_kept(
    catalog: Path, run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, Web(a=(301, "https://x.test/"), b=KeyboardInterrupt()))
    status, _, err = run("catalog", "resolve", catalog)
    assert status == 130
    assert "Interrupted" in err
    assert "https://x.test/" in links_module.links_path(catalog).read_text()
