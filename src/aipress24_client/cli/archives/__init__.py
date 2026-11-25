# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The archives that social networks give of an account."""

from __future__ import annotations

import zipfile
from functools import lru_cache
from pathlib import Path

from ..errors import CliError
from . import bluesky, mastodon
from .message import Archive, Message

SUFFIXES = (".zip", ".car")

__all__ = ["SUFFIXES", "Archive", "Message", "is_archive", "read_archive"]


def is_archive(path: Path) -> bool:
    return path.suffix.lower() in SUFFIXES


def read_archive(path: Path) -> Archive:
    return _read(path, path.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _read(path: Path, _modified: int) -> Archive:
    try:
        if path.suffix.lower() == ".car":
            return bluesky.read(path)
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
        if names >= mastodon.NAMES:
            return mastodon.read(path)
    except (
        *(AttributeError, IndexError, KeyError, TypeError, ValueError),
        *(RecursionError, zipfile.BadZipFile),
    ) as error:
        raise CliError(f"{path} is damaged: {error!r}") from error
    raise CliError(f"{path} is not a Mastodon or Bluesky archive.")
