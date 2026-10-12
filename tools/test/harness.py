# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Runs b2 on scratch copies of the superproject, for the tests of the build itself.

A scratch superproject is the superproject's own files, without what is local, built or a
library, plus the fixture libraries a test places under its libs/. It lives in the run's own
directory under $TMPDIR, whose name contains a space, as its own does, so every test also proves
that such a checkout builds. run_cases runs a test file's cases, each on a scratch superproject of
its own. Every b2 gets the Emscripten cache the shell names, else one of the run's own, beside its
scratch superprojects.
"""

from __future__ import annotations

import atexit
import contextlib
import functools
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
# what git ignores there is left out too (ignored_by_git). site/ is left out for the same reason
# as libs/: whether it is checked out, and what git ignores under it, is a developer's own
# machine, never a case's; a case that wants one adds its own Jamfile (matrix_test.py's
# site_jamfile, tools/site/site_test.py's own copy of the real site/).
TOP_IGNORED = {'.git', '.local', 'libs', 'site'}

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


@functools.cache
def run_directory() -> Path:
    """The directory under $TMPDIR, whose name contains a space, that holds every scratch
    superproject of this run, and Emscripten's cache: made once, and removed when the run ends."""
    directory = Path(tempfile.mkdtemp(prefix='webcpp run '))
    atexit.register(shutil.rmtree, directory, True)
    return directory


def emscripten_cache() -> Path:
    """Emscripten's cache for every b2 of this run: Emscripten writes it where EM_CACHE names,
    else inside the emsdk, which may be read-only. The one the shell's EM_CACHE names, else one of
    the run's own, beside its scratch superprojects, made once; either is made when it is not
    there yet.

    The shell's is shared with what else builds with it, as the CI's emsdk action's is, which
    holds the system libraries every lane links, built once: a test that links reads them, and
    writes only a library that is not there, as any build does. Emscripten makes that safe for
    builds at once: it builds a missing library under a lock of the cache's own, and looks again
    once it holds it. A copy of it for each run would build nothing faster than reading it.

    It is named by its resolved path: Emscripten 6.0.11 builds a system library from a relative
    path it computes from EM_CACHE as given, which misses its sources by one directory when the
    cache is reached through a link, as macOS's $TMPDIR is (/var is /private/var)."""
    shells = os.environ.get('EM_CACHE')
    cache = (Path(shells) if shells else run_directory() / 'emscripten-cache').resolve()
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def b2_environment(env_extra: Mapping[str, str | None] | None = None) -> dict[str, str]:
    """The environment every b2 of the harness runs in: this process's, without CPATH and its kin,
    and with EM_CACHE emscripten_cache(), resolved, with env_extra's variables added, a value of
    None removing its variable instead.

    EMCC_SKIP_SANITY_CHECK=1 keeps Emscripten from checking its configuration when it first meets
    the cache, which a cache of the run's own is in every run: the check prints "Running sanity
    checks" in the output of the b2 that configures the toolset, which a test compares whole (b2
    -d0 declared-targets). Its one other use, clearing a cache made by another toolchain, has
    nothing to clear in a cache of the run's own, and the CI's shared cache was checked when the
    emsdk action warmed it."""
    env = {name: value for name, value in os.environ.items() if name not in COMPILER_PATHS}
    env['EM_CACHE'] = str(emscripten_cache())
    env['EMCC_SKIP_SANITY_CHECK'] = '1'
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


def ignored_by_git(top: Path, paths: list[str]) -> set[str]:
    """Which of paths, each relative to top, git ignores there, by a .gitignore or by the
    checkout's own excludes, at any depth, so that what one machine keeps there (built, or local
    to it) stays out of a copy; none of them when top is not a git checkout."""
    result = subprocess.run(['git', '-C', str(top), 'check-ignore', '-z', '--stdin'],
                            input='\0'.join(paths), capture_output=True, text=True, check=False)
    if result.returncode not in (0, 1):
        return set()
    return {path for path in result.stdout.split('\0') if path}


def copy_tree(src: Path) -> Path:
    """Copies src to a new directory of the run's own, whose path contains a space, and returns
    it.

    The copy holds what git tracks, plus what it would track (untracked, not ignored), as the
    lint reads a repository (chapter 6): never what a build or a run wrote, nor what one
    machine's .gitignore keeps out of the tree, at any depth, so a build in src before or during
    the copy (doc/html/, bin/, and the rest .gitignore lists) cannot change what a test builds
    from. third_party/libs is a link to src's, which a case makes its own with
    third_party_of_its_own before it changes anything there. Only src's user-config.jam comes
    from its .local/, and a link to its .local/boost-source when it has one, so that the copy
    builds with the same toolsets and Boost sources without copying them.
    """
    top = src.resolve()

    def left_out(directory: str, names: list[str]) -> set[str]:
        skip = built(directory, names)
        relative = Path(directory).resolve().relative_to(top)
        if relative == Path('.'):
            skip |= {name for name in names if name in TOP_IGNORED}
        elif relative == Path('third_party'):
            skip |= {'libs'} & set(names)
        paths = {name: str(relative / name) for name in names if name not in skip}
        ignored = ignored_by_git(top, list(paths.values()))
        return skip | {name for name, path in paths.items() if path in ignored}

    scratch = Path(tempfile.mkdtemp(prefix='webcpp scratch ', dir=run_directory()))
    shutil.copytree(top, scratch, ignore=left_out, symlinks=True, dirs_exist_ok=True)
    config = top / '.local/user-config.jam'
    if config.is_file():
        (scratch / '.local').mkdir()
        shutil.copy2(config, scratch / '.local/user-config.jam')
    sources = top / '.local/boost-source'
    if sources.exists():
        (scratch / '.local').mkdir(exist_ok=True)
        (scratch / '.local/boost-source').symlink_to(sources.resolve())
    libs = top / 'third_party/libs'
    if libs.is_dir():
        (scratch / 'third_party/libs').symlink_to(libs.resolve())
    return scratch


def scratch_superproject(*fixtures: str) -> Path:
    """Returns a scratch copy of the superproject with each named fixture library in its libs/."""
    root = copy_tree(ROOT)
    for name in fixtures:
        shutil.copytree(FIXTURES / name, root / 'libs' / name, ignore=built)
    return root


def link_wasi_tools(root: Path) -> None:
    """Gives the scratch superproject root, in its .local, the wit-bindgen, the WASI WIT and the
    wasi-sdk that a copy leaves out: links to $WIT_BINDGEN_ROOT, the directory that holds
    wit-bindgen, else this checkout's .local/wit-bindgen, to $WASI_WIT_ROOT, the directory that
    holds p2 and p3, else this checkout's .local/wasi-wit, and to $WASI_SDK, else this checkout's
    .local/wasi-sdk."""
    for variable, name, inside in (('WIT_BINDGEN_ROOT', 'wit-bindgen', ('wit-bindgen',)),
                                   ('WASI_WIT_ROOT', 'wasi-wit', ('p2', 'p3')),
                                   ('WASI_SDK', 'wasi-sdk', ('bin/clang++',))):
        configured = os.environ.get(variable)
        source = Path(configured) if configured else ROOT / '.local' / name
        missing = [entry for entry in inside if not (source / entry).exists()]
        if missing:
            raise RuntimeError(f'no {", ".join(missing)} in {source}: install it there, or set '
                               f'{variable}')
        (root / '.local').mkdir(exist_ok=True)
        (root / '.local' / name).symlink_to(source.resolve())


def mrdocs_root() -> Path:
    """The directory MrDocs is installed in, which holds bin/mrdocs, for a test that links it
    into a scratch superproject's .local: $MRDOCS_ROOT, else this checkout's .local/mrdocs."""
    configured = os.environ.get('MRDOCS_ROOT')
    root = Path(configured) if configured else ROOT / '.local/mrdocs'
    if not (root / 'bin/mrdocs').is_file():
        raise RuntimeError(f'no {root}/bin/mrdocs: install MrDocs 2026.9.29 there, or set '
                           'MRDOCS_ROOT')
    return root


def link_emsdk(root: Path) -> None:
    """Gives the scratch superproject root, in its .local, the emsdk that a copy leaves out: a link
    to $EMSDK_ROOT, else to this checkout's .local/emsdk, which must hold
    upstream/emscripten/em++."""
    configured = os.environ.get('EMSDK_ROOT')
    source = Path(configured) if configured else ROOT / '.local/emsdk'
    if not (source / 'upstream/emscripten/em++').is_file():
        raise RuntimeError(f'no upstream/emscripten/em++ in {source}: install emsdk there, or set '
                           'EMSDK_ROOT')
    (root / '.local').mkdir(exist_ok=True)
    (root / '.local/emsdk').symlink_to(source.resolve())


def third_party_of_its_own(root: Path, name: str, checked_out: bool = True) -> Path:
    """Gives the scratch superproject root a third_party/libs/<name> of its own, which a case may
    change: the link to the checkout's third_party/libs becomes a directory of links, one per
    entry, and <name> a copy of the checkout's, or, unless checked_out, an empty directory, as a
    clone without that submodule has it. Returns it.

    The copy leaves out the submodule's .git, whose gitdir would name the checkout's repository,
    and what a copy leaves out at any depth (built), the suite's bin/ among it."""
    libs = root / 'third_party/libs'
    if libs.is_symlink():
        source = libs.resolve()
        libs.unlink()
        libs.mkdir()
        for entry in source.iterdir():
            (libs / entry.name).symlink_to(entry)
    own = libs / name
    source = own.resolve()
    own.unlink()

    def left_out(directory: str, names: list[str]) -> set[str]:
        return built(directory, names) | ({'.git'} & set(names))

    if checked_out:
        shutil.copytree(source, own, ignore=left_out)
    else:
        own.mkdir()
    return own


# A line of a user-config.jam that configures Boost.
USING_BOOST = re.compile(r'^\s*using\s+boost\b.*$', re.MULTILINE)

# The statement of a user-config.jam that configures the emscripten toolset, over its lines.
USING_EMSCRIPTEN = re.compile(r'^\s*using\s+emscripten\b.*?;\n', re.MULTILINE | re.DOTALL)


def expect(result: subprocess.CompletedProcess, succeeded: bool, *texts: str) -> None:
    """Asserts that b2 succeeded or failed as expected and printed each text."""
    output = result.stdout
    assert (result.returncode == 0) == succeeded, (succeeded, result.returncode, output[-4000:])
    for text in texts:
        assert text in output, (text, output[-4000:])


def without_boost() -> str:
    """The user-config of the superproject without its `using boost` line."""
    return USING_BOOST.sub('', user_config(ROOT).read_text())


def without_emscripten(root: Path) -> None:
    """Configures no emscripten toolset in the user-config.jam of the scratch superproject root,
    as on a machine without Emscripten and Node: b2 runs the node of that toolset as it configures
    it, in every run, as the CI's wrapper of .local/emscripten/node runs the node on PATH."""
    text = user_config(root).read_text()
    configure(root, USING_EMSCRIPTEN.sub('', text))
    assert not USING_EMSCRIPTEN.search(user_config(root).read_text()), user_config(root)


# A line of a user-config.jam that names Boost's sources.
POKE_BOOST_SOURCE = re.compile(r'^\s*modules\.poke\s*:\s*BOOST_SOURCE\s*:\s*"?([^";]+?)"?\s*;\s*$',
                               re.MULTILINE)


def boost_source() -> Path:
    """The tree of Boost's sources this checkout builds with: the one its user-config.jam names,
    else its .local/boost-source."""
    found = POKE_BOOST_SOURCE.search(user_config(ROOT).read_text())
    return Path(found.group(1)) if found else (ROOT / '.local/boost-source').resolve()


# A line of a user-config.jam that configures gcc, and the version it names.
USING_GCC = re.compile(r'^\s*using\s+gcc\s*(?::\s*([^\s:;]+))?', re.MULTILINE)


def gcc_request(root: Path) -> tuple[str, ...]:
    """The b2 request of the gcc that root's user-config.jam configures, toolset=gcc-<version>,
    or nothing when it configures none, as the CI's tools job, which registers clang alone."""
    found = USING_GCC.search(user_config(root).read_text())
    if not found:
        return ()
    return (f'toolset=gcc-{found.group(1)}',) if found.group(1) else ('toolset=gcc',)


def without_boost_source(root: Path) -> None:
    """Leaves the scratch superproject root without Boost's sources: its user-config.jam, the one
    b2 reads for it, names none, and its .local holds no boost-source."""
    configure(root, POKE_BOOST_SOURCE.sub('', user_config(root).read_text()))
    link = root / '.local/boost-source'
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        shutil.rmtree(link)


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


def select_cases(names: Sequence[str], argv: Sequence[str]) -> tuple[list[str], str]:
    """The names of the cases a run takes from argv, in order, and an empty string; or an empty
    list and what is wrong with argv.

    argv holds case names, which keep only those, and `--shard K/N`, which keeps the K-th of N
    interleaved slices of the cases: the case at index i is in shard i % N + 1, as tools/lint's
    shards slice their files. The N shards of a suite together run each of its cases once.
    """
    args = list(argv)
    k, n = 1, 1
    if '--shard' in args:
        at = args.index('--shard')
        value = args[at + 1] if at + 1 < len(args) else ''
        shard = re.fullmatch(r'([1-9][0-9]*)/([1-9][0-9]*)', value)
        if not shard or int(shard.group(1)) > int(shard.group(2)):
            return [], f'--shard takes K/N with 1 <= K <= N, not {value!r}'
        k, n = int(shard.group(1)), int(shard.group(2))
        del args[at:at + 2]
    unknown = set(args) - set(names)
    if unknown:
        return [], f'no case named {", ".join(sorted(unknown))}'
    return [name for i, name in enumerate(names)
            if (not args or name in args) and i % n == k - 1], ''


def run_cases(label: str, cases: Sequence[Callable[[Path], None]], argv: Sequence[str],
              fixtures: Sequence[str] = ('demo',)) -> int:
    """Runs each of cases, or those argv chooses (select_cases), and returns the exit status of the
    run.

    Each case receives a scratch superproject of its own, with the fixture libraries named in
    fixtures (demo, unless the test names others), which is removed after it. The run prints
    "<case>: ok" after each case and "<label>: ok" at its end; a case that fails raises, which
    ends the run there. An argv select_cases refuses, a name no case has or a wrong --shard,
    makes it print why and return 2 before any case runs, as does a run without --shard that
    chooses no case, which would pass having run nothing; a shard may be empty.
    """
    chosen, error = select_cases([case.__name__ for case in cases], argv)
    if not chosen and not error and '--shard' not in argv:
        error = 'no case chosen'
    if error:
        print(f'{label}: {error}', file=sys.stderr)
        return 2
    for case in cases:
        if case.__name__ not in chosen:
            continue
        root = scratch_superproject(*fixtures)
        try:
            case(root)
        finally:
            shutil.rmtree(root)
        print(f'{case.__name__}: ok')
    print(f'{label}: ok')
    return 0
