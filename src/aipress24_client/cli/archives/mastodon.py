# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Mastodon: the archive which can be asked for in the preferences.

Only these are opened: the profile, the messages, and the images of messages. The
archive also holds likes and bookmarks.
"""

from __future__ import annotations

import json
import zipfile
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bs4 import NavigableString, Tag

from ..document import MAX_IMAGE_SIZE
from ..html import parse
from .message import Archive, Attachment, Message, join_thread, oldest_first

NAMES = {"actor.json", "outbox.json"}
MAX_OUTBOX_SIZE = 500 * 1024 * 1024
_PUBLIC = {"https://www.w3.org/ns/activitystreams#Public", "as:Public"}


def read(path: Path) -> Archive:
    with zipfile.ZipFile(path) as archive:
        if archive.getinfo("outbox.json").file_size > MAX_OUTBOX_SIZE:
            msg = "outbox.json is too large"
            raise ValueError(msg)
        activities = json.loads(archive.read("outbox.json"))["orderedItems"]
        sizes = {info.filename: info.file_size for info in archive.infolist()}
        ignored: Counter[str] = Counter()
        notes: dict[str, dict[str, Any]] = {}
        for activity in activities:
            note = activity["object"]
            if activity["type"] != "Create" or not isinstance(note, dict):
                ignored["boost"] += 1
            elif not _is_public(note):
                ignored["private"] += 1
            else:
                notes[note["id"]] = note
        messages = {
            identifier: _message(archive, sizes, note)
            for identifier, note in notes.items()
        }
    return Archive(path, "Mastodon", _threads(notes, messages), ignored)


def _is_public(note: Mapping[str, Any]) -> bool:
    return bool(_PUBLIC & {*_list(note.get("to")), *_list(note.get("cc"))})


def _list(value: Any) -> list[str]:
    return [value] if isinstance(value, str) else value or []


def _threads(
    notes: Mapping[str, Mapping[str, Any]], messages: Mapping[str, Message]
) -> dict[str, Message]:
    threads: dict[str, list[Message]] = {}
    found = []
    for identifier, message in messages.items():
        root = _root(notes, identifier)
        reason = _reason(notes, messages, identifier, root)
        if reason:
            found.append(replace(message, reason=reason))
        else:
            threads.setdefault(root, []).append(message)
    for root, parts in threads.items():
        parts.sort(key=lambda part: part.published)
        found.append(join_thread(messages[root].key, parts))
    return oldest_first(found)


def _reason(
    notes: Mapping[str, Mapping[str, Any]],
    messages: Mapping[str, Message],
    identifier: str,
    root: str,
) -> str:
    if notes[root].get("inReplyTo"):
        return "reply" if root == identifier else "in the thread of someone else"
    # The parent of a reply is forgotten when it is deleted.
    if messages[root].text.startswith("@"):
        return "reply to a deleted message"
    if not _PUBLIC & {*_list(notes[identifier].get("to"))}:
        return "unlisted"
    if identifier != root and not _PUBLIC & {*_list(notes[root].get("to"))}:
        return "unlisted"
    return ""


def _root(notes: Mapping[str, Mapping[str, Any]], identifier: str) -> str:
    seen = {identifier}
    while True:
        parent = notes[identifier].get("inReplyTo")
        if parent is None or parent not in notes or parent in seen:
            return identifier
        seen.add(parent)
        identifier = parent


def _message(
    archive: zipfile.ZipFile, sizes: Mapping[str, int], note: Mapping[str, Any]
) -> Message:
    return Message(
        key=note["id"].rstrip("/").rpartition("/")[2],
        url=note.get("url") or note["id"],
        published=datetime.fromisoformat(note["published"]),
        text=text_of(note.get("content") or ""),
        images=tuple(_images(archive, sizes, note.get("attachment") or [])),
    )


def _images(
    archive: zipfile.ZipFile,
    sizes: Mapping[str, int],
    attachments: Iterable[Mapping[str, Any]],
) -> Iterable[Attachment]:
    for attachment in attachments:
        # The others are previews of links.
        if "url" not in attachment:
            continue
        name = attachment["url"].lstrip("/")
        size = sizes.get(name, 0)
        readable = name in sizes and size < MAX_IMAGE_SIZE
        yield Attachment(
            name.rpartition("/")[2],
            attachment.get("name") or "",
            size,
            archive.read(name) if readable else None,
        )


def text_of(html: str) -> str:
    """The text of a message, with its links in full."""
    root = parse(html)
    for br in root.find_all("br"):
        br.replace_with("\n")
    for link in root.find_all("a", href=True):
        link.replace_with(NavigableString(_link_text(link)))
    paragraphs = root.find_all("p") or [root]
    texts = (paragraph.get_text().strip() for paragraph in paragraphs)
    return "\n\n".join(text for text in texts if text)


def _link_text(link: Tag) -> str:
    classes = link.get("class") or []
    href, text = str(link["href"]), link.get_text()
    if "mention" not in classes:
        return href
    if "hashtag" in classes or text.startswith("#"):
        return text
    return text if "@" in text[1:] else f"{text}@{urlsplit(href).netloc}"
