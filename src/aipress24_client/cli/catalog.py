# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The table in which documents are sorted and classified."""

from __future__ import annotations

import csv
import io
import os
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .archives import Message, is_archive, read_archive
from .document import CLASSIFICATION, SUFFIXES, read_raw
from .errors import CliError
from .message_document import BARE, is_bare, title_of
from .similar import find_similar

SKIP = "skip"
POST = "post"
TYPES = ("press-release", "article", "event", POST, SKIP)
VALUE_COLUMNS = ("reference", "title", "published_at", "publisher", *CLASSIFICATION)
COLUMNS = ("source", "type", *VALUE_COLUMNS, "note")


@dataclass(frozen=True)
class Row:
    """One document of a catalog."""

    source: Path
    type: str
    values: Mapping[str, str]
    # The message, when the source is an archive.
    key: str = ""


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
        source, key = _split_source(line["source"].strip())
        rows.append(Row(catalog.parent / source, kind, values, key))
    return rows


@dataclass
class Listing:
    """The lines for new documents, and what was left out."""

    lines: list[dict[str, str]]
    ignored: Counter[str]


def create(catalog: Path, paths: Iterable[Path]) -> Listing:
    """Write a new catalog."""
    listing = _list_documents(catalog, paths, [])
    try:
        with catalog.open("x", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, COLUMNS)
            writer.writeheader()
            writer.writerows(listing.lines)
    except FileExistsError as error:
        raise CliError(f"{catalog} exists: use 'catalog update'.") from error
    return listing


def update(catalog: Path, paths: Iterable[Path]) -> Listing:
    """Append the documents it does not list yet."""
    listing = _list_documents(catalog, paths, read_rows(catalog))
    if listing.lines:
        header, _ = _read(catalog)
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(
            buffer, header, extrasaction="ignore", delimiter=_delimiter(catalog)
        )
        writer.writerows(listing.lines)
        text = catalog.read_text(encoding="utf-8-sig")
        separator = "" if text.endswith("\n") else "\n"
        with catalog.open("a", encoding="utf-8", newline="") as file:
            file.write(separator + buffer.getvalue())
    return listing


def _list_documents(
    catalog: Path, paths: Iterable[Path], rows: Iterable[Row]
) -> Listing:
    listing = Listing([], Counter())
    known = {(row.source.resolve(), row.key) for row in rows}
    references = {row.values["reference"] for row in rows if "reference" in row.values}
    kept = [
        read_archive(row.source).messages[row.key]
        for row in rows
        if row.type == POST and is_archive(row.source)
    ]
    for path in find_documents(paths):
        if is_archive(path):
            archive = read_archive(path)
            listing.ignored.update(archive.ignored)
            for message in archive.messages.values():
                if message.url not in references:
                    references.add(message.url)
                    line = _describe_message(catalog, path, message, kept)
                    listing.lines.append(line)
                    if line["type"] == POST:
                        kept.append(message)
        elif (path.resolve(), "") not in known:
            line = _describe(catalog, path)
            if not line["reference"] or line["reference"] not in references:
                listing.lines.append(line)
    return listing


def find_documents(paths: Iterable[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_file():  # archives too, but only when they are named
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


def _describe_message(
    catalog: Path, path: Path, message: Message, kept: Iterable[Message]
) -> dict[str, str]:
    note = message.reason
    if not note and (same := find_similar(message, kept)):
        note = f"same as {same.url}"
    if not note and is_bare(message) and not any(i.content for i in message.images):
        note = BARE
    return {
        **dict.fromkeys(COLUMNS, ""),
        "source": f"{_relative(catalog, path)}#{message.key}",
        "type": SKIP if note else POST,
        "reference": message.url,
        "title": title_of(message),
        "published_at": message.published.isoformat(),
        "note": note,
    }


def _describe(catalog: Path, path: Path) -> dict[str, str]:
    try:
        matter = read_raw(path).matter
    except (CliError, OSError, UnicodeDecodeError) as error:
        matter = {}
        note = f"cannot be read: {error}"
    else:
        note = ""
    return {
        "source": _relative(catalog, path),
        "type": "",
        **{key: _cell(matter.get(key)) for key in VALUE_COLUMNS},
        "note": note,
    }


def _relative(catalog: Path, path: Path) -> str:
    base = catalog.parent.resolve()
    return Path(os.path.relpath(path.resolve(), base)).as_posix()


def _split_source(source: str) -> tuple[str, str]:
    path, mark, key = source.rpartition("#")
    return (path, key) if mark and is_archive(Path(path)) else (source, "")


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
