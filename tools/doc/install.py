#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Installs the packages a directory's package-lock.json pins, so that any number of doc builds
at once, in one b2 run or in several, use them safely.

Usage: install.py <directory>

The packages are installed once per lockfile, never over an install in use: `npm ci` runs in a
directory of its own under <directory>/.node-modules/, which is renamed, whole and at once, to
.node-modules/<digest>, the digest of package.json and package-lock.json. Two runs that install
at the same time each install into their own directory, and the one that renames second throws
its copy away. <directory>/node_modules is then a link to .node-modules/<digest>/node_modules,
which Node finds as it finds any node_modules beside a script, made under another name and
renamed over the old link, so that a reader sees the old install or the new one, never none. A
run whose install is there already only checks the link, so `b2 -a` reinstalls nothing.

`npm ci` deletes node_modules before it installs, and two at once in one directory fail
(ENOTEMPTY), as does a page converted while the other deletes what it reads: this is why it
never runs in <directory> itself. An install of a lockfile that has changed since stays under
.node-modules/, unused, until removed by hand; node_modules made by `npm ci` in <directory>
before is moved there too and removed.

Exit 0 when the link names the install; 1 when npm ci fails, with its output; 2 on a usage
error.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

INSTALLS = '.node-modules'


def digest(directory: Path) -> str:
    """What names the install of directory's packages: its package.json and package-lock.json."""
    hashed = hashlib.sha256()
    for name in ('package.json', 'package-lock.json'):
        hashed.update((directory / name).read_bytes())
    return hashed.hexdigest()[:16]


def installed(directory: Path, name: str) -> Path:
    """The install name under directory, made by npm ci unless it is there."""
    installs = directory / INSTALLS
    done = installs / name
    if (done / 'node_modules').is_dir():
        return done
    installs.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f'{name}.', dir=installs))
    try:
        for file in ('package.json', 'package-lock.json'):
            shutil.copy2(directory / file, work / file)
        npm = subprocess.run(['npm', 'ci', '--no-audit', '--no-fund', '--prefer-offline',
                              '--loglevel=error'], cwd=work, capture_output=True, text=True,
                             check=False)
        if npm.returncode != 0:
            raise RuntimeError(f'npm ci failed in {work}:\n{npm.stdout}{npm.stderr}')
        try:
            work.rename(done)
        except OSError:
            # Another run renamed its install first: it is the same lockfile's, so this copy
            # goes.
            if not (done / 'node_modules').is_dir():
                raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return done


def linked(directory: Path, done: Path) -> None:
    """Makes directory/node_modules a link to done's node_modules, replacing what is there at
    once."""
    link = directory / 'node_modules'
    target = Path(INSTALLS) / done.name / 'node_modules'
    if link.is_symlink() and Path(os.readlink(link)) == target:
        return
    if link.is_dir() and not link.is_symlink():
        # A node_modules that npm ci made in the directory itself, before installs had a
        # directory of their own.
        aside = Path(tempfile.mkdtemp(prefix='replaced.', dir=directory / INSTALLS))
        try:
            link.rename(aside / 'node_modules')
        except FileNotFoundError:
            pass
        shutil.rmtree(aside, ignore_errors=True)
    temporary = directory / f'node_modules.{os.getpid()}'
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, link)


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not (Path(argv[0]) / 'package-lock.json').is_file():
        print('usage: install.py <directory that holds package.json and package-lock.json>',
              file=sys.stderr)
        return 2
    directory = Path(argv[0]).resolve()
    try:
        linked(directory, installed(directory, digest(directory)))
    except RuntimeError as failure:
        print(f'install.py: {failure}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
