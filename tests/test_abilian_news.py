# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the conversion of the abilian.com news."""

from __future__ import annotations

from pathlib import Path

import abilian_news
import pytest

from aipress24_client.cli.release import load_release

NEWS = """title: [R&D] Un: titre
---
pub_date: 2025-02-01
---
body:

Voir [ici](/fr/x/).
<hr>
Suite.

----

![Un schéma](/static/images/a.png)
---
description:

Un *chapo*
sur deux lignes.
"""


def test_a_news_becomes_a_release(tmp_path: Path) -> None:
    source = tmp_path / "site" / "content" / "fr" / "news" / "x"
    source.mkdir(parents=True)
    (source / "contents.lr").write_text(NEWS, encoding="utf-8")
    for name in ("illustrations/abilian.png", "images/a.png"):
        image = tmp_path / "site" / "assets" / "static" / name
        image.parent.mkdir(parents=True)
        image.write_bytes(b"png")

    folder = tmp_path / "x"
    classification = abilian_news.Classification("g", "s", "t")
    abilian_news.convert(tmp_path / "site", "x", classification, folder)
    release = load_release(folder)

    assert release.missing_to_publish() == []
    assert release.fields["titre"] == "Un: titre"
    assert release.fields["chapo"] == "Un chapo sur deux lignes."
    html = release.fields["contenu"]
    assert "publié le 1er février 2025" in html
    assert 'href="https://abilian.com/fr/x/"' in html
    assert html.count("<hr") == 2
    assert "<h2" not in html
    assert [(image.name, image.caption) for image in release.images] == [
        ("abilian.png", ""),
        ("a.png", "Un schéma"),
    ]


def test_html_which_is_not_converted_is_refused() -> None:
    with pytest.raises(ValueError, match="iframe"):
        abilian_news.clean_markdown("<iframe src='x'></iframe>")
