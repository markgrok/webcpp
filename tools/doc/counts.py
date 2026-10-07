#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Counts what a library's page says the library holds, for webcpp.doc to give the page.

A page states how many examples, tests, headers and twins its library has as Asciidoctor
attributes, `{n-examples}`, which webcpp.doc computes with this script at every build, so that
none is typed and none drifts from the tree. It prints each on a line of its own, `name=value`:

* From the programs b2 recorded, each given as `--program "<kind> <name> <target>..."`, as
  tools/webcpp.jam records the programs of the library's test and example Jamfiles (a Jamfile is
  never read here): `n-examples` and `n-examples-<target>`, the programs of kind example;
  `n-tests` and `n-tests-<target>`, every other one, a webcpp.run's -noexcept variant being no
  program of its own and each header that webcpp.headers-alone compiles alone one;
  `n-boost-test-suites`; and `n-headers`, the headers webcpp.headers-alone compiles alone, one
  program each. A target is native, emscripten, wasip2 or wasip3, and every one is counted, so a
  count of programs may be 0: a library declares the targets it builds for. `n-headers` is never
  0: every library compiles its public headers alone, and one that declares no
  webcpp.headers-alone fails the count, naming it.
* With `--examples`, `--twins` and `--suffix`, which the library's oracle declares with
  webcpp.twins, from what tools/oracle/twins.py --list prints, which runs no twin:
  `n-twins-agreeing`, `n-twins-divergent`, `n-examples-without-twin` and
  `n-examples-with-original`, the agreeing and the divergent. A library that declares no twins
  has none of these.
* From the library's own `doc/counts.py`, when there is one, run with the library's directory as
  its one argument: each line `<name>=<number>` it prints, a count of what only that library
  holds, such as the cases of its fixtures. What it writes on its standard error is written on
  this script's, and is no count.

A count that finds nothing fails, naming what it looked for, rather than put a zero on the page:
the headers, the twins (a library that declares twins and has none), and each count of a
library's own counts.py, which must also print at least one and exit 0. A name of the library's
own that is also one of the counts above fails, naming both. A fault is written on the standard
error, and the standard output holds only counts.

Usage: counts.py --library DIR [--program RECORD]... [--examples DIR --twins DIR --suffix SUFFIX]

Exit 0 printing the counts; 1 naming each fault; 2 on a usage error.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
TWINS = HERE.parent / 'oracle/twins.py'
SELF = 'tools/doc/counts.py'

KINDS = ('example', 'run', 'run-fail', 'compile', 'compile-fail', 'boost-test', 'headers-alone')
TARGETS = ('native', 'emscripten', 'wasip2', 'wasip3')

# What each generic count is counted from, by its name, as a fault names it.
PROGRAM_COUNTS = {
    'n-examples': 'the programs b2 recorded',
    **{f'n-examples-{target}': 'the programs b2 recorded' for target in TARGETS},
    'n-tests': 'the programs b2 recorded',
    **{f'n-tests-{target}': 'the programs b2 recorded' for target in TARGETS},
    'n-boost-test-suites': 'the programs b2 recorded',
    'n-headers': 'the programs b2 recorded',
}
TWIN_COUNTS = {name: 'tools/oracle/twins.py --list'
               for name in ('n-twins-agreeing', 'n-twins-divergent', 'n-examples-without-twin',
                            'n-examples-with-original')}
GENERIC = {**PROGRAM_COUNTS, **TWIN_COUNTS}

# A line of a library's own counts.py.
OWN_COUNT = re.compile(r'^([a-z][a-z0-9]*(?:-[a-z0-9]+)*)=([0-9]+)$')
# A line of twins.py --list.
LISTED = re.compile(r'^(agreeing|divergent|without-twin) (\S+)$')
TOTAL = re.compile(r'^total ([0-9]+) ([0-9]+) ([0-9]+) ([0-9]+)$')


class Fault(Exception):
    """A count that cannot be made, said to the user."""


class Program:
    """A program b2 recorded: its kind, its name and its targets."""

    def __init__(self, record: str) -> None:
        words = record.split()
        if len(words) < 3:
            raise ValueError(f'{record!r} is not "<kind> <name> <target>..."')
        self.kind, self.name, self.targets = words[0], words[1], words[2:]
        if self.kind not in KINDS:
            raise ValueError(f'{record!r}: {self.kind} is not a kind of program; the kinds are '
                             f'{", ".join(KINDS)}')
        for target in self.targets:
            if target not in TARGETS:
                raise ValueError(f'{record!r}: {target} is not a target; the targets are '
                                 f'{", ".join(TARGETS)}')


def program_counts(library: str, programs: Sequence[Program]) -> dict[str, int]:
    """The counts of the programs b2 recorded, a zero included, but for the headers: every
    library compiles its public headers alone, so one that records none fails."""
    examples = [program for program in programs if program.kind == 'example']
    tests = [program for program in programs if program.kind != 'example']
    counts = {'n-examples': len(examples)}
    for target in TARGETS:
        counts[f'n-examples-{target}'] = sum(target in program.targets for program in examples)
    counts['n-tests'] = len(tests)
    for target in TARGETS:
        counts[f'n-tests-{target}'] = sum(target in program.targets for program in tests)
    counts['n-boost-test-suites'] = sum(program.kind == 'boost-test' for program in tests)
    counts['n-headers'] = sum(program.kind == 'headers-alone' for program in tests)
    if counts['n-headers'] == 0:
        raise Fault(f'{SELF}: {library} declares no webcpp.headers-alone: its headers are not '
                    'counted, and every library compiles its public headers alone')
    return counts


def twin_counts(examples: Path, twins: Path, suffix: str) -> dict[str, int]:
    """The counts of the twins, from what twins.py --list prints, which runs no twin."""
    listed = subprocess.run([sys.executable, str(TWINS), '--list', '--suffix', suffix,
                             '--examples', str(examples), '--twins', str(twins)],
                            capture_output=True, text=True, check=False)
    if listed.returncode != 0:
        raise Fault(f'{SELF}: tools/oracle/twins.py --list exited with {listed.returncode}:\n'
                    f'{listed.stdout}{listed.stderr}'.rstrip())
    kinds = {'agreeing': 0, 'divergent': 0, 'without-twin': 0}
    total = None
    for line in listed.stdout.splitlines():
        program = LISTED.match(line)
        if program is not None:
            kinds[program.group(1)] += 1
            continue
        found = TOTAL.match(line)
        if found is None or total is not None:
            raise Fault(f'{SELF}: tools/oracle/twins.py --list printed a line it does not print: '
                        f'{line}')
        total = tuple(int(number) for number in found.groups())
    counted = (sum(kinds.values()), kinds['agreeing'], kinds['divergent'], kinds['without-twin'])
    if total != counted:
        raise Fault(f'{SELF}: tools/oracle/twins.py --list totals {total}, and lists {counted}')
    if kinds['agreeing'] + kinds['divergent'] == 0:
        raise Fault(f'{SELF}: no twin of an example of {examples} in {twins}, whose library '
                    'declares twins')
    return {
        'n-twins-agreeing': kinds['agreeing'],
        'n-twins-divergent': kinds['divergent'],
        'n-examples-without-twin': kinds['without-twin'],
        'n-examples-with-original': kinds['agreeing'] + kinds['divergent'],
    }


def own_counts(library: Path) -> dict[str, int]:
    """The counts of the library's own doc/counts.py, when there is one."""
    script = library / 'doc/counts.py'
    if not script.is_file():
        return {}
    run = subprocess.run([sys.executable, str(script), str(library)], capture_output=True,
                         text=True, check=False)
    if run.returncode != 0:
        raise Fault(f'{script}: exited with {run.returncode}:\n{run.stdout}{run.stderr}'.rstrip())
    sys.stderr.write(run.stderr)
    counts: dict[str, int] = {}
    for line in run.stdout.splitlines():
        found = OWN_COUNT.match(line)
        if found is None:
            raise Fault(f'{script}: not a count name=<number>: {line}')
        name, value = found.group(1), int(found.group(2))
        if name in GENERIC:
            raise Fault(f'{script}: {name} is a count of {SELF}\'s own, from {GENERIC[name]}; '
                        'name the library\'s count otherwise')
        if name in counts:
            raise Fault(f'{script}: {name} is printed twice')
        if value == 0:
            raise Fault(f'{script}: {name}=0: a count that finds nothing fails, rather than put a '
                        'zero on the page')
        counts[name] = value
    if not counts:
        raise Fault(f'{script}: prints no count')
    return counts


def parse(argv: Sequence[str]) -> tuple[Path, list[Program], tuple[Path, Path, str] | None]:
    """The library, its programs and its twins, if any, that the command line names."""
    parser = argparse.ArgumentParser(
        description='Counts what a library\'s page says the library holds.')
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--program', action='append', default=[])
    parser.add_argument('--examples', type=Path)
    parser.add_argument('--twins', type=Path)
    parser.add_argument('--suffix')
    arguments = parser.parse_args(argv)
    library: Path = arguments.library
    if not library.is_dir():
        parser.error(f'not a directory: {library}')
    try:
        programs = [Program(record) for record in arguments.program]
    except ValueError as error:
        parser.error(str(error))
    given = (arguments.examples, arguments.twins, arguments.suffix)
    if all(value is None for value in given):
        return library, programs, None
    if any(value is None for value in given):
        parser.error('--examples, --twins and --suffix go together: the twins webcpp.twins '
                     'declares')
    return library, programs, (arguments.examples, arguments.twins, arguments.suffix)


def main(argv: Sequence[str]) -> int:
    library, programs, twins = parse(argv)
    counts: dict[str, int] = {}
    try:
        counts.update(program_counts(library.name, programs))
        if twins is not None:
            counts.update(twin_counts(*twins))
        counts.update(own_counts(library))
    except Fault as fault:
        print(fault, file=sys.stderr)
        return 1
    for name, value in counts.items():
        print(f'{name}={value}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
