#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/node/install.py with a stand-in for npm, first on PATH, which writes a package into
node_modules after a moment and counts its runs: the packages are installed once per lockfile and
linked at node_modules, and a second run installs nothing; installs at once run npm once and all
succeed; the install of a lockfile that changed is kept for one generation more, for a build that
still uses it, and then pruned, as is at once the directory a killed npm ci left, even one it made
read-only; a node_modules that npm ci made in the directory itself gives way to the link; a failed
npm ci fails the run, naming it, and leaves the link as it was, and so does an npm not on PATH; a
directory the system will not let it write ends the run with a message, not a traceback. The
lock, which Windows takes with msvcrt rather than fcntl, is checked with stand-ins for both, and
the installer is imported where there is no fcntl. Run with the names of some cases to run only
those."""

from __future__ import annotations

import errno
import os
import subprocess
import sys
import tempfile
import types
from collections.abc import Callable
from pathlib import Path
from unittest import mock

import install as installer

SCRIPT = Path(__file__).resolve().parent / 'install.py'

# The stand-in for npm: `npm ci` writes node_modules/pinned/index.js holding package-lock.json's
# text after a second, and appends a line to the file NPM_RUNS names; NPM_FAILS makes it fail.
FAKE_NPM = """#!{python}
import os
import sys
import time
from pathlib import Path

assert sys.argv[1] == 'ci', sys.argv
with open(os.environ['NPM_RUNS'], 'a') as runs:
    runs.write(os.getcwd() + '\\n')
if os.environ.get('NPM_FAILS'):
    print('npm error code E404')
    sys.exit(1)
time.sleep(1)
package = Path('node_modules/pinned')
package.mkdir(parents=True)
(package / 'index.js').write_text(Path('package-lock.json').read_text())
"""

Case = Callable[[Path], None]


def environment(scratch: Path, fails: bool = False) -> dict[str, str]:
    """The environment of an install: the stand-in first on PATH, its runs counted in scratch."""
    tools = scratch / 'tools'
    if not tools.is_dir():
        tools.mkdir()
        (tools / 'npm').write_text(FAKE_NPM.format(python=sys.executable))
        (tools / 'npm').chmod(0o755)
    found = dict(os.environ, PATH=f'{tools}{os.pathsep}{os.environ["PATH"]}',
                 NPM_RUNS=str(scratch / 'runs'))
    if fails:
        found['NPM_FAILS'] = '1'
    return found


def project(scratch: Path, lock: str = 'one') -> Path:
    """A directory with a package.json and a package-lock.json that holds lock."""
    directory = scratch / 'project'
    directory.mkdir(exist_ok=True)
    (directory / 'package.json').write_text('{"name": "project"}\n')
    (directory / 'package-lock.json').write_text(f'{{"lock": "{lock}"}}\n')
    return directory


def start(directory: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen([sys.executable, str(SCRIPT), str(directory)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def install(directory: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), str(directory)], env=env,
                          capture_output=True, text=True, check=False, timeout=120)


def runs(scratch: Path) -> int:
    """How many times npm ci ran."""
    counted = scratch / 'runs'
    return len(counted.read_text().splitlines()) if counted.is_file() else 0


def installs(directory: Path) -> list[str]:
    """What .node-modules holds, but its lock and the name of the previous install."""
    return sorted(name for name in os.listdir(directory / '.node-modules')
                  if name not in ('.lock', '.previous'))


def linked(directory: Path) -> str:
    """What node_modules shows: the lockfile the installed package holds."""
    link = directory / 'node_modules'
    assert link.is_symlink(), link
    return (link / 'pinned/index.js').read_text()


def test_installed_once_and_linked(scratch: Path) -> None:
    directory = project(scratch)
    env = environment(scratch)
    for _ in range(2):
        result = install(directory, env)
        assert result.returncode == 0, result
    assert runs(scratch) == 1, runs(scratch)
    assert linked(directory) == '{"lock": "one"}\n'
    assert len(installs(directory)) == 1, installs(directory)


def test_installs_at_once_run_npm_once(scratch: Path) -> None:
    directory = project(scratch)
    env = environment(scratch)
    started = [start(directory, env) for _ in range(4)]
    for process in started:
        output, _ = process.communicate(timeout=120)
        assert process.returncode == 0, output
    assert runs(scratch) == 1, runs(scratch)
    assert linked(directory) == '{"lock": "one"}\n'
    assert len(installs(directory)) == 1, installs(directory)


def test_a_changed_lockfile_keeps_the_previous_generation(scratch: Path) -> None:
    # A build that resolved node_modules before the lockfile changed still reads the install it
    # found, so the install the link named before is kept for one generation more: generation 1
    # outlives the install of generation 2, and any run of it, and goes with generation 3.
    directory = project(scratch, lock='one')
    env = environment(scratch)
    assert install(directory, env).returncode == 0
    first = installer.digest(directory)
    project(scratch, lock='two')
    second = installer.digest(directory)
    for _ in range(2):
        assert install(directory, env).returncode == 0
        assert linked(directory) == '{"lock": "two"}\n'
        assert installs(directory) == sorted([first, second]), installs(directory)
    kept = directory / '.node-modules' / first / 'node_modules/pinned/index.js'
    assert kept.read_text() == '{"lock": "one"}\n', kept
    # A killed npm ci's directory, which it had made read-only, goes at once all the same.
    left = directory / '.node-modules' / f'{second}.k1ll3d'
    (left / 'node_modules/half').mkdir(parents=True)
    (left / 'node_modules/half/index.js').write_text('half\n')
    (left / 'node_modules/half').chmod(0o500)
    project(scratch, lock='three')
    third = installer.digest(directory)
    assert install(directory, env).returncode == 0
    assert linked(directory) == '{"lock": "three"}\n'
    assert installs(directory) == sorted([second, third]), installs(directory)
    assert runs(scratch) == 3, runs(scratch)


def test_what_a_killed_install_left_is_pruned(scratch: Path) -> None:
    directory = project(scratch)
    env = environment(scratch)
    assert install(directory, env).returncode == 0
    current = installs(directory)
    # A killed npm ci leaves its temporary directory, named after the digest; a killed prune, the
    # directory it renamed aside.
    left = directory / '.node-modules' / f'{current[0]}.k1ll3d'
    (left / 'node_modules/half').mkdir(parents=True)
    aside = directory / '.node-modules' / '.removed.0123'
    aside.mkdir()
    # A killed link, the link made under another name before it is renamed over node_modules.
    killed = directory / '.node-modules' / '.linking.99999'
    killed.symlink_to('.node-modules', target_is_directory=True)
    assert install(directory, env).returncode == 0
    assert installs(directory) == current, installs(directory)
    assert not os.path.lexists(killed), os.listdir(directory / '.node-modules')
    assert runs(scratch) == 1, runs(scratch)


class Killed(BaseException):
    """What stands for a kill in the middle of a run."""


def test_a_killed_link_is_left_where_git_ignores_it(scratch: Path) -> None:
    # The link is made under another name before it is renamed over node_modules. A run killed in
    # between leaves it under .node-modules/, which git ignores wherever packages are installed,
    # never beside node_modules, where git would list it; and the next run prunes it there.
    directory = project(scratch)
    done = directory / '.node-modules' / 'installed'
    (done / 'node_modules').mkdir(parents=True)

    with mock.patch.object(installer.os, 'replace', side_effect=Killed), \
            mock.patch.object(installer.os, 'rename', side_effect=Killed):
        try:
            installer.linked(directory, done)
        except Killed:
            pass
    assert sorted(os.listdir(directory)) == ['.node-modules', 'package-lock.json',
                                             'package.json'], os.listdir(directory)
    left = [name for name in os.listdir(directory / '.node-modules') if name != 'installed']
    assert len(left) == 1 and os.path.islink(directory / '.node-modules' / left[0]), left
    assert install(directory, environment(scratch)).returncode == 0
    assert installs(directory) == [installer.digest(directory)], installs(directory)
    assert linked(directory) == '{"lock": "one"}\n'


def test_a_node_modules_of_npm_gives_way_to_the_link(scratch: Path) -> None:
    directory = project(scratch)
    (directory / 'node_modules/stale').mkdir(parents=True)
    assert install(directory, environment(scratch)).returncode == 0
    assert linked(directory) == '{"lock": "one"}\n'


def test_a_failed_install_keeps_the_link(scratch: Path) -> None:
    directory = project(scratch)
    assert install(directory, environment(scratch)).returncode == 0
    project(scratch, lock='two')
    result = install(directory, environment(scratch, fails=True))
    assert result.returncode == 1, result
    assert 'npm ci failed' in result.stderr and 'E404' in result.stderr, result.stderr
    assert linked(directory) == '{"lock": "one"}\n'
    assert len(installs(directory)) == 1, installs(directory)


def test_an_npm_not_on_path_is_named(scratch: Path) -> None:
    directory = project(scratch)
    empty = scratch / 'empty'
    empty.mkdir()
    result = install(directory, dict(os.environ, PATH=str(empty)))
    assert result.returncode == 1, result
    assert 'npm' in result.stderr and 'PATH' in result.stderr, result.stderr
    assert not (directory / 'node_modules').exists(), directory


def test_a_directory_it_cannot_write_is_named(scratch: Path) -> None:
    # The system refusing a directory, read-only here, ends the run with a message naming the
    # cause, as every other failure does, and never with a traceback: first the directory itself,
    # where .node-modules cannot be made, then .node-modules, where npm ci's cannot.
    directory = project(scratch)
    for refused in (directory, directory / '.node-modules'):
        refused.mkdir(exist_ok=True)
        refused.chmod(0o555)
        try:
            result = install(directory, environment(scratch))
        finally:
            refused.chmod(0o755)
        assert result.returncode == 1, (refused, result)
        assert result.stderr.startswith('install.py: '), (refused, result.stderr)
        assert 'Permission denied' in result.stderr, (refused, result.stderr)
        assert 'Traceback' not in result.stderr, (refused, result.stderr)
    assert runs(scratch) == 0, runs(scratch)


def fake_msvcrt(refusals: int, error: int = errno.EDEADLK) -> tuple[types.SimpleNamespace,
                                                                    list[tuple[int, int, int]]]:
    """A stand-in for msvcrt whose locking(LK_LOCK) fails, as it does after about ten seconds
    of another's lock, refusals times with error, and the calls it was given, with the position
    of their file."""
    calls: list[tuple[int, int, int]] = []

    def locking(fd: int, mode: int, nbytes: int) -> None:
        calls.append((mode, nbytes, os.lseek(fd, 0, os.SEEK_CUR)))
        if mode == fake.LK_LOCK and sum(call[0] == fake.LK_LOCK for call in calls) <= refusals:
            raise OSError(error, os.strerror(error))

    fake = types.SimpleNamespace(LK_LOCK=1, LK_UNLCK=0, locking=locking)
    return fake, calls


def test_msvcrt_is_retried_until_the_lock_is_had(scratch: Path) -> None:
    fake, calls = fake_msvcrt(refusals=3)
    lock = scratch / 'lock'
    with installer.held(lock, fake):
        assert calls == [(1, 1, 0)] * 4, calls
    assert calls == [(1, 1, 0)] * 4 + [(0, 1, 0)], calls
    # An error that is not another's lock is raised at once.
    fake, calls = fake_msvcrt(refusals=1, error=errno.EBADF)
    try:
        with installer.held(lock, fake):
            raise AssertionError('locked')
    except OSError as failure:
        assert failure.errno == errno.EBADF, failure
    assert calls == [(1, 1, 0)], calls


def test_fcntl_locks_the_whole_file(scratch: Path) -> None:
    calls: list[int] = []
    fake = types.SimpleNamespace(LOCK_EX=2, flock=lambda fd, operation: calls.append(operation))
    with installer.held(scratch / 'lock', fake):
        assert calls == [2], calls
    assert calls == [2], calls
    assert installer.primitive() is sys.modules['fcntl'], installer.primitive()


# Imports the installer where there is no fcntl, as on Windows. subprocess and pathlib import
# fcntl on POSIX and not on Windows, so they are imported first; then fcntl is hidden, and msvcrt
# is the stand-in that FAKE_MSVCRT names, or is missing too.
WITHOUT_FCNTL = """
import pathlib, subprocess, sys, types
sys.modules['fcntl'] = None
if sys.argv[1] == 'msvcrt':
    fake = types.ModuleType('msvcrt')
    fake.LK_LOCK, fake.LK_UNLCK, fake.locking = 1, 0, lambda fd, mode, nbytes: None
    sys.modules['msvcrt'] = fake
else:
    sys.modules['msvcrt'] = None
sys.path.insert(0, sys.argv[2])
import install
if sys.argv[1] == 'msvcrt':
    assert install.primitive() is fake, install.primitive()
    print('msvcrt chosen')
else:
    sys.exit(install.main([sys.argv[3]]))
"""


def test_imported_without_fcntl(scratch: Path) -> None:
    here = str(SCRIPT.parent)
    result = subprocess.run([sys.executable, '-c', WITHOUT_FCNTL, 'msvcrt', here], text=True,
                            capture_output=True, check=False, timeout=60)
    assert result.returncode == 0 and 'msvcrt chosen' in result.stdout, result
    directory = project(scratch)
    result = subprocess.run([sys.executable, '-c', WITHOUT_FCNTL, 'none', here, str(directory)],
                            env=environment(scratch), text=True, capture_output=True, check=False,
                            timeout=60)
    assert result.returncode == 1, result
    assert 'fcntl' in result.stderr and 'msvcrt' in result.stderr, result.stderr
    assert runs(scratch) == 0, runs(scratch)


CASES: list[Case] = [
    test_installed_once_and_linked,
    test_installs_at_once_run_npm_once,
    test_a_changed_lockfile_keeps_the_previous_generation,
    test_what_a_killed_install_left_is_pruned,
    test_a_killed_link_is_left_where_git_ignores_it,
    test_a_node_modules_of_npm_gives_way_to_the_link,
    test_a_failed_install_keeps_the_link,
    test_an_npm_not_on_path_is_named,
    test_a_directory_it_cannot_write_is_named,
    test_msvcrt_is_retried_until_the_lock_is_had,
    test_fcntl_locks_the_whole_file,
    test_imported_without_fcntl,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'install_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='node install ') as scratch:
            case(Path(scratch))
        print(f'{case.__name__}: ok')
    print('install_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
