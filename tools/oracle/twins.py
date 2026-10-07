#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Runs the twins of a library's examples on the original and compares what each prints.

Usage: twins.py --suffix SUFFIX [--timeout SECONDS] [--update] [--list]
                --examples DIR --twins DIR -- WORD ...

A program is every file <examples>/<path>.cpp, at any depth, named by <path>
(xstate/actions_order, or a name alone at the top). It has a twin,
<twins>/<path><suffix>, which does on the original what the program does on
the port, or a line `<path>: <reason>` in <twins>/without-twin.txt, which says
why the original has none. A twin runs as the words after `--` followed by
its path (node --conditions=development, for a JavaScript original), in a
process group of its own that is killed when it outlives --timeout, colour
off whatever the shell asks for. What it prints on the standard output, every
carriage return removed, must equal the program's <examples>/<path>.expected,
unless the twin has an output of its own, <twins>/<path>.expected: the output
of a difference the port makes on purpose, which must then differ from the
program's. --update rewrites each such output from what the original prints
and writes nothing else.

--list runs nothing, so the words may be left out: it prints one line per
program, sorted by path, `agreeing <path>` (a twin without own output),
`divergent <path>` (a twin with one) or `without-twin <path>`, and a last
line `total <programs> <agreeing> <divergent> <without-twin>`. A tree with a
fault that needs no run is not listed; its faults are named instead.

Exit 0 when every twin agrees (or, with --list, when the tree is listed), 1
listing every fault, 2 on a usage error, a missing directory, a first word
that is not on PATH, or no program found.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import difflib
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

EXEMPTIONS = 'without-twin.txt'
PROGRAM = '.cpp'
OUTPUT = '.expected'


@dataclass(frozen=True)
class Arguments:
    """What the command line asks for; words is the command a twin runs with, empty with --list
    when none is given."""
    suffix: str
    timeout: float
    update: bool
    listing: bool
    examples: Path
    twins: Path
    words: tuple[str, ...]


@dataclass(frozen=True)
class Tree:
    """The programs, the twins, the twins' own outputs and the exemptions, each by path."""
    programs: frozenset[str]
    twins: frozenset[str]
    outputs: frozenset[str]
    exempt: Mapping[str, str]


def environment() -> dict[str, str]:
    """The environment a twin runs in: FORCE_COLOR would override NO_COLOR, so it goes."""
    chosen = dict(os.environ)
    chosen.pop('FORCE_COLOR', None)
    chosen['NO_COLOR'] = '1'
    return chosen


def files(directory: Path, suffix: str, leave_out: Path | None = None) -> frozenset[str]:
    """Every `<path>` that has a file `<directory>/<path><suffix>`, at any depth, written with /
    whatever the system."""
    found: set[str] = set()
    for path in directory.rglob(f'*{suffix}'):
        if path.is_file() and path != leave_out:
            found.add(path.relative_to(directory).as_posix()[:-len(suffix)])
    return frozenset(found)


def exemptions(path: Path) -> tuple[dict[str, str], list[str]]:
    """The lines of without-twin.txt, as {path: reason}, and the faults of its malformed lines."""
    found: dict[str, str] = {}
    faults: list[str] = []
    if not path.is_file():
        return found, faults
    for number, line in enumerate(path.read_text(encoding='utf-8').split('\n'), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        name, separator, reason = stripped.partition(':')
        name = name.strip()
        if not separator or not name or not reason.strip():
            faults.append(f'{path.name}:{number}: not `<path>: <reason>`: {line}')
            continue
        if name in found:
            faults.append(f'{path.name}:{number}: {name} is named twice')
            continue
        found[name] = reason.strip()
    return found, faults


def survey(arguments: Arguments) -> tuple[Tree, list[str]]:
    """The tree, and every fault that needs no twin to run: the bookkeeping of the programs, the
    twins, the outputs and the exemptions, and each program's .expected."""
    exemption_file = arguments.twins / EXEMPTIONS
    exempt, faults = exemptions(exemption_file)
    tree = Tree(programs=files(arguments.examples, PROGRAM),
                twins=files(arguments.twins, arguments.suffix, leave_out=exemption_file),
                outputs=files(arguments.twins, OUTPUT), exempt=exempt)
    named = set(tree.exempt)
    for name in sorted(tree.programs - tree.twins - named):
        faults.append(f'{name}: no twin, and no line in {EXEMPTIONS}')
    for name in sorted(tree.twins & named):
        faults.append(f'{name}: a twin, and a line in {EXEMPTIONS}')
    for name in sorted(tree.twins - tree.programs):
        faults.append(f'{name}: a twin of no example')
    for name in sorted(named - tree.programs):
        faults.append(f'{name}: {EXEMPTIONS} names no example')
    for name in sorted(tree.outputs - tree.twins):
        faults.append(f'{name}: an output of no twin')
    for name in sorted(tree.programs):
        expected = arguments.examples / f'{name}{OUTPUT}'
        if not expected.is_file():
            faults.append(f"{name}: the program's output {expected} does not exist")
    return tree, faults


def read(path: Path) -> bytes:
    """A file's bytes, every carriage return removed."""
    return path.read_bytes().replace(b'\r', b'')


def own_output_faults(arguments: Arguments, names: Sequence[str]) -> list[str]:
    """The twins among names whose own output is the program's: no difference to keep."""
    faults: list[str] = []
    for name in names:
        own = arguments.twins / f'{name}{OUTPUT}'
        if read(own) == read(arguments.examples / f'{name}{OUTPUT}'):
            faults.append(f"{name}: its own output is the program's; delete {own}")
    return faults


def run(words: Sequence[str], twin: Path, timeout: float) -> tuple[int | None, bytes, bytes]:
    """(exit status or None on a timeout, standard output without CR, standard error).

    Tip: start_new_session makes the twin its own process group, so a twin
    that spawns a child of its own is not orphaned when it is killed.
    """
    process = subprocess.Popen([*words, str(twin)], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=environment(),
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if hasattr(os, 'killpg'):
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        process.communicate()
        return None, b'', b''
    return process.returncode, stdout.replace(b'\r', b''), stderr


def difference(expected: bytes, printed: bytes, label: str) -> str:
    """A unified diff of what was expected and what the twin printed."""
    return ''.join(difflib.unified_diff(
        expected.decode(errors='replace').splitlines(True),
        printed.decode(errors='replace').splitlines(True), label, 'the twin printed'))


def compared(arguments: Arguments, tree: Tree, name: str,
             result: tuple[int | None, bytes, bytes]) -> list[str]:
    """The faults of one twin, from what it did when it ran."""
    status, printed, errors = result
    if status is None:
        return [f'{name}: did not end within {arguments.timeout} s']
    if status != 0:
        tail = errors.decode(errors='replace').strip().split('\n')[-5:]
        return [f'{name}: exited with status {status}\n' + '\n'.join(tail)]
    program = read(arguments.examples / f'{name}{OUTPUT}')
    if name in tree.outputs:
        own = arguments.twins / f'{name}{OUTPUT}'
        if arguments.update:
            if printed == program:
                return [f"{name}: --update refuses to make its own output the program's; "
                        f'{own} is unchanged']
            own.write_bytes(printed)
        expected = read(own)
        if expected == program:
            return [f"{name}: its own output is the program's; delete {own}"]
        label = str(own)
    else:
        expected = program
        label = str(arguments.examples / f'{name}{OUTPUT}')
    if printed != expected:
        return [f'{name}: differs\n' + difference(expected, printed, label)]
    return []


def check(arguments: Arguments) -> list[str]:
    """Every fault, as a list of messages: the survey's, then each twin's, in the order of their
    paths. A program whose .expected is missing is named by the survey and its twin not run."""
    tree, faults = survey(arguments)
    ordered = sorted(name for name in tree.twins & tree.programs
                     if (arguments.examples / f'{name}{OUTPUT}').is_file())
    workers = min(32, (os.cpu_count() or 1) + 4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda name: run(arguments.words,
                                            arguments.twins / f'{name}{arguments.suffix}',
                                            arguments.timeout), ordered)
        for name, result in zip(ordered, results):
            faults += compared(arguments, tree, name, result)
    return faults


def listing(arguments: Arguments) -> tuple[list[str], list[str]]:
    """The lines --list prints, and the faults that stop it from printing them."""
    tree, faults = survey(arguments)
    divergent = sorted(tree.twins & tree.outputs)
    faults += own_output_faults(arguments, [
        name for name in divergent if (arguments.examples / f'{name}{OUTPUT}').is_file()])
    if faults:
        return [], faults
    kinds = {name: 'without-twin' for name in tree.exempt}
    kinds.update({name: 'agreeing' for name in tree.twins - tree.outputs})
    kinds.update({name: 'divergent' for name in divergent})
    lines = [f'{kinds[name]} {name}' for name in sorted(tree.programs)]
    counts = [sum(1 for kind in kinds.values() if kind == wanted)
              for wanted in ('agreeing', 'divergent', 'without-twin')]
    lines.append(f'total {len(tree.programs)} ' + ' '.join(str(count) for count in counts))
    return lines, []


def parse(argv: Sequence[str]) -> Arguments:
    """The command line; argparse exits 2 on a usage error. The words after the first `--` are
    the twin's command and never options of this script's: argparse would read a word such as
    --conditions=development as one of its own."""
    parser = argparse.ArgumentParser(
        prog='twins.py', description="Runs the twins of a library's examples on the original.",
        usage='%(prog)s --suffix SUFFIX [--timeout SECONDS] [--update] [--list] '
              '--examples DIR --twins DIR -- WORD ...')
    parser.add_argument('--suffix', required=True,
                        help="what ends a twin's file name after its path, such as .mjs")
    parser.add_argument('--timeout', type=float, default=60.0, metavar='SECONDS')
    parser.add_argument('--update', action='store_true')
    parser.add_argument('--list', action='store_true', dest='listing')
    parser.add_argument('--examples', type=Path, required=True, metavar='DIR')
    parser.add_argument('--twins', type=Path, required=True, metavar='DIR')
    split = argv.index('--') if '--' in argv else len(argv)
    options = parser.parse_args(argv[:split])
    words = tuple(argv[split + 1:])
    if options.suffix in ('', OUTPUT, PROGRAM):
        parser.error(f'--suffix {options.suffix!r} cannot name a twin; give one such as .mjs')
    if options.listing and options.update:
        parser.error('--update writes what twins print, and --list runs none')
    if not options.listing and not words:
        parser.error('no command after --: the command a twin runs with, such as -- node')
    return Arguments(suffix=options.suffix, timeout=options.timeout, update=options.update,
                     listing=options.listing, examples=options.examples, twins=options.twins,
                     words=words)


def main(argv: Sequence[str]) -> int:
    arguments = parse(argv)
    if not arguments.listing and shutil.which(arguments.words[0]) is None:
        print(f'twins: {arguments.words[0]} is not on PATH', file=sys.stderr)
        return 2
    for directory in (arguments.examples, arguments.twins):
        if not directory.is_dir():
            print(f'twins: {directory} does not exist', file=sys.stderr)
            return 2
    if not files(arguments.examples, PROGRAM):
        print(f'twins: {arguments.examples} has no example', file=sys.stderr)
        return 2
    if arguments.listing:
        lines, faults = listing(arguments)
        for line in lines:
            print(line)
    else:
        faults = check(arguments)
    for fault in faults:
        print(f'twins: {fault}', file=sys.stderr)
    return 1 if faults else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
