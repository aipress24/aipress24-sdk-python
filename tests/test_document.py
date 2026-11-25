# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Reading documents."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import PNG, edit

from aipress24_client.cli.document import load_document

PAGE = """<!DOCTYPE html>
<html><head>
<title>Widget | Acme</title>
<link rel="canonical" href="https://acme.test/widget/">
<meta name="description" content="Un widget.">
<meta property="article:published_time" content="2014-12-03T09:00:00+01:00">
</head><body><nav>Menu</nav>
<main><h1>Acme lance <em>le Widget</em></h1>
<p>Du <b>texte</b> et un <a href="../contact/">lien</a>.</p>
<!-- secret -->
<script>alert(1)</script>
<figure><img src="my%20cover.png" alt="x"><figcaption>La <i>couverture</i></figcaption></figure>
<iframe src="https://video.test"></iframe>
</main></body></html>
"""


def load(folder: Path):
    return load_document(folder / "release.md")


def test_markdown(folder: Path) -> None:
    document = load(folder)

    assert document.problems == ()
    assert document.warnings == ()
    assert document.title == "Acme lance le Widget"
    assert document.fields["published_at"] == "2014-12-03T06:00:00+01:00"
    assert document.fields["external_ref"] == "https://acme.test/news/widget/"
    html = document.fields["contenu"]
    assert "<strong>widget</strong>" in html
    assert 'href="https://acme.test/contact/"' in html
    (image,) = document.images
    assert (image.name, image.caption) == ("cover.png", "La couverture")


def test_html(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text(PAGE, encoding="utf-8")
    (tmp_path / "my cover.png").write_bytes(PNG)
    document = load_document(path)

    assert document.problems == ()
    assert document.fields["titre"] == "Acme lance le Widget"
    assert document.fields["chapo"] == "Un widget."
    assert document.reference == "https://acme.test/widget/"
    assert document.fields["published_at"] == "2014-12-03T09:00:00+01:00"
    html = document.fields["contenu"]
    assert 'href="https://acme.test/contact/"' in html
    for absent in ("h1", "Menu", "secret", "alert", "img", "figure", "iframe"):
        assert absent not in html
    assert [(i.name, i.caption) for i in document.images] == [
        ("my cover.png", "La couverture")
    ]
    assert any("iframe" in warning for warning in document.warnings)
    assert any("carousel" in warning for warning in document.warnings)


def test_every_problem_is_reported(folder: Path) -> None:
    edit(folder, 'title: "Acme lance le Widget"', "title: 2014")
    edit(folder, "reference: https://acme.test/news/widget/\n", "")
    edit(folder, "published_at: 2014-12-03", "published_at: 03/12/2014")
    edit(folder, "cover.png", "missing.png")

    problems = " | ".join(load(folder).problems)
    for expected in (
        "title: 2014",
        "reference: missing",
        "published_at",
        "missing.png",
    ):
        assert expected in problems


@pytest.mark.parametrize(
    ("old", "new", "problem"),
    [
        ("2014-12-03", "1999-12-31", "before 2000"),
        ("2014-12-03", "2999-01-01", "in the future"),
        ("2014-12-03", "2014-12-03T09:00:00", "should be like"),
        ("published_at: 2014-12-03", "embargoed_until: 2026-12-01", "should be like"),
        ("title:", "title: [", "invalid front matter"),
        ("cover.png", "../secret.png", "outside"),
        ("cover.png", "/etc/hosts", "outside"),
        ("cover.png", "link.png", "outside"),
        ("cover.png", "text.png", "not a JPEG"),
        ("caption: La", "legende: La", "images: expected"),
    ],
)
def test_invalid_documents(folder: Path, old: str, new: str, problem: str) -> None:
    secret = folder.parent / "secret.png"
    secret.write_bytes(PNG)
    (folder / "link.png").symlink_to(secret)
    (folder / "text.png").write_text("text")
    edit(folder, old, new)

    assert problem in " | ".join(load(folder).problems)


def test_today_is_not_in_the_future(folder: Path) -> None:
    moment = datetime.now(UTC) - timedelta(minutes=1)
    edit(folder, "2014-12-03", moment.isoformat(timespec="seconds"))
    assert load(folder).problems == ()


def test_unknown_keys_are_only_mentioned(folder: Path) -> None:
    edit(folder, "genre:", "tags: [a]\ngenre:")
    document = load(folder)
    assert document.problems == ()
    assert document.warnings == ("ignored: tags",)


def test_images_of_the_text_follow_the_listed_ones(folder: Path) -> None:
    (folder / "other.png").write_bytes(PNG + b"other")
    edit(folder, "Un **widget**.", "Un widget.\n\n![Autre](other.png)\n![](cover.png)")
    document = load(folder)
    assert [image.name for image in document.images] == ["cover.png", "other.png"]
    assert "other.png" not in document.fields["contenu"]
    assert document.problems == ()


def test_remote_images_are_mentioned(folder: Path) -> None:
    edit(folder, "Un **widget**.", "![x](https://acme.test/x.png)")
    document = load(folder)
    assert document.problems == ()
    assert "https://acme.test/x.png" in document.warnings[0]


def test_relative_links_need_a_url_as_reference(folder: Path) -> None:
    edit(folder, "https://acme.test/news/widget/", "widget")
    assert "relative links" in load(folder).warnings[0]


def test_a_heading_gives_the_title_which_is_missing(tmp_path: Path) -> None:
    path = tmp_path / "plain.md"
    path.write_text("# Un titre\n\nDu texte.\n")
    document = load_document(path, overrides={"reference": "plain"})
    assert document.title == "Un titre"
    assert document.fields["contenu"] == "<p>Du texte.</p>"


def test_overrides_win(folder: Path) -> None:
    document = load_document(
        folder / "release.md",
        overrides={"title": "Autre", "published_at": "2015-01-02"},
    )
    assert document.title == "Autre"
    assert document.fields["published_at"].startswith("2015-01-02T06:00")


def test_an_unreadable_document_is_a_problem(tmp_path: Path) -> None:
    path = tmp_path / "latin.md"
    path.write_bytes(b"\xe9")
    assert load_document(path).problems
    assert load_document(tmp_path / "absent.md").problems
