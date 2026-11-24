# Copyright (c) 2025, Abilian SAS & TCA
#
# SPDX-License-Identifier: Apache-2.0
"""The generated module must match the committed spec: run ``make generate``."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import generate
from aipress24_client import _generated

SPEC = Path(generate.__file__).parent / "openapi.json"


def test_generated_module_matches_the_committed_spec() -> None:
    expected = generate.generate(json.loads(SPEC.read_text(encoding="utf-8")))
    committed = Path(_generated.__file__).read_text(encoding="utf-8")

    # Compared as syntax trees: the committed file is also formatted.
    assert ast.dump(ast.parse(committed)) == ast.dump(ast.parse(expected))
