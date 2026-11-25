# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Recognise a message published on several networks."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import timedelta
from difflib import SequenceMatcher

from .archives import Message
from .vocabulary import fold

MAX_DELAY = timedelta(days=3)
MIN_RATIO = 0.85
# When they also share a link.
MIN_RATIO_WITH_LINK = 0.65
MIN_LENGTH = 25
_URL = re.compile(r"https?://\S+")
_MENTION = re.compile(r"@\S+")


def find_similar(message: Message, others: Iterable[Message]) -> Message | None:
    """The first of the others which seems to be the same message."""
    return next((other for other in others if _is_same(message, other)), None)


def _is_same(one: Message, other: Message) -> bool:
    if abs(one.published - other.published) > MAX_DELAY:
        return False
    links, other_links = _links(one.text), _links(other.text)
    first, second = _words(one.text), _words(other.text)
    shortest = min(len(first), len(second))
    if shortest < MIN_LENGTH:
        return bool(links) and links == other_links
    # A network may have shortened the text.
    ratio = max(_ratio(first, second), _ratio(first[:shortest], second[:shortest]))
    return ratio >= (MIN_RATIO_WITH_LINK if links & other_links else MIN_RATIO)


def _ratio(first: str, second: str) -> float:
    return SequenceMatcher(None, first, second, autojunk=False).ratio()


def _words(text: str) -> str:
    bare = _MENTION.sub(" ", _URL.sub(" ", fold(text)))
    return " ".join(re.findall(r"\w+", bare))


def _links(text: str) -> set[str]:
    return {url.rstrip("/.,;:!?)") for url in _URL.findall(text)}
