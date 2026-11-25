# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Bluesky: the repository which can be exported in the settings.

It holds no image, and neither the name of the account nor those it answers to.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from .car import read_records
from .message import Archive, Attachment, Message, join_thread, oldest_first

_POST = "app.bsky.feed.post"
_REPOST = "app.bsky.feed.repost"
_LINK = "app.bsky.richtext.facet#link"
_URL = re.compile(r"https?://\S+")


def read(path: Path) -> Archive:
    did, records = read_records(path)
    posts: dict[str, Mapping[str, Any]] = {}
    ignored: Counter[str] = Counter()
    for key, record in records.items():
        kind, _, name = key.partition("/")
        if kind == _POST:
            posts[f"at://{did}/{key}"] = record
        elif kind == _REPOST:
            ignored["repost"] += 1
    threads: dict[str, list[Message]] = {}
    found = []
    for uri, post in posts.items():
        name = uri.rpartition("/")[2]
        root = _own_root(posts, uri)
        reason = ""
        if root is None:
            parent = post["reply"]["parent"]["uri"]
            reason = "in the thread of someone else" if parent in posts else "reply"
        message = _message(did, name, post, reason)
        if root is None:
            found.append(message)
        else:
            threads.setdefault(root, []).append(message)
    for root, parts in threads.items():
        parts.sort(key=lambda part: part.published)
        found.append(join_thread(root.rpartition("/")[2], parts))
    return Archive(path, "Bluesky", oldest_first(found), ignored)


def _own_root(posts: Mapping[str, Mapping[str, Any]], uri: str) -> str | None:
    """The start of the thread, if the author is alone from there to this post."""
    while "reply" in posts[uri]:
        uri = posts[uri]["reply"]["parent"]["uri"]
        if uri not in posts:
            return None
    return uri


def _message(did: str, name: str, post: Mapping[str, Any], reason: str) -> Message:
    embed = post.get("embed") or {}
    media = embed.get("media") or embed
    images = tuple(
        Attachment(
            f"{image['image']['ref']}.jpg",
            image.get("alt") or "",
            image["image"]["size"],
        )
        for image in media.get("images") or []
    )
    return Message(
        key=name,
        url=f"https://bsky.app/profile/{did}/post/{name}",
        published=datetime.fromisoformat(post["createdAt"]),
        text=_text(post, media.get("external")),
        images=images,
        reason=reason,
    )


def _text(post: Mapping[str, Any], card: Mapping[str, Any] | None) -> str:
    """The text, with its links in full, and the link of its card."""
    text = post["text"].encode()
    for facet in sorted(
        post.get("facets") or [], key=lambda f: -f["index"]["byteStart"]
    ):
        urls = [f["uri"] for f in facet["features"] if f["$type"] == _LINK]
        if urls:
            start, end = facet["index"]["byteStart"], facet["index"]["byteEnd"]
            text = text[:start] + urls[0].encode() + text[end:]
    result = text.decode(errors="replace").strip()
    if card:
        if not _URL.sub("", result).strip():
            result = f"{card['title']}\n{result}".strip()
        if card["uri"] not in result:
            result = f"{result}\n\n{card['uri']}".strip()
    return result
