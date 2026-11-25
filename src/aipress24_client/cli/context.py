# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""What every command shares: the site, and how to talk to the user."""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from typing import Annotated, Any

from cyclopts import Parameter

from .. import Client
from .access import find_token
from .errors import CliError, UsageError
from .site import RetryingClient, Site

_TITLE_WIDTH = 50


@dataclass
class Context:
    """The options common to all commands, and the results so far."""

    site_url: str
    as_json: bool = False
    failed: bool = False
    results: Counter[str] = field(default_factory=Counter)

    @cached_property
    def site(self) -> Site:
        return Site(self.make_client(self.require_token()))

    @property
    def has_token(self) -> bool:
        return bool(find_token(self.site_url))

    def require_token(self) -> str:
        token = find_token(self.site_url)
        if not token:
            raise CliError(
                "No token: run 'aipress24 auth login', or set AIPRESS24_TOKEN."
            )
        return token

    def make_client(self, token: str) -> Client:
        return RetryingClient(token, self.site_url)

    # --- output -----------------------------------------------------------

    def line(self, text: str, data: Mapping[str, Any]) -> None:
        """Print a result: ``text`` for people, ``data`` for programs."""
        if self.as_json:
            print(json.dumps(data, ensure_ascii=False), flush=True)
        else:
            print(_printable(text), flush=True)

    def result(
        self,
        result: str,
        title: str,
        detail: str = "",
        *,
        ok: bool = True,
        problems: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
        **data: Any,
    ) -> None:
        """Print the result for one document or item."""
        self.results[result] += 1
        self.failed = self.failed or not ok
        short = title if len(title) <= _TITLE_WIDTH else f"{title[: _TITLE_WIDTH - 1]}…"
        lines = [f"{result:<10} {short:<{_TITLE_WIDTH}} {detail}".rstrip()]
        lines += [f"{'':<10} - {problem}" for problem in problems]
        lines += [f"{'':<10} ! {warning}" for warning in warnings]
        record = {
            "result": result,
            "title": title,
            **data,
            "problems": list(problems),
            "warnings": list(warnings),
        }
        self.line("\n".join(lines), record)

    def summary(self, noun: str, *hints: str) -> None:
        total = self.results.total()
        counts = ", ".join(f"{count} {name}" for name, count in self.results.items())
        self.say(f"{total} {noun}: {counts}" if total else f"0 {noun}")
        for hint in hints:
            self.say(hint)

    def say(self, text: str) -> None:
        print(text, file=sys.stderr, flush=True)

    def confirm(self, text: str, *, yes: bool) -> None:
        self.say(text)
        if yes:
            return
        if not sys.stdin.isatty():
            raise UsageError("Nothing was done: confirm with --yes.")
        print("Continue? [y/N] ", end="", file=sys.stderr, flush=True)
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            raise CliError("Nothing was done.")


def _printable(text: str) -> str:
    """Titles come from others: keep them from driving the terminal."""
    return "".join(c if c.isprintable() or c == "\n" else " " for c in text)


# Given by `launch`, which parses the options common to all commands.
Ctx = Annotated[Context, Parameter(parse=False)]
