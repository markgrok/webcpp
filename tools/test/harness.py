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

import contextlib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Hashable, Mapping, Sequence
from pathlib import Path
from typing import TypeVar

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tools/test/fixtures'

# A shell with any of these (Homebrew sets CPATH) puts its headers before the configured Boost.
COMPILER_PATHS = ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH')

# Left out of a copy at its top: the repository, the machine-local tools and the real libraries;
# what git ignores there is left out too (ignored_by_git).
TOP_IGNORED = {'.git', '.local', 'libs'}

# Left out of a copy at any depth: what a build or a run writes.
IGNORED = {'bin', 'node_modules', '.node-modules', '__pycache__', '.DS_Store'}

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


def b2_environment(env_extra: Mapping[str, str | None] | None = None) -> dict[str, str]:
    """The environment every b2 of the harness runs in: this process's, without CPATH and its kin,
    with env_extra's variables added, a value of None removing its variable instead."""
    env = {name: value for name, value in os.environ.items() if name not in COMPILER_PATHS}
    for name, value in (env_extra or {}).items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return env


def start_b2(root: Path, *args: str, env_extra: Mapping[str, str | None] | None = None,
             stdin: int | None = None) -> subprocess.Popen:
    """b2 started in root, in the environment of b2_environment(env_extra), in a session of its
    own, without waiting; what it prints, stdout and stderr together, is read from its stdout, a
    byte that is not UTF-8, which b2 passes on from a test's output, as U+FFFD. stdin is b2's
    standard input, a file descriptor, else this process's own."""
    return subprocess.Popen(['b2', f'--user-config={user_config(root)}', *args], cwd=root,
                            env=b2_environment(env_extra), stdin=stdin, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors='replace',
                            start_new_session=True)


def run_b2(root: Path, *args: str, env_extra: Mapping[str, str | None] | None = None,
           stdin: int | None = None, timeout: float = TIMEOUT) -> subprocess.CompletedProcess:
    """Runs b2 in root, started as start_b2 starts it, and returns what it printed, stdout and
    stderr together, in stdout. A run that outlasts timeout, or is interrupted, is stopped with
    stop_session, and the exception that ended it, subprocess.TimeoutExpired or
    KeyboardInterrupt, is raised again."""
    with start_b2(root, *args, env_extra=env_extra, stdin=stdin) as process:
        try:
            output, _ = process.communicate(timeout=timeout)
        except BaseException:
            stop_session(process)
            raise
    return subprocess.CompletedProcess(process.args, process.returncode, output)


# What names a lane of run_lanes: its version, its name.
Lane = TypeVar('Lane', bound=Hashable)


def run_lanes(root: Path, lanes: Mapping[Lane, Sequence[str]],
              env_extra: Mapping[str, str | None] | None = None,
              timeout: float = TIMEOUT) -> dict[Lane, subprocess.CompletedProcess]:
    """Runs one b2 per lane of lanes, {name: its arguments}, at once, and returns what each gave,
    by name, in the order they ended.

    root/bin is made first. Each b2 makes the directories of its build directory as it opens the
    log of its configuration checks, and b2 makes a directory by asking whether it is there and
    then making it (path.makedirs): two that start at once on a root without bin can both find
    it missing, and the one whose MAKEDIR comes second fails with "Could not create directory
    'bin'". A lane that fails stops the others at once, sessions and all (stop_session), so that
    none still runs, and writes into root, when the case asserts and its root is removed; each
    stopped lane ends after the one that failed. A run that outlasts timeout stops every lane
    and raises subprocess.TimeoutExpired.
    """
    (root / 'bin').mkdir(exist_ok=True)
    started = {name: start_b2(root, *arguments, env_extra=env_extra)
               for name, arguments in lanes.items()}
    ended: dict[Lane, subprocess.CompletedProcess] = {}
    failed = threading.Event()

    def collect(name: Lane, process: subprocess.Popen) -> None:
        output, _ = process.communicate()
        ended[name] = subprocess.CompletedProcess(process.args, process.returncode, output)
        if process.returncode != 0:
            failed.set()

    threads = [threading.Thread(target=collect, args=item, daemon=True)
               for item in started.items()]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    try:
        while any(thread.is_alive() for thread in threads):
            if failed.wait(0.1):
                break
            if time.monotonic() > deadline:
                raise subprocess.TimeoutExpired([str(lane) for lane in lanes], timeout)
    finally:
        for process in started.values():
            if process.poll() is None:
                stop_session(process)
        for thread in threads:
            thread.join()
    return ended


def stop_session(process: subprocess.Popen) -> None:
    """Kills process, the leader of a session of its own, and every process of its session, then
    reaps it.

    b2 gives each action a process group of its own, so its group alone holds none of them: the
    session is what holds them all. b2 is stopped first, so that it starts nothing more; then
    every process whose session is b2's is killed, pass after pass, until a pass finds none it
    has not killed already, which catches what an action started between two passes. A process
    that is gone, or that refuses the signal (macOS answers EPERM for a zombie), is left alone:
    nothing here raises an OSError over the exception that ended the run.
    """
    with contextlib.suppress(OSError):
        os.kill(process.pid, signal.SIGSTOP)
    killed: set[int] = set()
    while True:
        listed = subprocess.run(['ps', '-A', '-o', 'pid='], capture_output=True, text=True,
                                check=False)
        found = set()
        for word in listed.stdout.split():
            with contextlib.suppress(OSError):
                if os.getsid(int(word)) == process.pid:
                    found.add(int(word))
        if not found - killed:
            break
        for pid in found - killed:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
        killed |= found
    with contextlib.suppress(OSError):
        os.kill(process.pid, signal.SIGKILL)
    process.wait()


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


def link_wasi_tools(root: Path) -> None:
    """Gives the scratch superproject root, in its .local, the wit-bindgen and the WASI WIT that a
    copy leaves out: links to $WIT_BINDGEN_ROOT, the directory that holds wit-bindgen, else this
    checkout's .local/wit-bindgen, and to $WASI_WIT_ROOT, the directory that holds p2 and p3,
    else this checkout's .local/wasi-wit."""
    for variable, name, inside in (('WIT_BINDGEN_ROOT', 'wit-bindgen', ('wit-bindgen',)),
                                   ('WASI_WIT_ROOT', 'wasi-wit', ('p2', 'p3'))):
        configured = os.environ.get(variable)
        source = Path(configured) if configured else ROOT / '.local' / name
        missing = [entry for entry in inside if not (source / entry).exists()]
        if missing:
            raise RuntimeError(f'no {", ".join(missing)} in {source}: install it there, or set '
                               f'{variable}')
        (root / '.local').mkdir(exist_ok=True)
        (root / '.local' / name).symlink_to(source.resolve())


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
