#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/node/install.py with a stand-in for npm, first on PATH, which writes a package into
node_modules after a moment and counts its runs: the packages are installed once per lockfile and
linked at node_modules, and a second run installs nothing; installs at once run npm once and all
succeed; an install of a lockfile that changed is pruned, and so is the directory a killed npm ci
left; a node_modules that npm ci made in the directory itself gives way to the link; and a failed
npm ci fails the run, naming it, and leaves the link as it was. Run with the names of some cases to
run only those."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

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
    """What .node-modules holds, but its lock."""
    return sorted(name for name in os.listdir(directory / '.node-modules') if name != '.lock')


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


def test_a_changed_lockfile_prunes_the_old_install(scratch: Path) -> None:
    directory = project(scratch)
    env = environment(scratch)
    assert install(directory, env).returncode == 0
    first = installs(directory)
    project(scratch, lock='two')
    assert install(directory, env).returncode == 0
    assert linked(directory) == '{"lock": "two"}\n'
    second = installs(directory)
    assert len(second) == 1 and second != first, (first, second)


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
    assert install(directory, env).returncode == 0
    assert installs(directory) == current, installs(directory)
    assert runs(scratch) == 1, runs(scratch)


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


CASES: list[Case] = [
    test_installed_once_and_linked,
    test_installs_at_once_run_npm_once,
    test_a_changed_lockfile_prunes_the_old_install,
    test_what_a_killed_install_left_is_pruned,
    test_a_node_modules_of_npm_gives_way_to_the_link,
    test_a_failed_install_keeps_the_link,
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
