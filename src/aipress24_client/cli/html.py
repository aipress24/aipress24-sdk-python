# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Turn the HTML of a document into what a release can hold."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Comment, Tag

_SILENTLY_DROPPED = ("script", "style", "noscript", "template")
_DROPPED = (
    *("iframe", "object", "embed", "video", "audio", "svg", "form"),
    *("nav", "footer"),
)
_IMAGE_WRAPPERS = ("a", "picture", "p", "div")


@dataclass(frozen=True)
class FoundImage:
    """An image met in a text."""

    src: str
    caption: str


@dataclass(frozen=True)
class Body:
    """A text without its images."""

    html: str
    images: tuple[FoundImage, ...]
    warnings: tuple[str, ...]


def parse(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def take_title(root: Tag) -> str:
    """Remove the first heading of the text, and return it."""
    heading = root.find("h1")
    if not isinstance(heading, Tag):
        return ""
    heading.extract()
    return plain(heading)


def plain(tag: Tag) -> str:
    return " ".join(tag.get_text(" ").split())


def clean(root: Tag, base_url: str) -> Body:
    """Take the images out, resolve the links, drop what cannot be shown."""
    for comment in root.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for tag in root.find_all(_SILENTLY_DROPPED):
        tag.extract()
    warnings = []
    dropped = sorted({_drop(tag) for tag in root.find_all(_DROPPED)})
    if dropped:
        warnings.append(f"left out of the text: {', '.join(dropped)}")
    images = tuple(_take_image(tag) for tag in root.find_all("img"))
    if not _resolve_links(root, base_url):
        warnings.append("relative links: they need the reference to be a URL")
    return Body(root.decode_contents().strip(), images, tuple(warnings))


def _drop(tag: Tag) -> str:
    tag.extract()
    return tag.name


def _take_image(tag: Tag) -> FoundImage:
    caption = str(tag.get("alt") or "")
    figure = tag.find_parent("figure")
    if figure and (legend := figure.find("figcaption")):
        caption = plain(legend)
        legend.extract()
    parent = tag.parent
    tag.extract()
    while (
        parent
        and parent.name in (*_IMAGE_WRAPPERS, "figure")
        and not parent.find(True)
        and not parent.get_text(strip=True)
    ):
        empty, parent = parent, parent.parent
        empty.extract()
    return FoundImage(str(tag.get("src") or ""), " ".join(caption.split()))


def _resolve_links(root: Tag, base_url: str) -> bool:
    """Make the links absolute; tell whether it was possible."""
    resolved = True
    for tag in root.find_all("a", href=True):
        href = str(tag["href"])
        try:
            if href.startswith("#") or urlsplit(href).scheme:
                continue
            if is_url(base_url):
                tag["href"] = urljoin(base_url, href)
            else:
                resolved = False
        except ValueError:  # such as an unclosed "[": left as it is
            continue
    return resolved


def is_url(text: str) -> bool:
    return text.startswith(("https://", "http://"))
