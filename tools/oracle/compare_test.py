#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/oracle/compare.py: two identical trees pass; a differing byte, a file in one tree
only, a file against a directory, an unreadable file and a tree that cannot be listed each fail,
naming the path; a wrong number of arguments is a usage error. Run with the names of some cases
to run only those."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

COMPARE = Path(__file__).resolve().parent / 'compare.py'


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def trees(root: Path) -> tuple[Path, Path]:
    """Two identical trees, nested, with a file whose size and time a difference would share."""
    for side in ('left', 'right'):
        write(root / side / 'top.json', b'{}\n')
        write(root / side / 'a/b/deep.json', b'[1, 2]\n')
        write(root / side / 'a/empty.txt', b'')
        os.utime(root / side / 'a/b/deep.json', (1_000_000_000, 1_000_000_000))
    return root / 'left', root / 'right'


def compare(*arguments: Path | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(COMPARE), *map(str, arguments)],
                          capture_output=True, text=True, check=False, timeout=120)


def expect(result: subprocess.CompletedProcess[str], status: int, *texts: str) -> None:
    assert result.returncode == status, (status, result.returncode, result.stderr)
    for text in texts:
        assert text in result.stderr, (text, result.stderr)


def test_identical_trees_pass(root: Path) -> None:
    left, right = trees(root)
    result = compare(left, right)
    expect(result, 0)
    assert result.stdout == '' and result.stderr == '', (result.stdout, result.stderr)


def test_a_differing_byte_fails(root: Path) -> None:
    # The same size and the same modification time: only the bytes tell them apart.
    left, right = trees(root)
    write(right / 'a/b/deep.json', b'[1, 3]\n')
    os.utime(right / 'a/b/deep.json', (1_000_000_000, 1_000_000_000))
    expect(compare(left, right), 1, f"compare: {left / 'a/b/deep.json'}: contents differ")


def test_a_file_in_one_tree_only_fails(root: Path) -> None:
    left, right = trees(root)
    write(left / 'a/only-left.json', b'{}\n')
    write(right / 'only-right.json', b'{}\n')
    expect(compare(left, right), 1,
           f"compare: {left / 'a/only-left.json'}: only in this tree",
           f"compare: {right / 'only-right.json'}: only in this tree")


def test_a_file_against_a_directory_fails(root: Path) -> None:
    left, right = trees(root)
    (right / 'top.json').unlink()
    (right / 'top.json').mkdir()
    expect(compare(left, right), 1,
           f"compare: {left / 'top.json'}: a file here, a directory in {right}")


def test_an_unreadable_file_fails(root: Path) -> None:
    left, right = trees(root)
    unreadable = left / 'a/b/deep.json'
    unreadable.chmod(0)
    try:
        if os.access(unreadable, os.R_OK):
            # Whoever can read any file (root) cannot see this case.
            print('test_an_unreadable_file_fails: skipped, every file is readable here')
            return
        expect(compare(left, right), 1,
               f'compare: {unreadable}: cannot be read here or in {right}')
    finally:
        unreadable.chmod(0o644)


def test_a_tree_that_cannot_be_listed_fails(root: Path) -> None:
    left, _ = trees(root)
    missing = root / 'no-such-tree'
    expect(compare(left, missing), 1, f'compare: {missing}: cannot be listed')


def test_a_usage_error_exits_2(root: Path) -> None:
    left, _ = trees(root)
    expect(compare(left), 2, 'usage: compare.py LEFT RIGHT')
    expect(compare(), 2, 'usage: compare.py LEFT RIGHT')


CASES: list[Callable[[Path], None]] = [
    test_identical_trees_pass,
    test_a_differing_byte_fails,
    test_a_file_in_one_tree_only_fails,
    test_a_file_against_a_directory_fails,
    test_an_unreadable_file_fails,
    test_a_tree_that_cannot_be_listed_fails,
    test_a_usage_error_exits_2,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'compare_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='webcpp compare ') as scratch:
            case(Path(scratch))
        print(f'{case.__name__}: ok')
    print('compare_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
