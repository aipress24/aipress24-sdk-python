# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""A press release, read from a folder."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from markdown_it import MarkdownIt

from .. import PressReleaseImage
from .errors import CliError

MAX_IMAGE_SIZE = 4 * 1024 * 1024

TEXT_FIELDS = (
    "titre",
    "chapo",
    "genre",
    "section",
    "topic",
    "sector",
    "geo_localisation",
    "language",
    "address",
    "pays_zip_ville",
    "pays_zip_ville_detail",
)
CLASSIFICATION = ("genre", "section", "topic", "sector")
REQUIRED_TO_PUBLISH = ("titre", "contenu", *CLASSIFICATION)
FRONT_MATTER_KEYS = {*TEXT_FIELDS, "publisher_id", "embargoed_until", "images"}
IMAGE_KEYS = {"file", "caption", "copyright"}


@dataclass(frozen=True)
class Image:
    """An image of the carousel, as found in the folder."""

    name: str
    content: bytes
    caption: str
    copyright: str

    def matches(self, uploaded: PressReleaseImage) -> bool:
        return (
            hashlib.sha256(self.content).hexdigest(),
            self.caption,
            self.copyright,
        ) == (uploaded["sha256"], uploaded["caption"], uploaded["copyright"])


@dataclass(frozen=True)
class Release:
    """A press release, as found in the folder."""

    fields: dict[str, Any]
    images: tuple[Image, ...]

    def missing_to_publish(self) -> list[str]:
        return [
            field
            for field in REQUIRED_TO_PUBLISH
            if not self.fields.get(field, "").strip()
        ]


def load_release(folder: Path) -> Release:
    """Read and validate the folder."""
    if not folder.is_dir():
        raise CliError(f"{folder} is not a folder.")
    sources = sorted(folder.glob("*.md"))
    if len(sources) != 1:
        raise CliError(f"{folder} must contain one .md file, not {len(sources)}.")
    text = sources[0].read_text(encoding="utf-8-sig")
    matter, body = _split_front_matter(text)

    unknown = sorted(str(key) for key in matter.keys() - FRONT_MATTER_KEYS)
    if unknown:
        raise CliError(f"Unknown front matter: {', '.join(unknown)}.")
    fields: dict[str, Any] = {
        key: _text(key, value) for key, value in matter.items() if key in TEXT_FIELDS
    }
    if not fields.get("titre", ""):
        raise CliError("The front matter must give a titre.")
    if "publisher_id" in matter:
        fields["publisher_id"] = _publisher(matter["publisher_id"])
    if "embargoed_until" in matter:
        fields["embargoed_until"] = _embargo(matter["embargoed_until"])
    fields["contenu"] = _html(body)

    entries = matter.get("images") or []
    if not isinstance(entries, list):
        raise CliError("images: expected a list.")
    root = folder.resolve()
    return Release(fields, tuple(_load_image(root, entry) for entry in entries))


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines(keepends=True)
    markers = [index for index, line in enumerate(lines) if line.rstrip() == "---"]
    if len(markers) < 2 or markers[0] != 0:
        raise CliError("The file must start with a front matter between two '---'.")
    try:
        matter = yaml.safe_load("".join(lines[1 : markers[1]]))
    except yaml.YAMLError as error:
        raise CliError(f"Invalid front matter: {error}") from error
    if not isinstance(matter, dict):
        raise CliError("The front matter must be a list of 'key: value' lines.")
    return matter, "".join(lines[markers[1] + 1 :])


def _text(key: str, value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CliError(f"{key}: {value!r} is not a text, put it between quotes.")
    return value.strip()


def _publisher(value: object) -> int | None:
    if value is None or type(value) is int:
        return value
    raise CliError("publisher_id: expected a number.")


def _embargo(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CliError(
            "embargoed_until: expected a date, a time and a time zone, "
            "as in 2026-12-01T08:00:00+01:00."
        )
    return value.isoformat()


def _html(body: str) -> str:
    markdown = MarkdownIt("commonmark", {"html": False}).enable("table")
    images = [
        child
        for token in markdown.parse(body)
        for child in token.children or []
        if child.type == "image"
    ]
    if images:
        raise CliError("Images are not supported in the text: list them in images.")
    return str(markdown.render(body)).strip()


def _load_image(root: Path, entry: object) -> Image:
    if isinstance(entry, str):
        entry = {"file": entry}
    if not isinstance(entry, dict) or "file" not in entry or entry.keys() - IMAGE_KEYS:
        raise CliError(f"images: expected file, caption and copyright, not {entry!r}.")
    name = _text("file", entry["file"])
    path = (root / name).resolve()
    # Resolved, so that neither '..' nor a link can send a file from elsewhere.
    if not path.is_relative_to(root):
        raise CliError(f"{name} is outside the folder.")
    if not path.is_file():
        raise CliError(f"{name} does not exist.")
    if path.stat().st_size >= MAX_IMAGE_SIZE:
        raise CliError(f"{name} is too large: the limit is 4 MB.")
    return Image(
        path.name,
        path.read_bytes(),
        _text("caption", entry.get("caption")),
        _text("copyright", entry.get("copyright")),
    )
