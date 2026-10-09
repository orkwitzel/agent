# SPDX-License-Identifier: GPL-3.0-or-later
"""Code standards no linter checks. CONTRIBUTING.md explains each one."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "agent"
TESTS = ROOT / "tests"

BANNED_MODULE_NAMES = {"utils", "helpers", "common", "misc", "base"}


def python_files():
    return sorted([*SRC.rglob("*.py"), *TESTS.rglob("*.py")])


def source_files():
    meson_files = [
        ROOT / "meson.build",
        ROOT / "meson_options.txt",
        *(ROOT / directory / "meson.build" for directory in ("src", "data", "po", "tests")),
    ]
    return [
        *python_files(),
        *SRC.rglob("*.blp"),
        *meson_files,
        ROOT / "src" / "agent.in",
        *(ROOT / "build-aux").glob("*.sh"),
    ]


def functions(path):
    tree = ast.parse(path.read_text())
    return [
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def where(path, node):
    return f"{path.relative_to(ROOT)}:{node.lineno} {node.name}"


def test_every_source_file_has_a_license_line():
    missing = [
        str(path.relative_to(ROOT))
        for path in source_files()
        if "SPDX-License-Identifier: GPL-3.0-or-later"
        not in "".join(path.read_text().splitlines(True)[:3])
    ]
    assert missing == []


def test_parameters_with_defaults_are_keyword_only():
    positional = [
        where(path, function)
        for path in python_files()
        for function in functions(path)
        if function.args.defaults
    ]
    assert positional == []


def test_no_staticmethods():
    static = [
        where(path, function)
        for path in python_files()
        for function in functions(path)
        if any(
            isinstance(decorator, ast.Name) and decorator.id == "staticmethod"
            for decorator in function.decorator_list
        )
    ]
    assert static == []


def test_no_dunder_all():
    declaring = [
        str(path.relative_to(ROOT))
        for path in python_files()
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    ]
    assert declaring == []


def test_no_vague_module_names():
    vague = [
        str(path.relative_to(ROOT)) for path in python_files() if path.stem in BANNED_MODULE_NAMES
    ]
    assert vague == []


def test_tests_mirror_the_modules_they_test():
    # tests/core/test_store.py tests src/agent/core/store.py. Tests directly
    # in tests/ span the whole codebase, and support/ holds shared helpers.
    orphans = [
        str(path.relative_to(ROOT))
        for path in TESTS.rglob("test_*.py")
        if path.parent != TESTS
        and not (
            SRC / path.parent.relative_to(TESTS) / f"{path.stem.removeprefix('test_')}.py"
        ).exists()
    ]
    assert orphans == []
