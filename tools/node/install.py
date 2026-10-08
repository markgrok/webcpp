#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Installs the Node packages a directory's package-lock.json pins, so that any number of runs at
once, in one b2 run or in several, use them safely: the documentation's (tools/doc), an oracle's
(beside its Jamfile) and the lint's (tools/lint).

Usage: install.py <directory>

The packages are installed once per lockfile, never over an install in use. `npm ci` deletes
node_modules before it installs, so two at once in one directory fail (ENOTEMPTY), and a reader
of the packages loses them while the other installs: this is why it never runs in <directory>
itself. It runs in a temporary directory under <directory>/.node-modules/, which is renamed,
whole and at once, to .node-modules/<digest>, the digest of package.json and package-lock.json.
<directory>/node_modules is then a link to .node-modules/<digest>/node_modules, which Node finds
as it finds any node_modules beside a script, made under another name and renamed over the old
link, so that a reader sees the old install or the new one, never none. A run whose install is
there already only checks the link, so `b2 -a` reinstalls nothing.

The whole run holds an exclusive lock on .node-modules/.lock (fcntl.flock, which the system
releases when the process ends, however it ends): runs at once wait for one another, and the
second finds the install the first made. Once the link names the current install, everything
else under .node-modules/ goes, the lock aside: the install of a lockfile that has changed since,
the temporary directory of an npm ci that was killed, a node_modules that npm ci made in
<directory> itself before, each renamed aside first, so that a prune killed half-way leaves a
name the next run prunes again, and then removed.

Exit 0 when the link names the install; 1 when npm ci fails, with its output, the link left as
it was; 2 on a usage error.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

INSTALLS = '.node-modules'
LOCK = '.lock'
# What a prune renames a directory to before it removes it.
REMOVED = '.removed.'


def digest(directory: Path) -> str:
    """What names the install of directory's packages: its package.json and package-lock.json."""
    hashed = hashlib.sha256()
    for name in ('package.json', 'package-lock.json'):
        hashed.update((directory / name).read_bytes())
    return hashed.hexdigest()[:16]


def installed(directory: Path, name: str) -> Path:
    """The install name under directory, made by npm ci unless it is there."""
    done = directory / INSTALLS / name
    if (done / 'node_modules').is_dir():
        return done
    work = Path(tempfile.mkdtemp(prefix=f'{name}.', dir=directory / INSTALLS))
    try:
        for file in ('package.json', 'package-lock.json'):
            shutil.copy2(directory / file, work / file)
        npm = subprocess.run(['npm', 'ci', '--no-audit', '--no-fund', '--prefer-offline',
                              '--loglevel=error'], cwd=work, capture_output=True, text=True,
                             check=False)
        if npm.returncode != 0:
            raise RuntimeError(f'npm ci failed in {directory}:\n{npm.stdout}{npm.stderr}')
        # A lockfile with no package still has an install, empty.
        (work / 'node_modules').mkdir(exist_ok=True)
        work.rename(done)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return done


def removed(path: Path) -> None:
    """Renames path aside under its parent, then removes it."""
    aside = path.parent / f'{REMOVED}{os.getpid()}.{path.name.lstrip(".")}'
    try:
        path.rename(aside)
    except FileNotFoundError:
        return
    shutil.rmtree(aside, ignore_errors=True)


def linked(directory: Path, done: Path) -> None:
    """Makes directory/node_modules a link to done's node_modules, replacing what is there at
    once."""
    link = directory / 'node_modules'
    target = Path(INSTALLS) / done.name / 'node_modules'
    if link.is_symlink() and Path(os.readlink(link)) == target:
        return
    if link.is_dir() and not link.is_symlink():
        # A node_modules that npm ci made in the directory itself: moved under .node-modules/,
        # which the prune empties.
        link.rename(directory / INSTALLS / f'{REMOVED}{os.getpid()}.node_modules')
    temporary = directory / f'node_modules.{os.getpid()}'
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, link)


def pruned(directory: Path, done: Path) -> None:
    """Removes everything under .node-modules but the current install and the lock."""
    for entry in sorted((directory / INSTALLS).iterdir()):
        if entry.name not in (done.name, LOCK):
            removed(entry)


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not (Path(argv[0]) / 'package-lock.json').is_file():
        print('usage: install.py <directory that holds package.json and package-lock.json>',
              file=sys.stderr)
        return 2
    directory = Path(argv[0]).resolve()
    (directory / INSTALLS).mkdir(exist_ok=True)
    with open(directory / INSTALLS / LOCK, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            done = installed(directory, digest(directory))
        except RuntimeError as failure:
            print(f'install.py: {failure}', file=sys.stderr)
            return 1
        linked(directory, done)
        pruned(directory, done)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
