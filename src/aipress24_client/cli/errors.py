# Copyright (c) 2026, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The errors the command shows, without a traceback."""

from __future__ import annotations


class CliError(Exception):
    """The command cannot do what it was asked."""

    exit_status = 1


class UsageError(CliError):
    """The command line is wrong, or a confirmation is missing."""

    exit_status = 2
