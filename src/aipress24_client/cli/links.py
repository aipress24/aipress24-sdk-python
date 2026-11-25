# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""Find what shortened links lead to, and remember it next to the catalog.

Only the shorteners are asked, never the sites they lead to: the answer is in the
redirection, which is not followed.
"""

from __future__ import annotations

import csv
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from email.message import Message
from http.client import HTTPException
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from .html import is_url

SHORTENERS = frozenset(
    [
        "bit.ly",
        "buff.ly",
        "cinc.me",
        "cli.gs",
        "cnb.cx",
        "dlvr.it",
        "econ.st",
        "fb.me",
        "ff.im",
        "goo.gl",
        "gu.com",
        "im.ly",
        "is.gd",
        "j.mp",
        "kck.st",
        "linkd.in",
        "lnkd.in",
        "nyr.kr",
        "nyti.ms",
        "ow.ly",
        "ping.fm",
        "pic.im",
        "prsm.tc",
        "r2.ly",
        "reut.rs",
        "rww.to",
        "seen.co",
        "shar.es",
        "smf.is",
        "t.co",
        "tcrn.ch",
        "tinyurl.com",
        "tnw.co",
        "tr.im",
        "trib.al",
        "u.nu",
        "w.lpnt.fr",
        "w33.us",
        "wapo.st",
        "wh.gov",
        "wmk.me",
        "zd.net",
        "dai.ly",
        "disq.us",
    ]
)
COLUMNS = ("link", "target", "note")
MAX_STEPS = 5
TIMEOUT = 10
DELAY = 0.2
FAILED = "failed"
_URL = re.compile(r"https?://[^\s<>\"]+")
_TRAILING = ".,;:!?)'»”\N{RIGHT SINGLE QUOTATION MARK}…"


@dataclass(frozen=True)
class Link:
    """A shortened link; ``target`` is empty when it leads nowhere."""

    link: str
    target: str
    note: str = ""

    @property
    def is_settled(self) -> bool:
        return not self.note.startswith(FAILED)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def ask(url: str) -> tuple[int, str]:
    """The status of the answer, and where it redirects to."""
    request = urllib.request.Request(
        url, method="GET", headers={"User-Agent": "aipress24-client"}
    )
    try:
        with _opener.open(request, timeout=TIMEOUT) as response:
            return response.status, _location(response.headers)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, _location(error.headers)


def _location(headers: Message) -> str:
    return headers.get("Location", "")


def find_links(texts: Iterable[str]) -> list[str]:
    """The shortened links of texts, each once."""
    found = (match.rstrip(_TRAILING) for text in texts for match in _URL.findall(text))
    return list(dict.fromkeys(link for link in found if is_short(link)))


def is_short(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:  # such as an unclosed "[" in the host
        return False
    return (
        parts.scheme in ("http", "https")
        and parts.netloc.lower() in SHORTENERS
        and len(parts.path) > 1
    )


def resolve(link: str) -> Link:
    """Ask the shortener, and those it leads to, if any."""
    url = link
    for _ in range(MAX_STEPS):
        try:
            status, location = ask(url)
        except (OSError, HTTPException, ValueError) as error:
            return Link(link, "", f"{FAILED}: {error}")
        if status >= 500 or status == 429:
            return Link(link, "", f"{FAILED}: HTTP {status}")
        if not 300 <= status < 400:
            return Link(link, "", f"dead: HTTP {status}" if status >= 400 else "a page")
        try:
            target = urljoin(url, location)
        except ValueError:
            target = ""
        if not location or not is_url(target):
            return Link(link, "", "no usable redirection")
        if not is_short(target):
            return Link(link, target)
        url = target
    return Link(link, "", "redirects in circles")


def resolve_all(
    links: Iterable[str],
    known: Mapping[str, Link],
    report: Callable[[Link], None],
) -> dict[str, Link]:
    """Resolve what is not settled yet, one at a time."""
    found = dict(known)
    for link in links:
        if link in found and found[link].is_settled:
            continue
        found[link] = resolve(link)
        report(found[link])
        time.sleep(DELAY)
    return found


def expand(text: str, links: Mapping[str, Link]) -> str:
    """Put the targets in a text."""

    def replace(match: re.Match[str]) -> str:
        url = match[0].rstrip(_TRAILING)
        target = links[url].target if url in links else ""
        return (target or url) + match[0][len(url) :]

    return _URL.sub(replace, text)


def links_path(catalog: Path) -> Path:
    return catalog.with_suffix(".links.csv")


def read_links(catalog: Path) -> dict[str, Link]:
    try:
        with links_path(catalog).open(encoding="utf-8-sig", newline="") as file:
            rows = [
                {key: row.get(key) or "" for key in COLUMNS}
                for row in csv.DictReader(file)
            ]
    except FileNotFoundError:
        return {}
    # A person may have corrected it.
    return {
        row["link"]: Link(**row)
        for row in rows
        if not row["target"] or is_url(row["target"])
    }


def write_links(catalog: Path, links: Mapping[str, Link]) -> Path:
    path = links_path(catalog)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, COLUMNS)
        writer.writeheader()
        writer.writerows(vars(links[link]) for link in sorted(links))
    temporary.replace(path)
    return path
