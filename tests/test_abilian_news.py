# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The conversion of the abilian.com news."""

from __future__ import annotations

from pathlib import Path

import abilian_news
from conftest import PNG

from aipress24_client.cli.catalog import read_rows
from aipress24_client.cli.sources import load_row

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


def test_a_news_becomes_a_document(tmp_path: Path) -> None:
    site = tmp_path / "site"
    source = site / "content" / "fr" / "news" / "wendelin-projet-big-data"
    source.mkdir(parents=True)
    (source / "contents.lr").write_text(NEWS, encoding="utf-8")
    for name in ("illustrations/abilian.png", "images/a.png"):
        image = site / "assets" / "static" / name
        image.parent.mkdir(parents=True)
        image.write_bytes(PNG)

    output = tmp_path / "output"
    abilian_news.main(site, output)
    catalog = output / "catalog.csv"
    (row,) = read_rows(catalog)
    document = load_row(catalog, row)

    assert row.type == "press-release"
    assert document.problems == ()
    assert document.title == "Un: titre"
    assert document.fields["chapo"] == "Un chapo sur deux lignes."
    assert document.fields["genre"] == "Business / Financement, levée de fonds"
    assert document.fields["published_at"] == "2025-02-01T06:00:00+01:00"
    html = document.fields["contenu"]
    assert 'href="https://abilian.com/fr/x/"' in html
    assert html.count("<hr") == 2
    assert "<h2" not in html
    assert [(image.name, image.caption) for image in document.images] == [
        ("abilian.png", ""),
        ("a.png", "Un schéma"),
    ]

    catalog.write_text("kept")
    abilian_news.main(site, output)
    assert catalog.read_text() == "kept"
