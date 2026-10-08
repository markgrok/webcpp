#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Writes webcpp's test matrix from the files b2 wrote for the CI lanes, and gives their verdict.

Usage: report.py --lane NAME=FILE [--lane NAME=FILE ...] --out DIR

Each FILE is what one lane's b2 run wrote with -a --dump-tests --out-xml=FILE (the lane command
the Jamroot documents), and NAME is the lane's column: letters, digits, '.', '_' and '-'. With
--out-xml, b2 exits 0 even when a test fails: the verdict is this script's exit status. It writes
into DIR, which it makes if need be:

  index.html          the libraries by lanes;
  <library>.html      a library's tests and examples by lanes;
  output/<lane>/...   what b2 captured of each failure, which the failure's cell links to.

A cell is green when every build of it in the lane passed, red with the kind of its most
significant failure, and grey (n/a) when the lane did not build it, as when it does not declare
the lane's target. A library's cell sums its tests and examples up the same way. lanes.py reads
and judges the lanes; pages.py writes the pages.

Exit 0 when every lane built something (a test or an example) of every library it lists, and
everything it built passed; 1 when a test or an example failed, an action outside every test and
example failed, a lane built nothing, or a lane that built something built none of the tests and
examples of a library it lists (the CI puts in a lane only the libraries that declare its
target), each named on the standard error; 2, each named and with nothing written, when an
input cannot be read, when a lane is built with more than one toolset, when a lane named after
a target (native, emscripten, wasip2, wasip3) is built for another, when a lane named after no
target is not named after the directory b2 built its toolset in (clang-darwin-21, gcc-15), or
when a library's own lane on a target, named <target>.<library>.<rest> (wasip2.wasi.test.http), is
built for another target or lists the tests of another library; 2 also when the pages cannot be
written.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import lanes
import pages

LANE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')


def lane_argument(text: str) -> tuple[str, Path]:
    name, separator, file = text.partition('=')
    if not separator or not file:
        raise argparse.ArgumentTypeError(f'{text!r} is not NAME=FILE')
    if not LANE_NAME.fullmatch(name):
        raise argparse.ArgumentTypeError(
            f'the lane name {name!r} is not letters, digits, ".", "_" and "-", from a letter or '
            'a digit')
    return name, Path(file)


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog='report.py', description=(__doc__ or '').split('\n', 1)[0])
    parser.add_argument('--lane', action='append', required=True, type=lane_argument,
                        metavar='NAME=FILE', help="a lane's name and the file b2 wrote for it")
    parser.add_argument('--out', required=True, type=Path, metavar='DIR',
                        help='the directory the pages are written into')
    options = parser.parse_args(arguments)
    given: list[tuple[str, Path]] = options.lane
    # A lane names a directory of output/, and a file system may ignore case.
    seen: dict[str, str] = {}
    for name, _ in given:
        if name.lower() in seen:
            parser.error(f'argument --lane: the lanes {seen[name.lower()]} and {name} are one '
                         'name')
        seen[name.lower()] = name
    read = []
    refused = []
    for name, path in given:
        try:
            read.append(lanes.read_lane(name, path))
        except lanes.InputError as error:
            refused.append(f'report: {name}: {error}')
    if refused:
        print('\n'.join(refused), file=sys.stderr)
        return 2
    try:
        pages.write(read, options.out)
    except OSError as error:
        print(f'report: cannot write {options.out}: {error}', file=sys.stderr)
        return 2
    index = options.out / 'index.html'
    found = [text for lane in read for text in lanes.problems(lane)]
    if found:
        print('\n'.join(f'report: {text}' for text in found), file=sys.stderr)
        print(f'report: {pages.plural(len(found), "failure")}; wrote {index}')
    else:
        print(f'report: every test and example built in {pages.plural(len(read), "lane")} '
              f'passed; wrote {index}')
    return lanes.exit_status(read)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
