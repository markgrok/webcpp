#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Exits 1, listing every path that differs, when two directory trees differ.

Usage: compare.py LEFT RIGHT

A file in both trees is compared by its bytes, never by its size and
modification time, which two different outputs can share. A path in one tree
only is named under the tree it is in. An entry that is a file in one tree and
a directory in the other, that is neither, or that cannot be read is a
difference, never skipped; so is a tree that cannot be listed. Each
difference is a line `compare: <path>: <reason>` on the standard error. Exit
0 when the trees are identical, 1 when they differ, 2 on a usage error.
"""

from __future__ import annotations

import os
import sys


def kind(path: str) -> str:
    if os.path.isdir(path):
        return 'directory'
    if os.path.isfile(path):
        return 'file'
    return 'other'


def read(path: str) -> bytes | None:
    try:
        with open(path, 'rb') as file:
            return file.read()
    except OSError:
        return None


def differences(left: str, right: str) -> list[tuple[str, str]]:
    """Every (path, reason) by which the tree right differs from the tree left, in a fixed
    order: the names of a directory sorted, the paths of left only before those of right."""
    try:
        left_names = set(os.listdir(left))
    except OSError:
        return [(left, 'cannot be listed')]
    try:
        right_names = set(os.listdir(right))
    except OSError:
        return [(right, 'cannot be listed')]
    found = [(os.path.join(left, name), 'only in this tree')
             for name in sorted(left_names - right_names)]
    found += [(os.path.join(right, name), 'only in this tree')
              for name in sorted(right_names - left_names)]
    for name in sorted(left_names & right_names):
        left_path = os.path.join(left, name)
        right_path = os.path.join(right, name)
        left_kind = kind(left_path)
        right_kind = kind(right_path)
        if left_kind != right_kind or left_kind == 'other':
            found.append((left_path, f'a {left_kind} here, a {right_kind} in {right}'))
        elif left_kind == 'directory':
            found += differences(left_path, right_path)
        else:
            left_bytes = read(left_path)
            right_bytes = read(right_path)
            if left_bytes is None or right_bytes is None:
                found.append((left_path, 'cannot be read here or in ' + right))
            elif left_bytes != right_bytes:
                found.append((left_path, 'contents differ'))
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print('usage: compare.py LEFT RIGHT', file=sys.stderr)
        return 2
    different = differences(argv[0], argv[1])
    for path, reason in different:
        print(f'compare: {path}: {reason}', file=sys.stderr)
    return 1 if different else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
