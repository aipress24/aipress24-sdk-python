# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""What is common to the archives of all networks."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Attachment:
    """An image of a message; ``content`` is None if the archive lacks it."""

    name: str
    caption: str
    size: int = 0
    content: bytes | None = None


@dataclass(frozen=True)
class Message:
    """A public message, or a thread of them."""

    key: str
    url: str
    published: datetime
    text: str
    images: tuple[Attachment, ...] = ()
    # Why it is not to be published by default, if so.
    reason: str = ""


@dataclass(frozen=True)
class Archive:
    """The public messages of an account, by key, oldest first."""

    path: Path
    network: str
    messages: Mapping[str, Message]
    # What is never published: private messages, texts of others...
    ignored: Counter[str]


def join_thread(key: str, parts: list[Message]) -> Message:
    """A thread is published as one message, dated from its first part."""
    first = parts[0]
    text = "\n\n".join(part.text for part in parts if part.text)
    images = tuple(image for part in parts for image in part.images)
    return Message(key, first.url, first.published, text, images, first.reason)


def oldest_first(messages: list[Message]) -> dict[str, Message]:
    ordered = sorted(messages, key=lambda message: message.published)
    return {message.key: message for message in ordered}
