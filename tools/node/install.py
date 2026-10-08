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
as it finds any node_modules beside a script, made under another name in .node-modules/ and
renamed over the old link, so that a reader sees the old install or the new one, never none. A
run whose install is there already only checks the link, so `b2 -a` reinstalls nothing.

The whole run holds an exclusive lock on .node-modules/.lock, which the system releases when the
process ends, however it ends: runs at once wait for one another, and the second finds the
install the first made. Once the link names the current install, everything else under
.node-modules/ goes but the lock and two installs: the current one, and the previous one, which
the link named before it last changed and which .node-modules/.previous names. A build that
resolved node_modules before its lockfile changed may still be reading the previous install, so
that install stays for one generation more and goes when the link changes again. What goes is
the install of an older lockfile, the temporary directory of an npm ci that was killed, and a
node_modules that npm ci made in <directory> itself before, each renamed aside first, so that a
prune killed half-way leaves a name the next run prunes again, and then removed, read-only
entries and all; and the link of a run killed before it renamed it.

On Windows, the lock is msvcrt's rather than fcntl's, retried for as long as another run holds
it, since msvcrt gives up after about ten seconds. The link is a directory symbolic link, or a
junction where making one needs a privilege the user lacks; and since Windows renames no link to
a directory over another, the old link is removed just before the new one takes its name, so a
reader may find none for that moment. An entry that Windows will not move or remove, because a
process has a file open in it, is named on stderr and left for a later run. These Windows paths
are checked with stand-ins for msvcrt only, never on Windows itself.

Exit 0 when the link names the install; 1, naming the cause, when npm ci fails, with its output,
the link left as it was, when npm, a lock or a link cannot be had, or when the system refuses to
make, move or remove a file or a directory (permissions, a full disk); 2 on a usage error.
"""

from __future__ import annotations

import errno
import hashlib
import importlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

INSTALLS = '.node-modules'
LOCK = '.lock'
# The file that names the previous install, which a running build may still read.
PREVIOUS = '.previous'
# What a prune renames a directory to before it removes it.
REMOVED = '.removed.'
# What the link is made as under .node-modules/, with its run's pid, before it is renamed to
# node_modules: a run killed in between leaves it where git ignores it wherever packages are
# installed, never beside node_modules, where git would list it, and the prune removes it.
LINKING = '.linking.'
# What msvcrt.locking(LK_LOCK) raises when another still holds the lock after its ten tries:
# EDEADLOCK, which is EDEADLK where both exist.
WAITED = {errno.EDEADLK, getattr(errno, 'EDEADLOCK', errno.EDEADLK)}


@runtime_checkable
class Flock(Protocol):
    """fcntl's lock, POSIX's: flock waits until it has the lock, which closing the file
    releases."""

    LOCK_EX: int

    def flock(self, fd: int, operation: int, /) -> None: ...


@runtime_checkable
class Locking(Protocol):
    """msvcrt's lock, Windows': locking locks bytes from the file's position, and LK_LOCK gives up
    after about ten seconds."""

    LK_LOCK: int
    LK_UNLCK: int

    def locking(self, fd: int, mode: int, nbytes: int, /) -> None: ...


def primitive() -> object:
    """The module whose lock this system has: fcntl on POSIX, msvcrt on Windows."""
    for name in ('fcntl', 'msvcrt'):
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    raise RuntimeError('neither fcntl (POSIX) nor msvcrt (Windows) can be imported, and without '
                       'a lock runs at once would install over each other')


def acquired(fd: int, system: Flock | Locking) -> Callable[[], None]:
    """Takes the lock on fd with system, waiting as long as another holds it; returns what
    releases it."""
    if isinstance(system, Flock):
        system.flock(fd, system.LOCK_EX)
        return lambda: None
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        try:
            system.locking(fd, system.LK_LOCK, 1)
            break
        except OSError as failure:
            if failure.errno not in WAITED:
                raise

    def released() -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        system.locking(fd, system.LK_UNLCK, 1)

    return released


@contextmanager
def held(path: Path, system: object) -> Generator[None, None, None]:
    """Holds an exclusive lock on the file path, made if need be, with system, a module such as
    primitive() returns."""
    if not isinstance(system, (Flock, Locking)):
        raise RuntimeError(f'{system!r} has neither flock nor locking')
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    try:
        released = acquired(fd, system)
        try:
            yield
        finally:
            released()
    finally:
        os.close(fd)


def is_link(path: Path) -> bool:
    """Whether path is a symbolic link or, on Windows, a junction: what is removed as a link, never
    emptied as a directory."""
    try:
        status = os.lstat(path)
    except FileNotFoundError:
        return False
    reparse = getattr(status, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    return stat.S_ISLNK(status.st_mode) or bool(reparse)


def unlinked(path: Path) -> None:
    """Removes the link path, which names a directory, and not what it names."""
    if sys.platform == 'win32':
        os.rmdir(path)
    else:
        path.unlink()


def made_link(link: Path, target: Path, home: Path) -> None:
    """Makes link a link to the directory target, relative to home, the directory the link is
    then renamed into: a symbolic link or, on Windows, where one may need Developer Mode or an
    administrator, a junction."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError as refused:
        if sys.platform != 'win32':
            raise
        import _winapi
        try:
            # A junction's target is absolute.
            _winapi.CreateJunction(str(home / target), str(link))
        except OSError as failed:
            raise RuntimeError(f'cannot link {link} to {target}: Windows refused a symbolic link '
                               f'({refused}) and a junction ({failed})') from failed


def deleted(path: Path) -> None:
    """Removes the file or the directory tree path, making writable what refuses to go: npm may
    leave a file read-only, which Windows does not remove, or a directory, which no system
    empties."""
    if is_link(path):
        unlinked(path)
        return
    if not path.is_dir():
        path.unlink()
        return

    def writable(function: Callable[..., Any], name: str, failure: BaseException) -> None:
        if function not in (os.unlink, os.remove, os.rmdir):
            raise failure
        parent = os.path.dirname(name)
        os.chmod(parent, os.stat(parent).st_mode | stat.S_IRWXU)
        if not is_link(Path(name)):
            os.chmod(name, os.lstat(name).st_mode | stat.S_IRWXU)
        function(name)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=writable)
    else:
        shutil.rmtree(path, onerror=lambda function, name, info: writable(function, name, info[1]))


def removed(path: Path) -> None:
    """Renames path aside under its parent, then removes it; what the system refuses to move or to
    remove is named and left for a later run."""
    aside = path.parent / f'{REMOVED}{os.getpid()}.{path.name.lstrip(".")}'
    try:
        path.rename(aside)
    except FileNotFoundError:
        return
    except OSError as refused:
        print(f'install.py: {path} is left for a later run: {refused}', file=sys.stderr)
        return
    try:
        deleted(aside)
    except OSError as refused:
        print(f'install.py: {aside} is left for a later run: {refused}', file=sys.stderr)


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
    # On Windows npm is npm.cmd, which only a search of PATH with PATHEXT finds.
    npm = shutil.which('npm')
    if npm is None:
        raise RuntimeError(f'npm is not on PATH, so the packages of {directory} cannot be '
                           'installed')
    if os.path.lexists(done):
        # An install that lost its node_modules, made again.
        removed(done)
    work = Path(tempfile.mkdtemp(prefix=f'{name}.', dir=directory / INSTALLS))
    try:
        for file in ('package.json', 'package-lock.json'):
            shutil.copy2(directory / file, work / file)
        ran = subprocess.run([npm, 'ci', '--no-audit', '--no-fund', '--prefer-offline',
                              '--loglevel=error'], cwd=work, capture_output=True, text=True,
                             check=False)
        if ran.returncode != 0:
            raise RuntimeError(f'npm ci failed in {directory}:\n{ran.stdout}{ran.stderr}')
        # A lockfile with no package still has an install, empty.
        (work / 'node_modules').mkdir(exist_ok=True)
        work.rename(done)
    finally:
        removed(work)
    return done


def pointed(directory: Path) -> str | None:
    """The install that directory/node_modules links to, if it is a link to one."""
    link = directory / 'node_modules'
    if not is_link(link):
        return None
    target = Path(os.path.realpath(link))
    if target.name != 'node_modules':
        return None
    if target.parent.parent != Path(os.path.realpath(directory / INSTALLS)):
        return None
    return target.parent.name


def linked(directory: Path, done: Path) -> None:
    """Makes directory/node_modules a link to done's node_modules, replacing what is there at
    once."""
    if pointed(directory) == done.name:
        return
    link = directory / 'node_modules'
    if link.is_dir() and not is_link(link):
        # A node_modules that npm ci made in the directory itself: moved under .node-modules/,
        # which the prune empties.
        link.rename(directory / INSTALLS / f'{REMOVED}{os.getpid()}.node_modules')
    temporary = directory / INSTALLS / f'{LINKING}{os.getpid()}'
    if is_link(temporary):
        unlinked(temporary)
    made_link(temporary, Path(INSTALLS) / done.name / 'node_modules', directory)
    if sys.platform == 'win32':
        # Windows renames no link to a directory over another.
        if is_link(link):
            unlinked(link)
        os.rename(temporary, link)
    else:
        os.replace(temporary, link)


def previous(directory: Path) -> str:
    """The install the link named before the current one, or nothing."""
    try:
        return (directory / INSTALLS / PREVIOUS).read_text().strip()
    except FileNotFoundError:
        return ''


def remembered(directory: Path, name: str) -> None:
    """Records name as the previous install, at once."""
    temporary = directory / INSTALLS / f'{PREVIOUS}.{os.getpid()}'
    temporary.write_text(f'{name}\n')
    os.replace(temporary, directory / INSTALLS / PREVIOUS)


def pruned(directory: Path, done: Path) -> None:
    """Removes everything under .node-modules but the lock, the current install and the previous
    one: the links that killed runs left there among the rest."""
    kept = {LOCK, PREVIOUS, done.name, previous(directory)}
    for entry in sorted((directory / INSTALLS).iterdir()):
        if entry.name not in kept:
            removed(entry)


def updated(directory: Path) -> None:
    """Installs directory's packages unless they are, links them, and prunes what no run uses."""
    before = pointed(directory)
    done = installed(directory, digest(directory))
    if before is not None and before != done.name:
        # Recorded before the link changes, so that a run killed in between loses no install.
        remembered(directory, before)
    linked(directory, done)
    pruned(directory, done)


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not (Path(argv[0]) / 'package-lock.json').is_file():
        print('usage: install.py <directory that holds package.json and package-lock.json>',
              file=sys.stderr)
        return 2
    directory = Path(argv[0]).resolve()
    try:
        (directory / INSTALLS).mkdir(exist_ok=True)
        with held(directory / INSTALLS / LOCK, primitive()):
            updated(directory)
    except RuntimeError as failure:
        print(f'install.py: {failure}', file=sys.stderr)
        return 1
    except OSError as refused:
        # Permissions, a full disk: the system's own words, and the paths it names.
        paths = ' and '.join(str(path) for path in (refused.filename, refused.filename2)
                             if path is not None)
        print(f'install.py: {refused.strerror or refused}{f": {paths}" if paths else ""}',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
