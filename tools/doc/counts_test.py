#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/doc/counts.py: the fixture demo counts its examples and its tests per target, its
Boost.Test suite and its headers, from the programs b2 recorded; the fixture oracle_demo counts its
agreeing, divergent and without-twin programs from twins.py --list, which runs no twin; a library's
own doc/counts.py adds its counts, and fails the count when it names a generic one, counts
nothing, prints nothing or fails; and so does a count read from the tree that finds nothing. Each
case copies a fixture library into a scratch directory. Run with the names of some cases to run
only those."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
COUNTS = HERE / 'counts.py'
FIXTURES = HERE.parent / 'test/fixtures'

# The programs of demo's test and example Jamfiles, as tools/webcpp.jam records them: "<kind>
# <name> <target>...", one per program, a webcpp.run's -noexcept variant being none.
DEMO_PROGRAMS = (
    'run pass native wasip2 wasip3',
    'run-fail fails native wasip2 wasip3',
    'compile-fail rejects native wasip2 wasip3',
    'run native_only native',
    'compile native_only_compiles native',
    'headers-alone alone-demo native wasip2 wasip3',
    'headers-alone alone-demo-answer native wasip2 wasip3',
    'boost-test suite native',
    'run parses_json native wasip2 wasip3',
    'example hello native wasip2 wasip3',
    'example catches native wasip3',
)

# What demo counts, every count of the programs b2 recorded, a zero included.
DEMO_COUNTS = {
    'n-examples': '2',
    'n-examples-native': '2',
    'n-examples-emscripten': '0',
    'n-examples-wasip2': '1',
    'n-examples-wasip3': '2',
    'n-tests': '9',
    'n-tests-native': '9',
    'n-tests-emscripten': '0',
    'n-tests-wasip2': '6',
    'n-tests-wasip3': '6',
    'n-boost-test-suites': '1',
    'n-headers': '2',
}

ORACLE_PROGRAMS = (
    'run square native',
    'example square native',
    'example half native',
    'example compile_time native',
)

# oracle_demo's twins, as its test/oracle/Jamfile declares them with webcpp.twins.
ORACLE_TWINS = ('--examples', 'example', '--twins', 'test/oracle/twins', '--suffix', '.mjs')


def library(root: Path, fixture: str) -> Path:
    """A copy of the fixture library under root/libs, as the superproject holds it."""
    copy = root / 'libs' / fixture
    shutil.copytree(FIXTURES / fixture, copy,
                    ignore=shutil.ignore_patterns('node_modules', '__pycache__', 'html'))
    return copy


def count(directory: Path, programs: Sequence[str], *extra: str,
          path: str | None = None) -> subprocess.CompletedProcess[str]:
    """Runs counts.py on the library at directory, as webcpp.doc runs it; the twins' directories
    of extra are relative to it. path, when given, is the only PATH it runs with."""
    words = [sys.executable, str(COUNTS), '--library', str(directory)]
    for program in programs:
        words += ['--program', program]
    for index, word in enumerate(extra):
        absolute = index > 0 and extra[index - 1] in ('--examples', '--twins')
        words.append(str(directory / word) if absolute else word)
    environment = None if path is None else {'PATH': path}
    return subprocess.run(words, capture_output=True, text=True, check=False, timeout=120,
                          env=environment)


def counted(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    """The counts a run printed, by name, in the order printed; each line is name=value."""
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    found: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, value = line.split('=', 1)
        assert name not in found, (name, result.stdout)
        found[name] = value
    return found


def fails(result: subprocess.CompletedProcess[str], *texts: str, status: int = 1) -> None:
    """Asserts that the run failed with status, printing nothing on its standard output, and
    named each text."""
    assert result.returncode == status, (status, result.returncode, result.stdout, result.stderr)
    assert result.stdout == '', result.stdout
    for text in texts:
        assert text in result.stderr, (text, result.stderr)


def own_counts(directory: Path, text: str) -> Path:
    """Gives the library at directory a doc/counts.py whose run is the Python text."""
    script = directory / 'doc/counts.py'
    script.parent.mkdir(exist_ok=True)
    script.write_text(text)
    return script


def test_demo_counts_programs_and_headers(root: Path) -> None:
    found = counted(count(library(root, 'demo'), DEMO_PROGRAMS))
    assert found == DEMO_COUNTS, found
    # Programs recorded in another order count the same.
    again = counted(count(root / 'libs/demo', tuple(reversed(DEMO_PROGRAMS))))
    assert again == DEMO_COUNTS, again


def test_oracle_demo_counts_twins_without_running_them(root: Path) -> None:
    directory = library(root, 'oracle_demo')
    # No node on PATH: twins.py --list runs no twin.
    found = counted(count(directory, ORACLE_PROGRAMS, *ORACLE_TWINS, path=''))
    twins = {name: found.pop(name) for name in ('n-twins-agreeing', 'n-twins-divergent',
                                                 'n-examples-without-twin',
                                                 'n-examples-with-original')}
    assert twins == {'n-twins-agreeing': '1', 'n-twins-divergent': '1',
                     'n-examples-without-twin': '1', 'n-examples-with-original': '2'}, twins
    assert (found['n-examples'], found['n-examples-native'], found['n-examples-wasip2'],
            found['n-tests'], found['n-boost-test-suites'], found['n-headers']) == \
        ('3', '3', '0', '1', '0', '1'), found
    # A library that declares no twins has no twin count.
    assert 'n-twins-agreeing' not in counted(count(directory, ORACLE_PROGRAMS)), found


def test_twins_list_faults_fail(root: Path) -> None:
    directory = library(root, 'oracle_demo')
    # A program with neither a twin nor a line in without-twin.txt: twins.py names it.
    (directory / 'example/cube.cpp').write_text('int main() {}\n')
    (directory / 'example/cube.expected').write_text('')
    fails(count(directory, ORACLE_PROGRAMS, *ORACLE_TWINS), 'twins.py', 'cube')
    (directory / 'example/cube.cpp').unlink()
    (directory / 'example/cube.expected').unlink()
    # A tree whose every program has no twin counts no program with an original: nothing.
    for twin in (directory / 'test/oracle/twins').glob('*.mjs'):
        twin.unlink()
    (directory / 'test/oracle/twins/half.expected').unlink()
    (directory / 'test/oracle/twins/without-twin.txt').write_text(
        'square: none\nhalf: none\ncompile_time: none\n')
    fails(count(directory, ORACLE_PROGRAMS, *ORACLE_TWINS), 'no twin', 'test/oracle/twins')


def test_headers_of_nothing_fail(root: Path) -> None:
    directory = library(root, 'demo')
    shutil.rmtree(directory / 'include/webcpp')
    (directory / 'include/webcpp').mkdir()
    (directory / 'include/webcpp/other.hpp').write_text('')
    fails(count(directory, DEMO_PROGRAMS), 'no header', 'webcpp/demo.hpp', 'webcpp/demo/')


def test_library_counts_are_added(root: Path) -> None:
    directory = library(root, 'demo')
    own_counts(directory, 'import sys\n'
                          'assert sys.argv[1:] == [sys.argv[1]], sys.argv\n'
                          'print("n-cases=38")\nprint("n-steps=111")\n')
    found = counted(count(directory, DEMO_PROGRAMS))
    assert list(found)[-2:] == ['n-cases', 'n-steps'], found
    assert (found['n-cases'], found['n-steps'], found['n-examples']) == ('38', '111', '2'), found
    # It runs with the library's directory, from which it finds what it counts.
    own_counts(directory, 'import sys\nfrom pathlib import Path\n'
                          'held = len(list((Path(sys.argv[1]) / "example").glob("*.cpp")))\n'
                          'print(f"n-programs={held}")\n')
    assert counted(count(directory, DEMO_PROGRAMS))['n-programs'] == '2'


def test_library_count_named_as_a_generic_one_fails(root: Path) -> None:
    directory = library(root, 'demo')
    script = own_counts(directory, 'print("n-cases=1")\nprint("n-headers=3")\n')
    fails(count(directory, DEMO_PROGRAMS), f'{script}: n-headers', 'tools/doc/counts.py')
    # A twin count too, which a library without twins does not get.
    own_counts(directory, 'print("n-twins-divergent=3")\n')
    fails(count(directory, DEMO_PROGRAMS), f'{script}: n-twins-divergent', 'tools/doc/counts.py')
    own_counts(directory, 'print("n-tests-wasip2=3")\n')
    fails(count(directory, DEMO_PROGRAMS), f'{script}: n-tests-wasip2', 'tools/doc/counts.py')


def test_library_count_of_nothing_fails(root: Path) -> None:
    directory = library(root, 'demo')
    script = own_counts(directory, 'print("n-cases=0")\n')
    fails(count(directory, DEMO_PROGRAMS), f'{script}: n-cases=0')
    own_counts(directory, '')
    fails(count(directory, DEMO_PROGRAMS), f'{script}: prints no count')
    own_counts(directory, 'import sys\nsys.exit("counts.py: no case file in fixtures")\n')
    fails(count(directory, DEMO_PROGRAMS), f'{script}: exited with 1',
          'counts.py: no case file in fixtures')
    for line in ('n-cases = 3', 'n-cases=three', 'cases', 'n-cases=3 n-steps=4', 'N-CASES=3'):
        own_counts(directory, f'print({line!r})\n')
        fails(count(directory, DEMO_PROGRAMS), f'{script}: not a count name=<number>: {line}')
    own_counts(directory, 'print("n-cases=3")\nprint("n-cases=4")\n')
    fails(count(directory, DEMO_PROGRAMS), f'{script}: n-cases is printed twice')


def test_usage_errors_exit_2(root: Path) -> None:
    directory = library(root, 'demo')
    fails(count(directory, ['test pass native']), 'test is not a kind of program', status=2)
    fails(count(directory, ['run pass native wasm']), 'wasm is not a target', status=2)
    fails(count(directory, ['run pass']), 'run pass', status=2)
    fails(count(directory, DEMO_PROGRAMS, '--suffix', '.mjs'),
          '--examples, --twins and --suffix', status=2)
    fails(count(root / 'nowhere', DEMO_PROGRAMS), 'not a directory', status=2)


CASES = [
    test_demo_counts_programs_and_headers,
    test_oracle_demo_counts_twins_without_running_them,
    test_twins_list_faults_fail,
    test_headers_of_nothing_fail,
    test_library_counts_are_added,
    test_library_count_named_as_a_generic_one_fails,
    test_library_count_of_nothing_fails,
    test_usage_errors_exit_2,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'counts_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='webcpp counts ') as scratch:
            case(Path(scratch))
        print(f'{case.__name__}: ok')
    print('counts_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
