#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks the shell steps of tools/ci/actions: download.sh keeps a file only when its SHA-256 is
the pinned one, exits 1 and leaves no file when the digest differs or the download fails; and the
Boost action's install.sh refuses an empty or relative prefix before it downloads anything, since
b2 given an empty --prefix installs into /usr/local. Nothing is fetched from the network: the
downloads are file:// URLs, and install.sh runs against a download.sh that only says it was
called. Run with the names of some cases to run only those."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

CI = Path(__file__).resolve().parent
DOWNLOAD = CI / 'download.sh'
BOOST = CI / 'actions/boost/install.sh'

# What the stand-in download.sh prints, and its exit status: install.sh got past its guards.
CALLED = 'download.sh was called'
CALLED_STATUS = 99


def run(*command: str | Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(['bash', *map(str, command)], capture_output=True, text=True,
                          check=False, env={**os.environ, **(env or {})})


def source(scratch: Path) -> tuple[Path, str]:
    """A file to download, and its SHA-256."""
    path = scratch / 'archive.tar.gz'
    path.write_bytes(b'the pinned bytes\n')
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_pinned_download_is_kept(scratch: Path) -> None:
    path, digest = source(scratch)
    file = scratch / 'downloaded'
    result = run(DOWNLOAD, path.as_uri(), digest, file)
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert file.read_bytes() == path.read_bytes()
    assert f'SHA-256 {digest}' in result.stdout, result.stdout


def test_another_digest_leaves_no_file(scratch: Path) -> None:
    path, digest = source(scratch)
    file = scratch / 'downloaded'
    pinned = '0' * 64
    result = run(DOWNLOAD, path.as_uri(), pinned, file)
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert f'has SHA-256 {digest}, and {pinned} is pinned' in result.stderr, result.stderr
    assert not file.exists()


def test_a_failed_download_exits_1_and_leaves_no_file(scratch: Path) -> None:
    file = scratch / 'downloaded'
    # A file left by an earlier attempt is not taken for this one's.
    file.write_bytes(b'partial')
    result = run(DOWNLOAD, (scratch / 'missing.tar.gz').as_uri(), '0' * 64, file)
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert 'could not download' in result.stderr, result.stderr
    assert not file.exists()


def test_a_usage_error_exits_2(scratch: Path) -> None:
    result = run(DOWNLOAD, 'file:///nothing')
    assert result.returncode == 2, (result.returncode, result.stderr)
    assert 'usage: tools/ci/download.sh <url> <sha256> <file>' in result.stderr, result.stderr


def boost_tree(scratch: Path) -> Path:
    """A copy of install.sh where it lives, beside a download.sh that only says it was called."""
    action = scratch / 'tools/ci/actions/boost'
    action.mkdir(parents=True)
    shutil.copy2(BOOST, action / 'install.sh')
    stand_in = scratch / 'tools/ci/download.sh'
    stand_in.write_text(f'#!/bin/sh\necho "{CALLED}" >&2\nexit {CALLED_STATUS}\n')
    stand_in.chmod(0o755)
    return action / 'install.sh'


def test_boost_refuses_an_empty_or_relative_prefix(scratch: Path) -> None:
    script = boost_tree(scratch)
    runner = {'RUNNER_OS': 'Linux', 'RUNNER_TEMP': str(scratch / 'temp'),
              'GITHUB_PATH': str(scratch / 'path')}
    for arguments in (['install'], ['install', ''], ['install', 'relative/prefix'],
                      ['configure'], ['configure', ''], ['configure', 'relative/prefix'], [],
                      ['other']):
        result = run(script, *arguments, env=runner)
        assert result.returncode == 2, (arguments, result.returncode, result.stderr)
        assert 'usage: install.sh key | install <prefix> | configure <prefix>' in (
            result.stderr), (arguments, result.stderr)
        assert CALLED not in result.stderr, (arguments, result.stderr)
    assert not (scratch / '.local').exists()
    # An absolute prefix, a POSIX one or a Windows one with slashes, gets to the download.
    for prefix in (str(scratch / 'prefix'), 'D:/a/_temp/boost-1.92.0'):
        result = run(script, 'install', prefix, env=runner)
        assert result.returncode == CALLED_STATUS, (prefix, result.returncode, result.stderr)
        assert CALLED in result.stderr, (prefix, result.stderr)


CASES: list[Callable[[Path], None]] = [
    test_a_pinned_download_is_kept,
    test_another_digest_leaves_no_file,
    test_a_failed_download_exits_1_and_leaves_no_file,
    test_a_usage_error_exits_2,
    test_boost_refuses_an_empty_or_relative_prefix,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'actions_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='webcpp actions ') as scratch:
            case(Path(scratch))
        print(f'{case.__name__}: ok')
    print('actions_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
