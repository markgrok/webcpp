#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/generated/generated.py, the driver of webcpp.generated, with a small generator that
writes its word into each output it is given: words that make no steps, among them an output that
two steps name, are a usage error; check and update keep their outputs apart, so that neither
touches what the other wrote; a build directory that cannot be emptied fails; update refuses a
committed output that is not a file before it writes anything, removes a staged file a killed run
left beside a committed one, leaves every committed file as it was when a copy fails, and, when a
rename fails, names what it replaced and what it left, with no traceback. Each case runs in a
scratch directory of its own, whose path holds a space. Run with the names of some cases to run
only those."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVER = HERE / 'generated.py'

# The generator: `gen.py WORD PATH...` writes WORD and a newline at each path.
GENERATOR = '''import sys
from pathlib import Path

word, *paths = sys.argv[1:]
for path in paths:
    Path(path).write_text(word + '\\n')
'''

WRITER = 'libs/gen/test//update-generated'


def setup(root: Path) -> Path:
    """Writes the generator into root/test, with its committed outputs a.txt and sub/b.txt; returns
    root/test."""
    test = root / 'test'
    (test / 'sub').mkdir(parents=True)
    (test / 'gen.py').write_text(GENERATOR)
    (test / 'a.txt').write_text('word\n')
    (test / 'sub/b.txt').write_text('word\n')
    return test


def step(test: Path, name: str, word: str, *outputs: str) -> list[str]:
    """The driver's words of the step name: gen.py run in test with word, writing outputs."""
    return [name, str(test), str(test / 'gen.py'), '1', word, str(len(outputs)),
            *(str(test / output) for output in outputs)]


def drive(mode: str, build: Path, *words: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(DRIVER), mode, str(build), WRITER, *words],
                          capture_output=True, text=True, check=False, timeout=120)


def expect(result: subprocess.CompletedProcess[str], status: int, *texts: str) -> None:
    output = result.stdout + result.stderr
    assert result.returncode == status, (status, result.returncode, output)
    assert 'Traceback' not in output, output
    for text in texts:
        assert text in output, (text, output)


def files(directory: Path) -> dict[str, tuple[bytes, int]]:
    """Every file under directory, by its path relative to it, with its bytes and its time."""
    return {str(path.relative_to(directory)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in sorted(directory.rglob('*')) if path.is_file()}


def test_words_that_make_no_steps_are_a_usage_error(root: Path) -> None:
    test = setup(root)
    build = root / 'build'
    good = step(test, 'a', 'word', 'a.txt')
    for words, message in (
            ([], 'no step was given'),
            (good[:2], 'a step needs a name, a directory and a script'),
            (good[:3] + ['many'], 'a count was expected at word 4'),
            (good[:3] + ['5', 'word'], 'the count 5 at word 4 runs past the last word'),
            (good[:5] + ['0'], 'a: a generator writes at least one output'),
            (step(test, 'a', 'word', 'a.txt', 'a.txt'), f'a: {test / "a.txt"} is named twice'),
            (good + step(test, 'b', 'word', 'a.txt'),
             f'b: {test / "a.txt"} is written by a already')):
        for mode in ('check', 'update'):
            expect(drive(mode, build, *words), 2, message)
    expect(subprocess.run([sys.executable, str(DRIVER), 'check', str(build)], capture_output=True,
                          text=True, check=False, timeout=120),
           2, 'usage: generated.py check|update BUILD WRITER STEP...')
    expect(drive('write', build, *good), 2, 'usage: generated.py check|update BUILD WRITER STEP...')
    assert not build.exists(), sorted(build.rglob('*'))


def test_check_and_update_keep_their_outputs_apart(root: Path) -> None:
    # Each leaves what the other wrote as it was, byte and time, so that one b2 request that builds
    # both, in parallel, never compares or copies a file the other is writing.
    test = setup(root)
    build = root / 'build'
    words = step(test, 'a', 'word', 'a.txt', 'sub/b.txt')
    expect(drive('check', build, *words), 0)
    checked = files(build)
    assert checked, 'the check wrote nothing into its build directory'
    expect(drive('update', build, *words), 0)
    updated = {path: kept for path, kept in files(build).items() if path not in checked}
    assert updated, 'the update wrote nothing into its build directory'
    assert {path: kept for path, kept in files(build).items() if path in checked} == checked
    expect(drive('check', build, *words), 0)
    assert {path: kept for path, kept in files(build).items() if path in updated} == updated


def test_a_build_directory_that_cannot_be_emptied_fails(root: Path) -> None:
    # A stale output left there could pass as written.
    test = setup(root)
    build = root / 'build'
    words = step(test, 'a', 'word', 'a.txt', 'sub/b.txt')
    expect(drive('check', build, *words), 0)
    stuck = next(path for path in (build / 'check').rglob('*') if path.is_dir())
    stuck.chmod(0o555)
    try:
        if os.access(stuck, os.W_OK):
            print('test_a_build_directory_that_cannot_be_emptied_fails: skipped, every directory '
                  'is writable here')
            return
        expect(drive('check', build, *words), 1, 'generated: a: cannot make ', ' ready: ')
    finally:
        stuck.chmod(0o755)


def test_a_committed_output_that_is_not_a_file_is_refused(root: Path) -> None:
    test = setup(root)
    (test / 'sub/b.txt').unlink()
    (test / 'sub/b.txt').mkdir()
    (test / 'a.txt').write_text('stale\n')
    expect(drive('update', root / 'build', *step(test, 'a', 'word', 'a.txt', 'sub/b.txt')), 1,
           f'generated: a: {test / "sub/b.txt"} is not a file')
    assert (test / 'a.txt').read_text() == 'stale\n'
    assert not list(test.rglob('*.generated')), sorted(test.rglob('*'))


def test_a_staged_file_a_killed_run_left_is_removed(root: Path) -> None:
    # Removed even by an update whose generator fails, which stages nothing over it.
    test = setup(root)
    (test / 'fail.py').write_text('import sys\n\nsys.exit(1)\n')
    (test / 'sub/b.txt.generated').write_text('half\n')
    failing = ['a', str(test), str(test / 'fail.py'), '0', '2', str(test / 'a.txt'),
               str(test / 'sub/b.txt')]
    expect(drive('update', root / 'build', *failing), 1,
           'generated: a: fail.py exited with status 1')
    assert not list(test.rglob('*.generated')), sorted(test.rglob('*'))
    assert (test / 'a.txt').read_text() == 'word\n'
    assert (test / 'sub/b.txt').read_text() == 'word\n'


def test_a_copy_that_fails_leaves_every_committed_file(root: Path) -> None:
    test = setup(root)
    (test / 'sub').chmod(0o555)
    try:
        if os.access(test / 'sub', os.W_OK):
            # Whoever can write any directory (root) cannot see this case.
            print('test_a_copy_that_fails_leaves_every_committed_file: skipped, every directory '
                  'is writable here')
            return
        expect(drive('update', root / 'build', *step(test, 'a', 'new', 'a.txt', 'sub/b.txt')), 1,
               'generated: a: cannot stage', 'sub/b.txt.generated')
    finally:
        (test / 'sub').chmod(0o755)
    assert (test / 'a.txt').read_text() == 'word\n'
    assert (test / 'sub/b.txt').read_text() == 'word\n'
    assert not list(test.rglob('*.generated')), sorted(test.rglob('*'))


# Runs the driver's main with os.replace failing on its second call, as a full disk or a file
# made read-only meanwhile would make it fail.
FAILING_RENAME = '''import os
import sys

sys.path.insert(0, sys.argv[1])
import generated

calls = []
replace = os.replace


def failing(source, destination):
    calls.append(destination)
    if len(calls) == 2:
        raise PermissionError(13, 'Permission denied', str(destination))
    replace(source, destination)


os.replace = failing
sys.exit(generated.main(sys.argv[2:]))
'''


def test_a_rename_that_fails_names_what_was_replaced(root: Path) -> None:
    test = setup(root)
    result = subprocess.run([sys.executable, '-c', FAILING_RENAME, str(HERE), 'update',
                             str(root / 'build'), WRITER,
                             *step(test, 'a', 'new', 'a.txt', 'sub/b.txt')],
                            capture_output=True, text=True, check=False, timeout=120)
    expect(result, 1, f'generated: replaced {test / "a.txt"}',
           f'generated: not replaced {test / "sub/b.txt"}', 'Permission denied')
    assert (test / 'a.txt').read_text() == 'new\n'
    assert (test / 'sub/b.txt').read_text() == 'word\n'
    assert not list(test.rglob('*.generated')), sorted(test.rglob('*'))


CASES: list[Callable[[Path], None]] = [
    test_words_that_make_no_steps_are_a_usage_error,
    test_check_and_update_keep_their_outputs_apart,
    test_a_build_directory_that_cannot_be_emptied_fails,
    test_a_committed_output_that_is_not_a_file_is_refused,
    test_a_staged_file_a_killed_run_left_is_removed,
    test_a_copy_that_fails_leaves_every_committed_file,
    test_a_rename_that_fails_names_what_was_replaced,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'generated_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='webcpp generated ') as scratch:
            case(Path(scratch))
        print(f'{case.__name__}: ok')
    print('generated_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
