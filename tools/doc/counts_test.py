#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/doc/counts.py: the fixture demo counts its examples and its tests per target, its
Boost.Test suite and its headers compiled alone, from the programs b2 recorded, each count of a
thousand or more printed with a thousands separator, 1,234; the fixture
component_demo counts its served programs, as tests and on their own; the fixture browser_demo
counts its link-only program and its driven test, as tests and on their own; the fixture
oracle_demo counts its agreeing, divergent and without-twin programs from twins.py --list, which
runs no twin; a library's own doc/counts.py adds its counts, its standard error shown and never
counted, and fails the count when it names a generic one, counts nothing, prints nothing or fails;
and so does a library that declares twins and has none. Each case copies a fixture library into a
scratch directory. Run with the names of some cases to run only those."""

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
# <name> <target>...", one per program.
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
    'example catches native wasip2 wasip3',
)

# What demo counts, every count of the programs b2 recorded, a zero included.
DEMO_COUNTS = {
    'n-examples': '2',
    'n-examples-native': '2',
    'n-examples-emscripten': '0',
    'n-examples-wasip2': '2',
    'n-examples-wasip3': '2',
    'n-tests': '9',
    'n-tests-native': '9',
    'n-tests-emscripten': '0',
    'n-tests-wasip2': '6',
    'n-tests-wasip3': '6',
    'n-served': '0',
    'n-served-native': '0',
    'n-served-emscripten': '0',
    'n-served-wasip2': '0',
    'n-served-wasip3': '0',
    'n-linked': '0',
    'n-linked-native': '0',
    'n-linked-emscripten': '0',
    'n-linked-wasip2': '0',
    'n-linked-wasip3': '0',
    'n-driven': '0',
    'n-driven-native': '0',
    'n-driven-emscripten': '0',
    'n-driven-wasip2': '0',
    'n-driven-wasip3': '0',
    'n-boost-test-suites': '1',
    'n-headers': '2',
}

# The programs of component_demo's test Jamfile, as tools/webcpp.jam records them, with a served
# example and its native-only header test beside them: an example Jamfile's served program is a
# test, as the report shows it.
COMPONENT_PROGRAMS = (
    'compile bindings wasip2 wasip3',
    'run native_alone native',
    'serve answers wasip2 wasip3',
    'serve hello wasip2',
    'headers-alone alone-component_demo native',
)

# The programs of browser_demo's test, driver and example Jamfiles, as tools/webcpp.jam records
# them: a link-only program and a driven test among them.
BROWSER_PROGRAMS = (
    'headers-alone alone-browser_demo native emscripten',
    'headers-alone alone-browser_demo-native native',
    'headers-alone alone-browser_demo-page emscripten',
    'run reads native emscripten',
    'run catches native emscripten',
    'run pointer native emscripten',
    'run json native emscripten',
    'run-fail fails native emscripten',
    'drive driven native emscripten',
    'example hello native emscripten',
    'link page emscripten',
)

ORACLE_PROGRAMS = (
    'run square native',
    'headers-alone alone-oracle_demo native',
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
        ('3', '3', '0', '2', '0', '1'), found
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


def test_served_programs_are_tests_and_counted(root: Path) -> None:
    # A program of kind serve is a test, on its targets, and is counted on its own too.
    found = counted(count(library(root, 'component_demo'), COMPONENT_PROGRAMS))
    assert {name: found[name] for name in found if 'served' in name or 'tests' in name} == {
        'n-tests': '5',
        'n-tests-native': '2',
        'n-tests-emscripten': '0',
        'n-tests-wasip2': '3',
        'n-tests-wasip3': '2',
        'n-served': '2',
        'n-served-native': '0',
        'n-served-emscripten': '0',
        'n-served-wasip2': '2',
        'n-served-wasip3': '1',
    }, found
    assert (found['n-examples'], found['n-headers']) == ('0', '1'), found
    # A library's own count may not take the name.
    script = own_counts(root / 'libs/component_demo', 'print("n-served-wasip3=4")\n')
    fails(count(root / 'libs/component_demo', COMPONENT_PROGRAMS), f'{script}: n-served-wasip3',
          'tools/doc/counts.py')


def test_linked_and_driven_programs_are_tests_and_counted(root: Path) -> None:
    # A link-only program (webcpp.link) and a driven test (webcpp.drive) are tests of their
    # targets, each counted on its own too.
    found = counted(count(library(root, 'browser_demo'), BROWSER_PROGRAMS))
    assert {name: found[name] for name in found
            if any(kind in name for kind in ('tests', 'linked', 'driven'))} == {
        'n-tests': '10',
        'n-tests-native': '8',
        'n-tests-emscripten': '9',
        'n-tests-wasip2': '0',
        'n-tests-wasip3': '0',
        'n-linked': '1',
        'n-linked-native': '0',
        'n-linked-emscripten': '1',
        'n-linked-wasip2': '0',
        'n-linked-wasip3': '0',
        'n-driven': '1',
        'n-driven-native': '1',
        'n-driven-emscripten': '1',
        'n-driven-wasip2': '0',
        'n-driven-wasip3': '0',
    }, found
    assert (found['n-examples'], found['n-examples-emscripten'], found['n-headers']) == (
        '1', '1', '3'), found


def test_headers_are_those_compiled_alone(root: Path) -> None:
    # n-headers counts what webcpp.headers-alone recorded, one program per header, and reads no
    # header itself: the tree's headers are b2's to find.
    directory = library(root, 'demo')
    shutil.rmtree(directory / 'include')
    assert counted(count(directory, DEMO_PROGRAMS))['n-headers'] == '2'
    more = (*DEMO_PROGRAMS, 'headers-alone alone-demo-more native')
    assert counted(count(directory, more))['n-headers'] == '3'
    # A library whose tests compile no header alone fails, rather than put a zero on the page:
    # every library compiles its public headers alone.
    plain = tuple(record for record in DEMO_PROGRAMS if not record.startswith('headers-alone'))
    fails(count(directory, plain), 'demo declares no webcpp.headers-alone: its headers are not '
                                   'counted')


def test_a_compile_diagnostic_is_a_test(root: Path) -> None:
    # A test that must stop with the error it states (webcpp.compile-diagnostic) is a test of each
    # of its targets, as a compile-fail test is.
    directory = library(root, 'demo')
    more = (*DEMO_PROGRAMS, 'compile-diagnostic stated native wasip2')
    found = counted(count(directory, more))
    assert (found['n-tests'], found['n-tests-native'], found['n-tests-wasip2'],
            found['n-tests-wasip3']) == ('10', '10', '7', '6'), found


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
    # What it writes on its standard error is shown there, and is no count.
    own_counts(directory, 'import sys\nprint("a warning, n-steps=4", file=sys.stderr)\n'
                          'print("n-cases=38")\n')
    result = count(directory, DEMO_PROGRAMS)
    assert counted(result)['n-cases'] == '38' and 'n-steps' not in counted(result), result
    assert 'a warning, n-steps=4' in result.stderr, result.stderr


def test_counts_print_with_a_thousands_separator(root: Path) -> None:
    # A page reads 1,234 where a count reaches a thousand, as English writes it, in the counts of
    # the programs b2 recorded and in a library's own; a library's counts.py prints plain digits.
    directory = library(root, 'demo')
    own_counts(directory, 'print("n-cases=999")\nprint("n-steps=1111")\n'
                          'print("n-checks=1234567")\n')
    many = (*DEMO_PROGRAMS, *(f'run case_{index} native' for index in range(1000)))
    found = counted(count(directory, many))
    assert (found['n-cases'], found['n-steps'], found['n-checks']) == (
        '999', '1,111', '1,234,567'), found
    assert (found['n-tests'], found['n-tests-native'], found['n-tests-wasip2']) == (
        '1,009', '1,009', '6'), found
    for line in ('n-cases=1,111', 'n-cases=1 111'):
        script = own_counts(directory, f'print({line!r})\n')
        fails(count(directory, DEMO_PROGRAMS), f'{script}: not a count name=<number>: {line}')


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
    test_headers_are_those_compiled_alone,
    test_a_compile_diagnostic_is_a_test,
    test_served_programs_are_tests_and_counted,
    test_linked_and_driven_programs_are_tests_and_counted,
    test_library_counts_are_added,
    test_counts_print_with_a_thousands_separator,
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
