#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/oracle/twins.py on twins that need no original's package: node runs .mjs files
that print, and Python runs .py files, for a port of another language. A tree that agrees
passes, colour off whatever the shell asks; each fault is named and fails: a difference, a twin
that exits non-zero or hangs, an own output equal to the program's, a program without twin and
without line, a malformed line, a line or a twin or an output of no program, a twin and a line
for one program, a program without its .expected; --update rewrites a divergent twin's own output
and refuses to make it the program's; a program is found at any depth, and at the top; --list
runs nothing and accounts for every program; a missing directory, a tree without program, a
command not on PATH and a usage error exit 2. Run with the names of some cases to run only
those."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

RUNNER = Path(__file__).resolve().parent / 'twins.py'


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())


def runner(root: Path, *options: str, command: tuple[str, ...] = ('node',),
           env: Mapping[str, str] | None = None, examples: Path | None = None,
           twins: Path | None = None,
           suffix: str = '.mjs') -> subprocess.CompletedProcess[str]:
    """Runs twins.py over root's tree, the twins run by the words of command; a generous timeout,
    so that a broken timeout handler fails loudly instead of hanging."""
    chosen_examples = root / 'example' if examples is None else examples
    chosen_twins = root / 'twins' if twins is None else twins
    words = ['--', *command] if command else []
    return subprocess.run([sys.executable, str(RUNNER), '--suffix', suffix, *options,
                           '--examples', str(chosen_examples), '--twins', str(chosen_twins),
                           *words],
                          capture_output=True, text=True, env=env, check=False, timeout=120)


def tree(root: Path) -> None:
    """Three programs: a twin that agrees, a twin with an output of its own, and one without."""
    write(root / 'example/xstate/agrees.cpp', '')
    write(root / 'example/xstate/agrees.expected', 'one\ntwo\n')
    write(root / 'example/xstate/differs.cpp', '')
    write(root / 'example/xstate/differs.expected', 'xstate\n')
    write(root / 'example/actors/alone.cpp', '')
    write(root / 'example/actors/alone.expected', 'fuel\n')
    write(root / 'twins/xstate/agrees.mjs', "process.stdout.write('one\\r\\ntwo\\r\\n');\n")
    write(root / 'twins/xstate/differs.mjs', "console.log('XState');\n")
    write(root / 'twins/xstate/differs.expected', 'XState\n')
    write(root / 'twins/without-twin.txt', '# A comment.\nactors/alone: XState has no fuel\n')


def expect(result: subprocess.CompletedProcess[str], status: int, text: str) -> None:
    assert result.returncode == status, (status, result.returncode, result.stdout, result.stderr)
    assert text in result.stderr, (text, result.stderr)


def test_a_tree_that_agrees_passes(root: Path) -> None:
    tree(root)
    result = runner(root)
    expect(result, 0, '')
    assert result.stderr == '', result.stderr


def test_colour_is_off_whatever_the_shell_asks(root: Path) -> None:
    tree(root)
    write(root / 'example/xstate/agrees.expected', '1\n')
    write(root / 'twins/xstate/agrees.mjs', 'console.log(1);\n')
    expect(runner(root, env=dict(os.environ, FORCE_COLOR='3')), 0, '')


def test_the_command_words_reach_the_twin(root: Path) -> None:
    # The words after -- are the command, even those that read as an option of twins.py.
    tree(root)
    write(root / 'example/xstate/agrees.expected', '--conditions=development\n')
    write(root / 'twins/xstate/agrees.mjs', "console.log(process.execArgv.join(' '));\n")
    expect(runner(root, command=('node', '--conditions=development')), 0, '')


def test_a_difference_fails(root: Path) -> None:
    tree(root)
    write(root / 'twins/xstate/agrees.mjs', 'console.log(2);\n')
    result = runner(root)
    expect(result, 1, 'twins: xstate/agrees: differs')
    assert '+2' in result.stderr, result.stderr


def test_a_twin_that_fails_fails(root: Path) -> None:
    tree(root)
    write(root / 'twins/xstate/agrees.mjs', "console.log('one\\ntwo'); process.exit(3);\n")
    expect(runner(root), 1, 'xstate/agrees: exited with status 3')


def test_a_twin_that_hangs_is_killed(root: Path) -> None:
    tree(root)
    write(root / 'twins/xstate/agrees.mjs', 'for (;;) {}\n')
    expect(runner(root, '--timeout', '2'), 1, 'xstate/agrees: did not end within 2.0 s')


def test_an_own_output_equal_to_the_program_s_fails(root: Path) -> None:
    tree(root)
    write(root / 'twins/xstate/differs.expected', 'xstate\n')
    expect(runner(root), 1, "xstate/differs: its own output is the program's")


def test_update_rewrites_an_own_output(root: Path) -> None:
    tree(root)
    write(root / 'twins/xstate/differs.expected', 'stale\n')
    expect(runner(root, '--update'), 0, '')
    assert (root / 'twins/xstate/differs.expected').read_text() == 'XState\n'
    # The program's own output and an agreeing twin are never written.
    assert (root / 'example/xstate/differs.expected').read_text() == 'xstate\n'
    assert not (root / 'twins/xstate/agrees.expected').exists()


def test_update_refuses_an_agreeing_output(root: Path) -> None:
    # A divergent twin whose output now matches the program's is not a divergence any more:
    # --update refuses to make its own output the program's, and leaves it as it was.
    tree(root)
    write(root / 'twins/xstate/differs.mjs', "console.log('xstate');\n")
    write(root / 'twins/xstate/differs.expected', 'stale again\n')
    expect(runner(root, '--update'), 1, 'xstate/differs: --update refuses')
    assert (root / 'twins/xstate/differs.expected').read_text() == 'stale again\n'


def test_no_twin_and_no_line_fails(root: Path) -> None:
    tree(root)
    write(root / 'twins/without-twin.txt', '')
    expect(runner(root), 1, 'actors/alone: no twin, and no line in without-twin.txt')
    (root / 'twins/without-twin.txt').unlink()
    expect(runner(root), 1, 'actors/alone: no twin, and no line in without-twin.txt')


def test_a_malformed_line_fails(root: Path) -> None:
    tree(root)
    write(root / 'twins/without-twin.txt', 'actors/alone XState has no fuel\n')
    expect(runner(root), 1, 'without-twin.txt:1: not `<path>: <reason>`')
    write(root / 'twins/without-twin.txt', 'actors/alone:\n')
    expect(runner(root), 1, 'without-twin.txt:1: not `<path>: <reason>`')
    write(root / 'twins/without-twin.txt', ': XState has no fuel\n')
    expect(runner(root), 1, 'without-twin.txt:1: not `<path>: <reason>`')
    write(root / 'twins/without-twin.txt',
          'actors/alone: XState has no fuel\nactors/alone: twice\n')
    expect(runner(root), 1, 'without-twin.txt:2: actors/alone is named twice')


def test_a_line_that_names_no_example_fails(root: Path) -> None:
    tree(root)
    write(root / 'twins/without-twin.txt',
          'actors/alone: XState has no fuel\nxstate/ghost: never existed\n')
    expect(runner(root), 1, 'xstate/ghost: without-twin.txt names no example')


def test_a_twin_and_a_line_fails(root: Path) -> None:
    tree(root)
    write(root / 'twins/actors/alone.mjs', "console.log('fuel');\n")
    expect(runner(root), 1, 'actors/alone: a twin, and a line in without-twin.txt')


def test_a_twin_of_no_example_fails(root: Path) -> None:
    tree(root)
    write(root / 'twins/xstate/stray.mjs', '')
    expect(runner(root), 1, 'xstate/stray: a twin of no example')


def test_an_output_of_no_twin_fails(root: Path) -> None:
    tree(root)
    write(root / 'twins/xstate/orphan.expected', '')
    expect(runner(root), 1, 'xstate/orphan: an output of no twin')


def test_missing_expected_is_a_fault(root: Path) -> None:
    # A program without its .expected, with a twin or without one, is named; the others run.
    tree(root)
    (root / 'example/xstate/agrees.expected').unlink()
    (root / 'example/actors/alone.expected').unlink()
    write(root / 'twins/xstate/differs.mjs', "console.log('changed');\n")
    result = runner(root)
    for name in ('xstate/agrees', 'actors/alone'):
        missing = root / f'example/{name}.expected'
        expect(result, 1, f"twins: {name}: the program's output {missing} does not exist")
    assert 'xstate/differs: differs' in result.stderr, result.stderr


def test_nested_paths_are_programs(root: Path) -> None:
    # A program is found at any depth and named by its path; one at the top has no group.
    tree(root)
    write(root / 'example/a/b/c.cpp', '')
    write(root / 'example/a/b/c.expected', 'deep\n')
    write(root / 'example/top.cpp', '')
    write(root / 'example/top.expected', 'top\n')
    write(root / 'twins/a/b/c.mjs', "console.log('deep');\n")
    write(root / 'twins/without-twin.txt',
          'actors/alone: XState has no fuel\ntop: a program at the top, without twin\n')
    expect(runner(root), 0, '')
    write(root / 'twins/a/b/c.mjs', "console.log('shallow');\n")
    expect(runner(root), 1, 'twins: a/b/c: differs')
    (root / 'twins/a/b/c.mjs').unlink()
    expect(runner(root), 1, 'a/b/c: no twin, and no line in without-twin.txt')


def test_another_suffix_and_language(root: Path) -> None:
    # A port of a Python library: its twins are .py files that Python runs; a .mjs is not one.
    write(root / 'example/greet.cpp', '')
    write(root / 'example/greet.expected', 'hello\n')
    write(root / 'twins/greet.py', "print('hello')\n")
    write(root / 'twins/greet.mjs', '')
    expect(runner(root, suffix='.py', command=(sys.executable,)), 0, '')
    write(root / 'twins/greet.py', "print('goodbye')\n")
    expect(runner(root, suffix='.py', command=(sys.executable,)), 1, 'greet: differs')


def test_list_counts_every_program(root: Path) -> None:
    # --list runs nothing, so it needs no command, and a twin that would fail is not run.
    tree(root)
    write(root / 'example/xstate/also.cpp', '')
    write(root / 'example/xstate/also.expected', 'also\n')
    write(root / 'twins/xstate/also.mjs', 'process.exit(1);\n')
    result = runner(root, '--list', command=())
    expect(result, 0, '')
    assert result.stdout == ('without-twin actors/alone\n'
                             'agreeing xstate/agrees\n'
                             'agreeing xstate/also\n'
                             'divergent xstate/differs\n'
                             'total 4 2 1 1\n'), result.stdout
    # A command not on PATH does not matter to a run that runs nothing.
    expect(runner(root, '--list', command=('no-such-tool',)), 0, '')
    # A tree with a fault is not counted: its faults are named instead.
    write(root / 'twins/xstate/differs.expected', 'xstate\n')
    write(root / 'twins/xstate/stray.mjs', '')
    result = runner(root, '--list', command=())
    expect(result, 1, "xstate/differs: its own output is the program's")
    assert 'xstate/stray: a twin of no example' in result.stderr, result.stderr
    assert result.stdout == '', result.stdout


def test_missing_directories_exit_2(root: Path) -> None:
    tree(root)
    missing = root / 'no-such-directory'
    expect(runner(root, examples=missing), 2, f'twins: {missing} does not exist')
    expect(runner(root, twins=missing), 2, f'twins: {missing} does not exist')
    empty = root / 'empty-examples'
    empty.mkdir()
    expect(runner(root, examples=empty), 2, f'twins: {empty} has no example')
    expect(runner(root, '--list', command=(), examples=empty), 2, f'{empty} has no example')


def test_command_not_on_path_exits_2(root: Path) -> None:
    tree(root)
    expect(runner(root, command=('no-such-tool',)), 2, 'twins: no-such-tool is not on PATH')


def test_usage_errors_exit_2(root: Path) -> None:
    tree(root)
    expect(runner(root, command=()), 2, 'the command a twin runs with')
    no_suffix = subprocess.run([sys.executable, str(RUNNER), '--examples', str(root / 'example'),
                                '--twins', str(root / 'twins'), '--', 'node'],
                               capture_output=True, text=True, check=False, timeout=120)
    expect(no_suffix, 2, '--suffix')
    expect(runner(root, suffix='.expected'), 2, '--suffix')
    expect(runner(root, suffix=''), 2, '--suffix')
    expect(runner(root, '--list', '--update'), 2, '--update')


CASES: list[Callable[[Path], None]] = [
    test_a_tree_that_agrees_passes,
    test_colour_is_off_whatever_the_shell_asks,
    test_the_command_words_reach_the_twin,
    test_a_difference_fails,
    test_a_twin_that_fails_fails,
    test_a_twin_that_hangs_is_killed,
    test_an_own_output_equal_to_the_program_s_fails,
    test_update_rewrites_an_own_output,
    test_update_refuses_an_agreeing_output,
    test_no_twin_and_no_line_fails,
    test_a_malformed_line_fails,
    test_a_line_that_names_no_example_fails,
    test_a_twin_and_a_line_fails,
    test_a_twin_of_no_example_fails,
    test_an_output_of_no_twin_fails,
    test_missing_expected_is_a_fault,
    test_nested_paths_are_programs,
    test_another_suffix_and_language,
    test_list_counts_every_program,
    test_missing_directories_exit_2,
    test_command_not_on_path_exits_2,
    test_usage_errors_exit_2,
]


def main(argv: list[str]) -> int:
    if shutil.which('node') is None:
        print('twins_test: node is not on PATH', file=sys.stderr)
        return 2
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'twins_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='webcpp twins ') as scratch:
            case(Path(scratch))
        print(f'{case.__name__}: ok')
    print('twins_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
