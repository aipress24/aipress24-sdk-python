# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Read a message of an archive as a document."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from .archives import Message, read_archive
from .document import MAX_IMAGE_SIZE, Document, Image, is_image, published_at
from .errors import CliError
from .links import Link, expand, find_links

BARE = "no text and no image, mentions aside"
MAX_IMAGES = 12
MAX_TEXT_LENGTH = 10_000
_TITLE_LENGTH = 100
_MENTION = re.compile(r"@\S+")


def load_message(
    path: Path,
    key: str,
    *,
    home: Path,
    overrides: Mapping[str, str],
    links: Mapping[str, Link] = MappingProxyType({}),
) -> Document:
    """Read a message; a catalog may correct its date, its reference, its links."""
    source = path.with_name(f"{path.name}#{key}")
    try:
        message = read_archive(path).messages.get(key)
    except (CliError, OSError) as error:
        return Document(source, home, source.name, "", "", {}, (), (str(error),), ())
    if message is None:
        problem = "not in the archive, or not public"
        return Document(source, home, source.name, "", "", {}, (), (problem,), ())
    message = replace(message, text=expand(message.text, links))
    problems = []
    warnings = []
    images = []
    if short := find_links([message.text]):
        warnings.append(f"shortened links: {', '.join(short)}")
    for image in message.images:
        if not image.is_present:
            warnings.append(f"image {image.name}: not in the archive")
        elif image.size >= MAX_IMAGE_SIZE:
            problems.append(f"image {image.name}: too large, the limit is 4 MB")
        elif not is_image(content := image.read()):
            warnings.append(f"not an image, not sent: {image.name}")
        else:
            images.append(Image(image.name, content, image.caption, ""))
    if len(images) > MAX_IMAGES:
        problems.append(f"{len(images)} images, the limit is {MAX_IMAGES}")
    if len(message.text) > MAX_TEXT_LENGTH:
        problems.append(f"over {MAX_TEXT_LENGTH} characters")
    if not images and is_bare(message):
        problems.append(BARE)
    reference = overrides.get("reference", message.url)
    fields = {"content": message.text, "external_ref": reference}
    try:
        date = overrides.get("published_at") or message.published
        fields["published_at"] = published_at(date).isoformat()
    except ValueError as error:
        problems.append(f"published_at: {error}")
    return Document(
        source=source,
        home=home,
        title=title_of(message),
        reference=reference,
        publisher="",
        fields=fields,
        images=tuple(images),
        problems=tuple(problems),
        warnings=tuple(warnings),
    )


def message_text(path: Path, key: str) -> str:
    """The text of a message, as it is in the archive."""
    message = read_archive(path).messages.get(key) if key else None
    return message.text if message else ""


def is_bare(message: Message) -> bool:
    """Is there nothing to read in the text?"""
    return not _MENTION.sub("", message.text).strip()


def title_of(message: Message) -> str:
    """The beginning of the text, to recognise the message."""
    line = " ".join(message.text.split())
    if len(line) > _TITLE_LENGTH:
        line = f"{line[: _TITLE_LENGTH - 1]}…"
    return line or "(no text)"
