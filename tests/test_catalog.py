# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The table of documents."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from conftest import Run, make_folder, results
from fake_site import FakeSite


@pytest.fixture
def catalog(tmp_path: Path, run: Run) -> Path:
    news = tmp_path / "news"
    news.mkdir()
    for name in "abc":
        make_folder(news / name, name)
    path = tmp_path / "news.csv"
    assert run("catalog", "create", news, "-o", path)[0] == 0
    return path


def read(catalog: Path) -> list[dict[str, str]]:
    with catalog.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write(catalog: Path, rows: list[dict[str, str]], delimiter: str = ",") -> None:
    with catalog.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, rows[0], delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def set_types(catalog: Path, *types: str, **values: str) -> None:
    rows = [
        {**row, "type": kind, **values}
        for row, kind in zip(read(catalog), types, strict=True)
    ]
    write(catalog, rows)


def test_create_lists_what_the_documents_say(catalog: Path) -> None:
    rows = read(catalog)
    assert [row["source"] for row in rows] == [
        f"news/{name}/release.md" for name in "abc"
    ]
    assert rows[0]["type"] == ""
    assert rows[0]["reference"] == "https://acme.test/news/widgeta/"
    assert rows[0]["published_at"] == "2014-12-03"


def test_create_overwrites_nothing(catalog: Path, run: Run) -> None:
    before = catalog.read_bytes()
    status, _, err = run("catalog", "create", catalog.parent / "news", "-o", catalog)
    assert status == 1
    assert "catalog update" in err
    assert catalog.read_bytes() == before


def test_update_only_appends(catalog: Path, run: Run) -> None:
    set_types(catalog, "press-release", "skip", "")
    before = catalog.read_text()
    make_folder(catalog.parent / "news" / "d", "d")

    assert run("catalog", "update", catalog, catalog.parent / "news")[0] == 0
    assert catalog.read_text().startswith(before)
    assert [row["type"] for row in read(catalog)] == ["press-release", "skip", "", ""]
    assert run("catalog", "update", catalog, catalog.parent / "news")[1] == [
        {"catalog": str(catalog), "added": 0}
    ]


def test_only_the_lines_of_the_type_are_taken(
    catalog: Path, site: FakeSite, run: Run
) -> None:
    set_types(catalog, "press-release", "event", "")
    status, lines, err = run("press-release", "draft", catalog)
    assert status == 0
    assert results(lines) == ["created"]
    assert "1 event" in err
    assert "1 undecided" in err


def test_cells_win_unless_empty(catalog: Path, site: FakeSite, run: Run) -> None:
    set_types(catalog, "press-release", "", "", title="Nouveau titre", genre="")
    assert run("press-release", "draft", catalog)[0] == 0
    assert site.only()["titre"] == "Nouveau titre"
    assert site.only()["genre"] == "Annonce"


@pytest.mark.parametrize("delimiter", [";", "\t"])
def test_other_delimiters(
    catalog: Path, site: FakeSite, run: Run, delimiter: str
) -> None:
    set_types(catalog, "press-release", "", "")
    write(catalog, read(catalog), delimiter)
    assert run("press-release", "draft", catalog)[0] == 0
    make_folder(catalog.parent / "news" / "d", "d")
    assert run("catalog", "update", catalog, catalog.parent / "news")[0] == 0
    assert results(run("press-release", "draft", catalog)[1]) == ["unchanged"]


def test_only_and_limit(catalog: Path, site: FakeSite, run: Run) -> None:
    set_types(catalog, *["press-release"] * 3)
    assert len(run("press-release", "check", catalog, "--only", "*widgetb/")[1]) == 1
    assert len(run("press-release", "check", catalog, "--limit", 2)[1]) == 2


def test_a_reference_is_used_once(catalog: Path, site: FakeSite, run: Run) -> None:
    set_types(catalog, *["press-release"] * 3, reference="same")
    status, lines, _ = run("press-release", "draft", catalog)
    assert status == 1
    assert results(lines) == ["invalid"] * 3
    assert site.releases == {}


def test_an_unknown_type_is_refused(catalog: Path, site: FakeSite, run: Run) -> None:
    set_types(catalog, "press release", "", "")
    status, _, err = run("press-release", "check", catalog)
    assert status == 1
    assert "line 2" in err


def test_status_covers_every_type(catalog: Path, site: FakeSite, run: Run) -> None:
    set_types(catalog, "press-release", "event", "")
    run("press-release", "draft", catalog)
    status, lines, _ = run("catalog", "status", catalog)
    assert status == 0
    assert results(lines) == ["unchanged", "event", "undecided"]
    assert lines[0]["status"] == "draft"


def test_a_catalog_remembers_next_to_itself(
    catalog: Path, site: FakeSite, run: Run
) -> None:
    set_types(catalog, "press-release", "", "")
    run("press-release", "draft", catalog)
    assert (catalog.parent / ".aipress24").is_dir()
    assert not (catalog.parent / "news" / "a" / ".aipress24").exists()
