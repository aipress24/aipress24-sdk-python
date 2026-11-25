# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Read the documents: Markdown with a front matter, or HTML."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import yaml
from bs4 import Tag
from markdown_it import MarkdownIt

from .. import PressReleaseImage
from .errors import CliError
from .html import FoundImage, clean, is_url, parse, plain, take_title

MARKDOWN_SUFFIXES = (".md", ".markdown")
HTML_SUFFIXES = (".html", ".htm")
SUFFIXES = (*MARKDOWN_SUFFIXES, *HTML_SUFFIXES)

# Document key -> API field.
TEXT_KEYS = {
    "title": "titre",
    "summary": "chapo",
    "genre": "genre",
    "section": "section",
    "topic": "topic",
    "sector": "sector",
    "language": "language",
    "address": "address",
    "country": "pays_zip_ville",
    "city": "pays_zip_ville_detail",
}
CLASSIFICATION = ("genre", "section", "topic", "sector")
REQUIRED_TO_PUBLISH = {
    "title": "titre",
    "text": "contenu",
    **{key: key for key in CLASSIFICATION},
}
OTHER_KEYS = {"reference", "publisher", "published_at", "embargoed_until", "images"}
IMAGE_KEYS = {"file", "caption", "copyright"}
MAX_IMAGE_SIZE = 4 * 1024 * 1024
MAX_REFERENCE = 500
FIRST_YEAR = 2000

_PARIS = ZoneInfo("Europe/Paris")
# Of a bare date: the same day in Paris and in UTC, and rarely still to come.
_DATE_TIME = time(6, tzinfo=_PARIS)


@dataclass(frozen=True)
class Image:
    """An image of the carousel."""

    name: str
    content: bytes
    caption: str
    copyright: str

    @property
    def key(self) -> tuple[str | None, str, str]:
        digest = hashlib.sha256(self.content).hexdigest()
        return digest, self.caption, self.copyright

    def matches(self, uploaded: PressReleaseImage) -> bool:
        return self.key == image_key(uploaded)


def image_key(uploaded: PressReleaseImage) -> tuple[str | None, str, str]:
    return uploaded["sha256"], uploaded["caption"], uploaded["copyright"]


@dataclass(frozen=True)
class Document:
    """A document, with everything that is wrong in it."""

    source: Path
    # The folder which remembers what was sent.
    home: Path
    title: str
    reference: str
    publisher: str
    fields: Mapping[str, Any]
    images: tuple[Image, ...]
    problems: tuple[str, ...]
    warnings: tuple[str, ...]

    def with_problems(self, *problems: str) -> Document:
        return replace(self, problems=(*self.problems, *problems))


@dataclass(frozen=True)
class Raw:
    """What a file says, before it is checked."""

    matter: Mapping[str, Any]
    root: Tag


def load_document(
    path: Path,
    *,
    home: Path | None = None,
    overrides: Mapping[str, str] | None = None,
) -> Document:
    """Read a document; ``overrides`` win over what it says."""
    home = home or path.parent
    try:
        raw = read_raw(path)
    except (CliError, OSError, UnicodeDecodeError) as error:
        return Document(path, home, path.name, "", "", {}, (), (str(error),), ())
    return _Reader(path, home, {**raw.matter, **(overrides or {})}).read(raw.root)


def read_raw(path: Path) -> Raw:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in HTML_SUFFIXES:
        return _read_html(text)
    if path.suffix.lower() in MARKDOWN_SUFFIXES:
        return _read_markdown(text)
    raise CliError(f"not one of {', '.join(SUFFIXES)}")


def _read_markdown(text: str) -> Raw:
    matter, body = _split_front_matter(text)
    markdown = MarkdownIt("commonmark", {"html": True}).enable("table")
    root = parse(markdown.render(body))
    if not matter.get("title") and (title := take_title(root)):
        matter = {**matter, "title": title}
    return Raw(matter, root)


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        return {}, text
    markers = [index for index, line in enumerate(lines) if line.rstrip() == "---"]
    if len(markers) < 2:
        raise CliError("the front matter has no closing '---'")
    try:
        matter = yaml.safe_load("".join(lines[1 : markers[1]]))
    except yaml.YAMLError as error:
        reason = " ".join(str(error).split())
        raise CliError(f"invalid front matter: {reason}") from error
    if not isinstance(matter, dict):
        raise CliError("the front matter must be a list of 'key: value' lines")
    return {str(key): value for key, value in matter.items()}, "".join(
        lines[markers[1] + 1 :]
    )


def _read_html(text: str) -> Raw:
    soup = parse(text)
    root = soup.find("article") or soup.find("main") or soup.find("body") or soup
    canonical = soup.find("link", rel="canonical")
    heading = take_title(root)
    page_title = plain(soup.title) if soup.title else ""
    matter = {
        "title": heading or _meta(soup, "og:title") or page_title,
        "summary": _meta(soup, "description") or _meta(soup, "og:description"),
        "reference": str(canonical["href"])
        if canonical and canonical.get("href")
        else _meta(soup, "og:url"),
        "published_at": _meta(soup, "article:published_time"),
    }
    return Raw({key: value for key, value in matter.items() if value}, root)


def _meta(soup: Tag, name: str) -> str:
    tag = soup.find("meta", attrs={"name": name}) or soup.find(
        "meta", attrs={"property": name}
    )
    return str(tag.get("content") or "").strip() if tag else ""


class _Reader:
    """Check the values of one document, collecting every problem."""

    def __init__(self, path: Path, home: Path, matter: Mapping[str, Any]) -> None:
        self.path = path
        self.home = home
        self.matter = matter
        self.problems: list[str] = []
        self.warnings: list[str] = []

    def read(self, root: Tag) -> Document:
        unknown = sorted(self.matter.keys() - TEXT_KEYS.keys() - OTHER_KEYS)
        if unknown:
            self.warnings.append(f"ignored: {', '.join(unknown)}")
        fields: dict[str, Any] = {
            field: self.text(key)
            for key, field in TEXT_KEYS.items()
            if key in self.matter
        }
        if not fields.get("titre"):
            self.problems.append("title: missing")
        reference = self.text("reference")
        if not reference:
            self.problems.append(
                "reference: missing (the URL of the original, or any stable name)"
            )
        elif len(reference) > MAX_REFERENCE:
            self.problems.append(f"reference: over {MAX_REFERENCE} characters")
        else:
            fields["external_ref"] = reference
        self.read_date(fields, "published_at", published_at)
        self.read_date(fields, "embargoed_until", to_moment)

        body = clean(root, reference)
        self.warnings.extend(body.warnings)
        fields["contenu"] = body.html
        return Document(
            source=self.path,
            home=self.home,
            title=fields.get("titre") or self.path.name,
            reference=reference,
            publisher=self.publisher(),
            fields=fields,
            images=self.images(body.images),
            problems=tuple(self.problems),
            warnings=tuple(self.warnings),
        )

    def text(self, key: str) -> str:
        value = self.matter.get(key)
        if value is None:
            return ""
        if not isinstance(value, str):
            self.problems.append(f"{key}: {value!r} is not a text, put it in quotes")
            return ""
        return value.strip()

    def publisher(self) -> str:
        value = self.matter.get("publisher")
        return str(value) if type(value) is int else self.text("publisher")

    def read_date(
        self, fields: dict[str, Any], key: str, convert: Callable[[object], datetime]
    ) -> None:
        value = self.matter.get(key)
        if value in (None, ""):
            return
        try:
            fields[key] = convert(value).isoformat()
        except ValueError as error:
            self.problems.append(f"{key}: {error}")

    def images(self, found: tuple[FoundImage, ...]) -> tuple[Image, ...]:
        images: dict[Path, Image] = {}
        entries = self.matter.get("images") or []
        if not isinstance(entries, list):
            self.problems.append("images: expected a list")
            entries = []
        for entry in entries:
            self.add_listed(images, entry)
        listed = len(images)
        for image in found:
            if is_url(image.src) or image.src.startswith(("//", "data:")):
                self.warnings.append(
                    f"image not sent, as it is not a file: {image.src[:80]}"
                )
            else:
                self.add_file(images, unquote(image.src), image.caption, "")
        if len(images) > listed:
            self.warnings.append(
                f"moved from the text to the carousel: {len(images) - listed} image(s)"
            )
        return tuple(images.values())

    def add_listed(self, images: dict[Path, Image], entry: object) -> None:
        if isinstance(entry, str):
            entry = {"file": entry}
        if not isinstance(entry, dict) or not (
            {"file"} <= entry.keys() <= IMAGE_KEYS
            and all(isinstance(value, str) for value in entry.values())
        ):
            self.problems.append(
                f"images: expected texts for file, caption and copyright, not {entry!r}"
            )
            return
        caption, copyright = entry.get("caption", ""), entry.get("copyright", "")
        self.add_file(images, entry["file"], caption, copyright)

    def add_file(
        self, images: dict[Path, Image], name: str, caption: str, copyright: str
    ) -> None:
        # Resolved, so that neither '..' nor a link can send a file from elsewhere.
        path = (self.path.parent / name).resolve()
        root = self.path.parent.resolve()
        if root.is_relative_to(self.home.resolve()):
            root = self.home.resolve()
        if path in images:
            return
        if not path.is_relative_to(root):
            self.problems.append(f"image {name}: outside of {root}")
        elif not path.is_file():
            self.problems.append(f"image {name}: not found")
        elif path.stat().st_size >= MAX_IMAGE_SIZE:
            self.problems.append(f"image {name}: too large, the limit is 4 MB")
        elif not is_image(content := path.read_bytes()):
            self.problems.append(f"image {name}: not a JPEG, PNG, GIF, WebP or AVIF")
        else:
            images[path] = Image(path.name, content, caption.strip(), copyright.strip())


def published_at(value: object) -> datetime:
    moment = to_moment(value, _DATE_TIME)
    if moment.astimezone(UTC).year < FIRST_YEAR:
        msg = f"{value} is before {FIRST_YEAR}"
        raise ValueError(msg)
    if moment > datetime.now(UTC):
        msg = f"{value} is in the future"
        raise ValueError(msg)
    return moment


def to_moment(value: object, default: time | None = None) -> datetime:
    if isinstance(value, str):
        value = _parse_date(value.strip())
    if isinstance(value, datetime):
        if value.tzinfo:
            return value
    elif isinstance(value, date) and default:
        return datetime.combine(value, default)
    example = "2026-12-01T08:00:00+01:00"
    expected = f"2026-12-01 or {example}" if default else example
    msg = f"{value} should be like {expected}"
    raise ValueError(msg)


def _parse_date(text: str) -> date | str:
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return text


def is_image(content: bytes) -> bool:
    return (
        content.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF8"))
        or (content[:4] == b"RIFF" and content[8:12] == b"WEBP")
        or (content[4:8] == b"ftyp" and content[8:12] in (b"avif", b"avis"))
    )
