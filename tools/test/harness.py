# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Runs b2 on scratch copies of the superproject, for the tests of the build itself.

A scratch superproject is the superproject's own files, without what is local, built or a
library, plus the fixture libraries a test places under its libs/. It lives under $TMPDIR in a
directory whose name contains a space, so every test also proves that such a checkout builds.
run_cases runs a test file's cases, each on a scratch superproject of its own.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tools/test/fixtures'

# A shell with any of these (Homebrew sets CPATH) puts its headers before the configured Boost.
COMPILER_PATHS = ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH')

# Left out of a copy at its top: the repository, the machine-local tools and the real libraries;
# what git ignores there is left out too (ignored_by_git).
TOP_IGNORED = {'.git', '.local', 'libs'}

# Left out of a copy at any depth: what a build or a run writes.
IGNORED = {'bin', 'node_modules', '__pycache__', '.DS_Store'}

TIMEOUT = 900


def user_config(root: Path) -> Path:
    """Returns the user-config.jam b2 reads for root: root/.local's, else $WEBCPP_USER_CONFIG's.

    A relative $WEBCPP_USER_CONFIG is resolved here, since b2 runs in root.
    """
    local = root / '.local/user-config.jam'
    if local.is_file():
        return local
    configured = os.environ.get('WEBCPP_USER_CONFIG')
    if configured:
        return Path(configured).resolve()
    raise RuntimeError(f'no user-config.jam: {local} does not exist, '
                       'and WEBCPP_USER_CONFIG is not set')


def run_b2(root: Path, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Runs b2 in root and returns what it printed, stdout and stderr together, in stdout.

    env_extra adds variables to b2's environment after CPATH and its kin are removed; a value
    of None removes that variable instead. A byte that is not UTF-8, which b2 passes on from a
    test's output, is read as U+FFFD.
    """
    env = {name: value for name, value in os.environ.items() if name not in COMPILER_PATHS}
    for name, value in (env_extra or {}).items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    command = ['b2', f'--user-config={user_config(root)}', *args]
    return subprocess.run(command, cwd=root, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, errors='replace', check=False,
                          timeout=TIMEOUT)


def built(_: str, names: list[str]) -> set[str]:
    """The names a copy leaves out of any directory: what a build or a run wrote."""
    return {name for name in names if name in IGNORED}


def ignored_by_git(top: Path, names: list[str]) -> set[str]:
    """The names of top that git ignores, by a .gitignore or by the checkout's own excludes, so that
    what one machine keeps there stays out of a copy; none when top is not a git checkout."""
    result = subprocess.run(['git', '-C', str(top), 'check-ignore', '-z', '--stdin'],
                            input='\0'.join(names), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return set()
    return {name for name in result.stdout.split('\0') if name}


def copy_tree(src: Path) -> Path:
    """Copies src to a new directory under $TMPDIR whose path contains a space, and returns it.

    Only src's user-config.jam comes from its .local/, so that the copy builds with the same
    toolsets without copying the toolchains themselves.
    """
    top = src.resolve()

    def left_out(directory: str, names: list[str]) -> set[str]:
        if Path(directory) != top:
            return built(directory, names)
        return (built(directory, names) | {name for name in names if name in TOP_IGNORED}
                | ignored_by_git(top, names))

    scratch = Path(tempfile.mkdtemp(prefix='webcpp scratch '))
    shutil.copytree(top, scratch, ignore=left_out, symlinks=True, dirs_exist_ok=True)
    config = top / '.local/user-config.jam'
    if config.is_file():
        (scratch / '.local').mkdir()
        shutil.copy2(config, scratch / '.local/user-config.jam')
    return scratch


def scratch_superproject(*fixtures: str) -> Path:
    """Returns a scratch copy of the superproject with each named fixture library in its libs/."""
    root = copy_tree(ROOT)
    for name in fixtures:
        shutil.copytree(FIXTURES / name, root / 'libs' / name, ignore=built)
    return root


# A line of a user-config.jam that configures Boost.
USING_BOOST = re.compile(r'^\s*using\s+boost\b.*$', re.MULTILINE)


def expect(result: subprocess.CompletedProcess, succeeded: bool, *texts: str) -> None:
    """Asserts that b2 succeeded or failed as expected and printed each text."""
    output = result.stdout
    assert (result.returncode == 0) == succeeded, (succeeded, result.returncode, output[-4000:])
    for text in texts:
        assert text in output, (text, output[-4000:])


def without_boost() -> str:
    """The user-config of the superproject without its `using boost` line."""
    return USING_BOOST.sub('', user_config(ROOT).read_text())


def configure(root: Path, text: str) -> None:
    """Makes text the user-config.jam of the scratch superproject root."""
    (root / '.local').mkdir(exist_ok=True)
    (root / '.local/user-config.jam').write_text(text)


def replace(path: Path, old: str, new: str) -> None:
    """Replaces the one occurrence of old in the file at path with new."""
    text = path.read_text()
    assert text.count(old) == 1, (path, old)
    path.write_text(text.replace(old, new))


def add_library(root: Path, name: str, jamfile: str, sources: dict[str, str]) -> None:
    """Adds to the scratch superproject root a library whose test/ holds jamfile and sources."""
    (root / 'libs' / name / 'test').mkdir(parents=True)
    (root / 'libs' / name / 'build.jam').write_text(f'project /webcpp/{name} ;\n')
    (root / 'libs' / name / 'test/Jamfile').write_text(jamfile)
    for source, text in sources.items():
        (root / 'libs' / name / 'test' / source).write_text(text)


def run_cases(label: str, cases: Sequence[Callable[[Path], None]], argv: Sequence[str],
              fixtures: Sequence[str] = ('demo',)) -> int:
    """Runs each of cases, or only those argv names, and returns the exit status of the run.

    Each case receives a scratch superproject of its own, with the fixture libraries named in
    fixtures (demo, unless the test names others), which is removed after it. The run prints
    "<case>: ok" after each case and "<label>: ok" at its end; a case that fails raises, which
    ends the run there. A name in argv that is no case's makes it print the unknown names and
    return 2 before any case runs.
    """
    unknown = set(argv) - {case.__name__ for case in cases}
    if unknown:
        print(f'{label}: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in cases:
        if argv and case.__name__ not in argv:
            continue
        root = scratch_superproject(*fixtures)
        try:
            case(root)
        finally:
            shutil.rmtree(root)
        print(f'{case.__name__}: ok')
    print(f'{label}: ok')
    return 0
