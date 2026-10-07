# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Runs b2 on scratch copies of the superproject, for the tests of the build itself.

A scratch superproject is the superproject's own files, without what is local, built or a
library, plus the fixture libraries a test places under its libs/. It lives under $TMPDIR in a
directory whose name contains a space, so every test also proves that such a checkout builds.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tools/test/fixtures'

# A shell with any of these (Homebrew sets CPATH) puts its headers before the configured Boost.
COMPILER_PATHS = ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH')

# Left out of a copy at its top: the repository, the machine-local tools, the agents'
# workspace and the real libraries.
TOP_IGNORED = {'.git', '.local', '.superpowers', 'libs'}

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
    of None removes that variable instead.
    """
    env = {name: value for name, value in os.environ.items() if name not in COMPILER_PATHS}
    for name, value in (env_extra or {}).items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    command = ['b2', f'--user-config={user_config(root)}', *args]
    return subprocess.run(command, cwd=root, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, check=False, timeout=TIMEOUT)


def built(_: str, names: list[str]) -> set[str]:
    """The names a copy leaves out of any directory: what a build or a run wrote."""
    return {name for name in names if name in IGNORED}


def copy_tree(src: Path) -> Path:
    """Copies src to a new directory under $TMPDIR whose path contains a space, and returns it.

    Only src's user-config.jam comes from its .local/, so that the copy builds with the same
    toolsets without copying the toolchains themselves.
    """
    top = src.resolve()

    def left_out(directory: str, names: list[str]) -> set[str]:
        if Path(directory) != top:
            return built(directory, names)
        return built(directory, names) | {name for name in names if name in TOP_IGNORED}

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
