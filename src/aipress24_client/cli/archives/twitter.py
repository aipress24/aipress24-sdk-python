# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Twitter: the archive which can be asked for in the settings.

Only these are opened: the manifest, the tweets, whether the account was protected,
and the images of tweets. The archive also holds direct messages, deleted tweets,
addresses and advertising data.
"""

from __future__ import annotations

import html
import json
import re
import zipfile
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import replace
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from .message import (
    Archive,
    Attachment,
    Message,
    join_thread,
    oldest_first,
    open_zip,
)

MANIFEST = "data/manifest.js"
NAMES = {MANIFEST}
MAX_TWEETS_SIZE = 1024 * 1024 * 1024
_PROTECTED = "data/protected-history.js"
_STATUS = re.compile(r"https?://(?:\w+\.)?(?:twitter|x)\.com/\w+/status(?:es)?/\d+")
_LINK_OR_MENTION = re.compile(r"https?://\S+|@\w+")
# From before quotes and retweets existed: the text of someone else.
_OLD_QUOTE = re.compile(r"^\W{0,2}[\"“”«]\s?@\w")
_OLD_RETWEET = re.compile(r"\b(?:RT|MT)\b[\s:]*[\"“]?@\w")


def read(path: Path) -> Archive:
    archive = open_zip(path)
    manifest = _load(archive, MANIFEST)
    user = manifest["userInfo"]
    sizes = {info.filename: info.file_size for info in archive.infolist()}
    was_protected = _PROTECTED in sizes and bool(_load(archive, _PROTECTED))
    ignored: Counter[str] = Counter()
    tweets: dict[str, dict[str, Any]] = {}
    for file in manifest["dataTypes"]["tweets"]["files"]:
        for item in _load(archive, file["fileName"]):
            tweet = item["tweet"]
            if tweet["full_text"].startswith("RT @"):
                ignored["retweet"] += 1
            else:
                tweets[tweet["id_str"]] = tweet
    messages = {
        key: _message(path, sizes, user["userName"], tweet)
        for key, tweet in tweets.items()
    }
    found = []
    threads: dict[str, list[Message]] = {}
    for key, message in messages.items():
        root = _root(tweets, key)
        if was_protected:
            reason = "the account was protected at some time"
        elif _is_reply(tweets[root]):
            reason = "reply" if root == key else "in the thread of someone else"
        else:
            threads.setdefault(root, []).append(message)
            continue
        found.append(replace(message, reason=reason))
    for root, parts in threads.items():
        parts.sort(key=lambda part: part.published)
        thread = join_thread(root, parts)
        found.append(replace(thread, reason=_reason(tweets[root], thread)))
    return Archive(path, "Twitter", oldest_first(found), ignored)


def _load(archive: zipfile.ZipFile, name: str) -> Any:
    """Files are scripts which assign one JSON value."""
    if archive.getinfo(name).file_size > MAX_TWEETS_SIZE:
        msg = f"{name} is too large"
        raise ValueError(msg)
    text = archive.read(name).decode()
    return json.loads(text[text.index("=") + 1 :])


def _root(tweets: Mapping[str, Mapping[str, Any]], key: str) -> str:
    seen = {key}
    while True:
        parent = tweets[key].get("in_reply_to_status_id_str")
        if parent is None or parent not in tweets or parent in seen:
            return key
        seen.add(parent)
        key = parent


def _is_reply(tweet: Mapping[str, Any]) -> bool:
    return (
        bool(tweet.get("in_reply_to_status_id_str"))
        or bool(tweet.get("in_reply_to_user_id_str"))
        or tweet["full_text"].startswith("@")
    )


def _reason(tweet: Mapping[str, Any], message: Message) -> str:
    """Why an original is better left out."""
    if any(key.startswith("withheld") for key in tweet):
        return "withheld"
    if tweet.get("possibly_sensitive"):
        return "sensitive"
    if _OLD_QUOTE.search(message.text) or _OLD_RETWEET.search(message.text):
        return "text of someone else"
    if _STATUS.search(message.text):
        return "quotes a message"
    words = _LINK_OR_MENTION.sub("", message.text)
    if not message.images and not re.search(r"\w{2}", words):
        return "nothing but a link"
    return ""


def _message(
    path: Path, sizes: Mapping[str, int], account: str, tweet: Mapping[str, Any]
) -> Message:
    key = tweet["id_str"]
    return Message(
        key=key,
        url=f"https://twitter.com/{account}/status/{key}",
        published=parsedate_to_datetime(tweet["created_at"]),
        text=_text(tweet),
        images=tuple(_images(path, sizes, tweet)),
        popularity=int(tweet["favorite_count"]) + int(tweet["retweet_count"]),
    )


def _text(tweet: Mapping[str, Any]) -> str:
    """The text, with its links in full and without those of its images."""
    text = tweet["full_text"]
    for media in _media(tweet):
        text = text.replace(media["url"], "")
    for url in tweet["entities"].get("urls", []):
        text = text.replace(url["url"], url.get("expanded_url") or url["url"])
    return html.unescape(text).strip()


def _media(tweet: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return (tweet.get("extended_entities") or tweet["entities"]).get("media", [])


def _images(
    path: Path, sizes: Mapping[str, int], tweet: Mapping[str, Any]
) -> Iterable[Attachment]:
    for media in _media(tweet):
        name = media["media_url"].rpartition("/")[2]
        member = f"data/tweets_media/{tweet['id_str']}-{name}"
        # The image of a video is not the video.
        present = media["type"] == "photo" and member in sizes
        yield Attachment(
            name,
            media.get("ext_alt_text") or "",
            sizes.get(member, 0),
            path,
            member if present else "",
        )
