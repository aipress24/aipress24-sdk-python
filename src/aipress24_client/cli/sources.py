# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Find the documents a command is given."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from .catalog import Row, read_rows
from .document import SUFFIXES, Document, load_document
from .errors import CliError
from .html import is_url
from .links import Link, read_links
from .message_document import load_message


@dataclass
class Selection:
    """The documents of one type, and how many lines were left out."""

    documents: list[Document] = field(default_factory=list)
    left_out: Counter[str] = field(default_factory=Counter)


def is_item(target: str) -> bool:
    return target.isdigit() or is_url(target)


def select(
    sources: Sequence[Path],
    kind: str,
    only: Sequence[str] = (),
    limit: int | None = None,
) -> Selection:
    """Read the documents of type ``kind``."""
    selection = Selection()
    for source in sources:
        selection.documents.extend(_read_source(source, kind, only, selection))
    selection.documents = _flag_duplicates(selection.documents[:limit])
    return selection


def _read_source(
    source: Path, kind: str, only: Sequence[str], selection: Selection
) -> Iterator[Document]:
    if source.suffix.lower() == ".csv":
        links = read_links(source)
        for row in read_rows(source):
            if row.type != kind:
                selection.left_out[row.type or "undecided"] += 1
            else:
                document = load_row(source, row, links)
                if _matches(document, only):
                    yield document
    else:
        document = load_document(_single_document(source))
        if _matches(document, only):
            yield document


def load_row(catalog: Path, row: Row, links: Mapping[str, Link]) -> Document:
    home = catalog.parent
    if row.key:
        return load_message(
            row.source, row.key, home=home, overrides=row.values, links=links
        )
    return load_document(row.source, home=home, overrides=row.values)


def _matches(document: Document, only: Sequence[str]) -> bool:
    names = (document.source.as_posix(), document.source.name, document.reference)
    return not only or any(fnmatch(name, pattern) for name in names for pattern in only)


def _single_document(source: Path) -> Path:
    if source.is_file():
        return source
    if not source.is_dir():
        raise CliError(f"{source} does not exist.")
    found = sorted(path for path in source.iterdir() if path.suffix.lower() in SUFFIXES)
    if len(found) != 1:
        raise CliError(
            f"{source} holds {len(found)} documents instead of one. "
            "For several, use 'aipress24 catalog create'."
        )
    return found[0]


def _flag_duplicates(documents: list[Document]) -> list[Document]:
    counts = Counter(document.reference for document in documents)
    return [
        document.with_problems("reference: used by several documents")
        if document.reference and counts[document.reference] > 1
        else document
        for document in documents
    ]
