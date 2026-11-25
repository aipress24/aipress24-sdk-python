# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The command line itself, and the small nouns."""

from __future__ import annotations

import io
import stat
from pathlib import Path

import pytest
from conftest import Run
from fake_site import URL, FakeSite

from aipress24_client import ApiError, Client, cli
from aipress24_client.cli import site as site_module
from aipress24_client.cli.access import find_token, store_token
from aipress24_client.cli.errors import CliError
from aipress24_client.cli.site import RetryingClient


@pytest.mark.parametrize(
    "argv",
    [
        ["nope"],
        ["press-release", "nope"],
        ["press-release", "draft"],
        ["press-release", "draft", "x", "--nope"],
        ["vocabulary", "list", "press-release.nope"],
        ["article", "draft", "x"],
    ],
)
def test_a_wrong_command_line(
    argv: list[str], site: FakeSite, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(argv) == 2
    assert capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["press-release"],
        ["catalog", "create"],
        ["catalog", "update"],
        ["catalog", "status"],
        ["catalog", "resolve"],
        ["vocabulary", "list"],
        ["vocabulary", "search"],
        ["publisher", "list"],
        ["auth", "login"],
        ["auth", "logout"],
        ["auth", "status"],
        *(
            ["post", verb]
            for verb in ["check", "status", "publish", "delete", "list", "show"]
        ),
        *(
            ["press-release", verb]
            for verb in [
                "check",
                "status",
                "draft",
                "publish",
                "unpublish",
                "delete",
                "list",
                "show",
            ]
        ),
    ],
)
def test_each_command_has_its_help(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([*argv, "--help"]) == 0
    assert f"aipress24 {' '.join(argv)}" in capsys.readouterr().out


def test_the_nouns_are_listed(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    for noun in ("press-release", "catalog", "vocabulary", "publisher", "auth"):
        assert noun in out
    assert "article" not in out


@pytest.mark.parametrize("source", ["before", "after", "environment"])
def test_the_site_can_be_chosen(
    source: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(site_module, "RETRY_DELAYS", ())
    monkeypatch.setenv("AIPRESS24_TOKEN", "a24_x")
    url = "http://127.0.0.1:1"
    argv = ["publisher", "list"]
    if source == "before":
        argv = ["--site", url, *argv]
    elif source == "after":
        argv = [*argv, "--site", url]
    else:
        monkeypatch.setenv("AIPRESS24_SITE", url)

    assert cli.main(argv) == 1
    assert f"Cannot reach {url}" in capsys.readouterr().err


def test_text_output(
    site: FakeSite, folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["press-release", "draft", str(folder)]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("created    Acme lance le Widget")
    assert f"{URL}/wip/communiques/" in captured.out
    assert "1 press release(s): 1 created" in captured.err


def test_titles_do_not_drive_the_terminal(
    site: FakeSite, folder: Path, run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    run("press-release", "draft", folder)
    site.only()["titre"] = "\x1b[2Jx"
    cli.main(["press-release", "list"])
    assert "\x1b" not in capsys.readouterr().out


def test_vocabularies(site: FakeSite, run: Run) -> None:
    assert run("vocabulary", "list", "press-release.genre")[1] == [
        {"vocabulary": "press-release.genre", "value": "Annonce"}
    ]
    assert run("vocabulary", "search", "ECONO")[1] == [
        {"vocabulary": "press-release.section", "value": "Économie"}
    ]


def test_publishers(site: FakeSite, run: Run) -> None:
    names = [line["name"] for line in run("publisher", "list")[1]]
    assert names == ["Acme", "Client"]


def test_login_then_logout(
    site: FakeSite, run: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AIPRESS24_TOKEN")
    assert run("auth", "status")[0] == 1
    monkeypatch.setattr("sys.stdin", io.StringIO("a24_secret\n"))
    status, (line,), err = run("auth", "login")
    assert (status, line["name"]) == (0, "Pia Ar")
    assert "a24_secret" not in err
    path = tmp_path / "config" / "aipress24" / "tokens.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert find_token(URL) == "a24_secret"
    assert find_token("https://other.test") == ""

    assert run("auth", "status")[1][0]["organisation"] == "Acme"
    assert run("auth", "logout")[0] == 0
    assert find_token(URL) == ""
    assert run("auth", "logout")[0] == 1


def test_a_token_file_others_can_read_is_refused(
    site: FakeSite, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AIPRESS24_TOKEN")
    store_token(URL, "a24_x").chmod(0o644)
    with pytest.raises(CliError, match="chmod 600"):
        find_token(URL)


class _Transport(Client):
    """Answers with the statuses it is given, one after the other."""

    statuses: list[int]

    def _open(self, url, headers, method="GET", data=None):
        return self.statuses.pop(0), b"{}"


class FlakyClient(RetryingClient, _Transport):
    def __init__(self, *statuses: int) -> None:
        super().__init__("a24_x", URL)
        self.statuses = list(statuses)


def test_only_reads_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(site_module, "RETRY_DELAYS", (0, 0))
    assert FlakyClient(502, 503, 200).me() == {}
    for client, call in (
        (FlakyClient(502, 502, 502), lambda c: c.me()),
        (FlakyClient(404), lambda c: c.me()),
        (FlakyClient(502), lambda c: c.create("x", {})),
    ):
        with pytest.raises(ApiError):
            call(client)
        assert client.statuses == []
