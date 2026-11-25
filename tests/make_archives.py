# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Make archives as the networks do."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

ACTOR = "https://social.test/users/me"
PUBLIC = "https://www.w3.org/ns/activitystreams#Public"
DID = "did:plc:me"


# --- Mastodon --------------------------------------------------------------


def note(key: str, content: str, **values: Any) -> dict[str, Any]:
    """A public message; ``reply`` is the key or the URL of its parent."""
    reply = values.pop("reply", None)
    if reply and not reply.startswith("https:"):
        reply = f"{ACTOR}/statuses/{reply}"
    images = values.pop("images", [])
    content_ = {
        "id": f"{ACTOR}/statuses/{key}",
        "type": "Note",
        "url": f"https://social.test/@me/{key}",
        "published": f"2024-05-01T10:00:{int(key):02}Z",
        "inReplyTo": reply,
        "to": [PUBLIC],
        "cc": [f"{ACTOR}/followers"],
        "content": content,
        "attachment": [
            {
                "type": "Document",
                "mediaType": "image/png",
                "url": f"/{name}",
                "name": alt,
            }
            for name, alt in images
        ],
        **values,
    }
    return {"type": "Create", "object": content_}


def make_mastodon(path: Path, *activities: Any, **files: bytes) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("actor.json", json.dumps({"id": ACTOR}))
        archive.writestr("outbox.json", json.dumps({"orderedItems": activities}))
        archive.writestr("likes.json", "not read")
        for name, content in files.items():
            archive.writestr(f"{name}.png", content)
    return path


# --- Bluesky ---------------------------------------------------------------


class Link(bytes):
    """A reference to a block."""


def encode(value: Any) -> bytes:
    match value:
        case None:
            return b"\xf6"
        case bool():
            return b"\xf5" if value else b"\xf4"
        case int():
            return _head(0, value) if value >= 0 else _head(1, -1 - value)
        case Link():
            return _head(6, 42) + encode(b"\x00" + bytes(value))
        case bytes():
            return _head(2, len(value)) + value
        case str():
            return _head(3, len(value.encode())) + value.encode()
        case list():
            return _head(4, len(value)) + b"".join(map(encode, value))
        case dict():
            items = (encode(key) + encode(item) for key, item in value.items())
            return _head(5, len(value)) + b"".join(items)
    raise TypeError(value)


def _head(major: int, number: int) -> bytes:
    for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
        if number < 24:
            return bytes([major << 5 | number])
        if number < 1 << (8 * size):
            return bytes([major << 5 | info]) + number.to_bytes(size, "big")
    raise ValueError(number)


def _varint(number: int) -> bytes:
    result = b""
    while number > 0x7F:
        result += bytes([number & 0x7F | 0x80])
        number >>= 7
    return result + bytes([number])


def post(text: str, *, second: int = 0, **values: Any) -> dict[str, Any]:
    return {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": f"2024-05-01T10:00:{second:02}.000Z",
        **values,
    }


def reply_to(uri: str) -> dict[str, Any]:
    return {"root": {"uri": uri}, "parent": {"uri": uri}}


def uri(key: str) -> str:
    return f"at://{DID}/app.bsky.feed.post/{key}"


def facet(text: str, part: str, **feature: str) -> dict[str, Any]:
    start = text.encode().index(part.encode())
    index = {"byteStart": start, "byteEnd": start + len(part.encode())}
    return {"index": index, "features": [feature]}


def make_car(path: Path, posts: dict[str, Any], **others: Any) -> Path:
    blocks = b""

    def add(value: Any) -> Link:
        nonlocal blocks
        content = encode(value)
        cid = b"\x01\x71\x12\x20" + hashlib.sha256(content).digest()
        blocks += _varint(len(cid) + len(content)) + cid + content
        return Link(cid)

    records = {f"app.bsky.feed.post/{key}": each for key, each in posts.items()}
    entries: list[dict[str, Any]] = []
    previous = b""
    for key in sorted({**records, **others}):
        name = key.encode()
        shared = 0
        while previous[shared : shared + 1] == name[shared : shared + 1] != b"":
            shared += 1
        value = add({**records, **others}[key])
        entries.append({"p": shared, "k": name[shared:], "v": value, "t": None})
        previous = name
    # The last entries are in a subtree, as in large repositories.
    head, last = entries[:-1], entries[-1:]
    if head:
        last[0] = {**last[0], "p": 0, "k": previous}
        head[-1]["t"] = add({"l": None, "e": last})
    tree = add({"l": None, "e": head or last})
    commit = add({"did": DID, "version": 3, "data": tree})
    header = encode({"roots": [commit], "version": 1})
    path.write_bytes(_varint(len(header)) + header + blocks)
    return path
