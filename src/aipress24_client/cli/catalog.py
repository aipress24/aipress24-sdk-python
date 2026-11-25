# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The table in which documents are sorted and classified."""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .document import CLASSIFICATION, SUFFIXES, read_raw
from .errors import CliError

SKIP = "skip"
TYPES = ("press-release", "article", "event", SKIP)
VALUE_COLUMNS = ("reference", "title", "published_at", "publisher", *CLASSIFICATION)
COLUMNS = ("source", "type", *VALUE_COLUMNS, "note")


@dataclass(frozen=True)
class Row:
    """One document of a catalog."""

    source: Path
    type: str
    values: Mapping[str, str]


def read_rows(catalog: Path) -> list[Row]:
    header, lines = _read(catalog)
    missing = {"source", "type"} - set(header)
    if missing:
        raise CliError(f"{catalog}: no column {', '.join(sorted(missing))}")
    rows = []
    for number, line in enumerate(lines, start=2):
        kind = line["type"].strip()
        if kind and kind not in TYPES:
            raise CliError(
                f"{catalog}, line {number}: type {kind!r} is not "
                f"{', '.join(TYPES)} or empty"
            )
        values = {
            key: line[key].strip()
            for key in VALUE_COLUMNS
            if key in line and line[key].strip()
        }
        rows.append(Row(catalog.parent / line["source"].strip(), kind, values))
    return rows


def create(catalog: Path, paths: Iterable[Path]) -> int:
    """Write a new catalog; return how many documents it lists."""
    rows = [_describe(catalog, path) for path in find_documents(paths)]
    try:
        with catalog.open("x", encoding="utf-8-sig", newline="") as file:
            _write(file, COLUMNS, rows)
    except FileExistsError as error:
        raise CliError(f"{catalog} exists: use 'catalog update'.") from error
    return len(rows)


def update(catalog: Path, paths: Iterable[Path]) -> int:
    """Append the documents it does not list yet; return how many."""
    known = {row.source.resolve() for row in read_rows(catalog)}
    new = [path for path in find_documents(paths) if path.resolve() not in known]
    if new:
        header, _ = _read(catalog)
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(
            buffer, header, extrasaction="ignore", delimiter=_delimiter(catalog)
        )
        writer.writerows(_describe(catalog, path) for path in new)
        text = catalog.read_text(encoding="utf-8-sig")
        separator = "" if text.endswith("\n") else "\n"
        with catalog.open("a", encoding="utf-8", newline="") as file:
            file.write(separator + buffer.getvalue())
    return len(new)


def find_documents(paths: Iterable[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from sorted(
                found
                for found in path.rglob("*")
                if found.suffix.lower() in SUFFIXES
                and not any(
                    part.startswith(".") for part in found.relative_to(path).parts
                )
            )
        else:
            raise CliError(f"{path} does not exist.")


def _describe(catalog: Path, path: Path) -> dict[str, str]:
    base = catalog.parent.resolve()
    source = path.resolve()
    try:
        matter = read_raw(path).matter
    except (CliError, OSError, UnicodeDecodeError) as error:
        matter = {}
        note = f"cannot be read: {error}"
    else:
        note = ""
    return {
        "source": Path(os.path.relpath(source, base)).as_posix(),
        "type": "",
        **{key: _cell(matter.get(key)) for key in VALUE_COLUMNS},
        "note": note,
    }


def _cell(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return "" if value is None else str(value)


def _read(catalog: Path) -> tuple[list[str], list[dict[str, str]]]:
    text = catalog.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(
        io.StringIO(text, newline=""), delimiter=_delimiter(catalog), restval=""
    )
    lines = list(reader)
    if any(None in line for line in lines):
        raise CliError(f"{catalog}: a line has more cells than there are columns")
    return [name or "" for name in reader.fieldnames or []], lines


def _delimiter(catalog: Path) -> str:
    """Spreadsheets save with a semicolon or a tab in some languages."""
    with catalog.open(encoding="utf-8-sig") as file:
        header = file.readline()
    return max(",;\t", key=header.count)


def _write(
    file: io.TextIOBase, header: Iterable[str], rows: Iterable[Mapping[str, str]]
) -> None:
    writer = csv.DictWriter(file, tuple(header))
    writer.writeheader()
    writer.writerows(rows)
