#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks the shell steps of tools/ci/actions: download.sh keeps a file only when its SHA-256 is
the pinned one, exits 1 and leaves no file when the digest differs or the download fails; and the
Boost action's install.sh refuses an empty or relative prefix before it downloads anything, since
b2 given an empty --prefix installs into /usr/local, installs b2 in <prefix>/bin and the headers
in <prefix>/include/boost on every runner, Windows's included, where the default layouts would put
b2 in <prefix> itself and the headers in <prefix>/include/boost-1_92, and fails, before the prefix
is cached, when the prefix holds no headers or no b2 after the install. The wit-bindgen action
installs the build of the runner's system and processor, the program alone, in .local/wit-bindgen,
where the build looks for it, in place of what was there, and refuses a runner it pins no build
for before it downloads anything; the wasi-wit action installs the wit/deps directory of each
crate, wasip2's and wasip3's, in .local/wasi-wit/p2 and .local/wasi-wit/p3, in place of what was
there, and fails, naming the crate, on one that holds no WIT. The emsdk action installs the emsdk
repository at its pinned commit, fetched with git, in .local/emsdk, in place of what was there,
and fails when another commit is checked out; every archive emsdk installs is downloaded and
checked first, a release without Emscripten's node_modules fails before emsdk runs, and so does
one emsdk would download unpinned, before emsdk activate; it refuses a runner other than Linux and
macOS on x86-64 and arm64 before it downloads anything; its configure step fails, naming both
versions, on an emcc that is not Emscripten 6.0.11, installs the node wrapper, which refuses b2's
probe of --experimental-wasm-threads without a word, gives the jobs EM_CACHE by its resolved path,
outside the emsdk, and warms that cache, so that no b2 meets Emscripten's sanity check; and its
libraries step builds the system libraries the lanes link into that cache, or, for a job that
only parses (the input libraries: 'false', under the same key), the sysroot alone, a cache the
action never saves. The actions of trystero's external libraries: secp256k1 downloads the archive
of its pinned commit, refuses one whose SHA-256 is not the pin before CMake runs, builds it with
the lane's C compiler, natively and with emcmake, Debug on Windows, installs it in
.local/secp256k1-native and .local/secp256k1-emscripten, exports their variables, and keys its
cache on the compiler and the emscripten build; libdatachannel clones the tag, refuses another
commit before CMake runs, builds it with the lane's compilers against OPENSSL_ROOT, which it
refuses without, Debug on Windows, where it puts its DLL on PATH, and keys its cache on the
compilers and OpenSSL's version; openssl lays out the system's OpenSSL 3 as links on Linux and
macOS, copies the image's on Windows, from lib/VC/x64/MD first, downloads the pinned installer
when the image has none, and refuses one that is not OpenSSL 3; and each refuses a runner it
builds nothing for. Nothing is fetched
from the network: the downloads are file:// URLs, git is a stand-in, and install.sh runs against
a download.sh that only says it was called, or that hands it a stand-in archive. Run with the
names of some cases to run only those."""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

CI = Path(__file__).resolve().parent
DOWNLOAD = CI / 'download.sh'
BOOST = CI / 'actions/boost/install.sh'
WIT_BINDGEN = CI / 'actions/wit-bindgen/install.sh'
WASI_WIT = CI / 'actions/wasi-wit/install.sh'
EMSDK = CI / 'actions/emsdk/install.sh'

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


# A stand-in for b2, as bootstrap.sh builds it: --version, the headers' install, and the install
# of b2 itself from tools/build, where the layout decides where b2 goes. On Windows, Boost's
# boostcpp.jam defaults to --layout=versioned, which installs the headers in
# <prefix>/include/boost-1_92/boost, and b2's Jamroot to the portable layout, which puts b2 in
# --prefix and ignores --bindir; the system and standard layouts, the defaults elsewhere, put them
# in <prefix>/include/boost and --bindir. The stand-in takes Windows's defaults, so that only an
# install that names both layouts finds the headers and b2 where configure looks for them. With
# STAND_IN_INSTALLS_NOTHING set, it installs nothing and succeeds.
FAKE_B2 = r'''#!/usr/bin/env bash
set -euo pipefail
prefix='' bindir='' layout=portable headers=boost-1_92
for argument in "$@"; do
    case "$argument" in
        --version) echo 'B2 5.5.3 (stand-in)'; exit 0 ;;
        --prefix=*) prefix="${argument#--prefix=}" ;;
        --bindir=*) bindir="${argument#--bindir=}" ;;
        --layout=system) headers=. ;;
        b2-install-layout=*) layout="${argument#b2-install-layout=}" ;;
    esac
done
if [ -n "${STAND_IN_INSTALLS_NOTHING-}" ]; then
    exit 0
elif [ -z "$bindir" ]; then
    mkdir -p "$prefix/include/$headers/boost"
    echo '#define BOOST_VERSION 109200' > "$prefix/include/$headers/boost/version.hpp"
elif [ "$layout" = standard ]; then
    mkdir -p "$bindir" && cp "$0" "$bindir/b2"
else
    mkdir -p "$prefix" && cp "$0" "$prefix/b2"
fi
'''


def boost_archive(scratch: Path) -> Path:
    """A boost_1_92_0.tar.gz whose bootstrap.sh writes the stand-in b2."""
    tree = scratch / 'archive/boost_1_92_0'
    (tree / 'tools/build').mkdir(parents=True)
    (tree / 'b2.in').write_text(FAKE_B2)
    bootstrap = tree / 'bootstrap.sh'
    bootstrap.write_text('#!/bin/sh\ncp b2.in b2 && chmod +x b2\n')
    bootstrap.chmod(0o755)
    archive = scratch / 'boost_1_92_0.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(tree, arcname='boost_1_92_0')
    return archive


def boost_install_tree(scratch: Path) -> tuple[Path, dict[str, str]]:
    """install.sh beside a download.sh that serves the stand-in archive, and a runner's
    variables."""
    script = boost_tree(scratch)
    archive = boost_archive(scratch)
    # Boost's gzip archive, the one every runner's tar reads by itself: Windows Server 2022's
    # tar.exe has no bzip2, and hung on the bzip2 archive until the job timed out.
    (scratch / 'tools/ci/download.sh').write_text(
        '#!/bin/sh\n'
        'case "$1" in\n'
        '    https://archives.boost.io/release/1.92.0/source/boost_1_92_0.tar.gz) ;;\n'
        '    *) echo "download.sh: not the archive: $1" >&2; exit 1 ;;\n'
        'esac\n'
        f'cp "{archive}" "$3"\n')
    (scratch / 'temp').mkdir()
    return script, {'RUNNER_OS': 'Linux', 'RUNNER_TEMP': str(scratch / 'temp'),
                    'GITHUB_PATH': str(scratch / 'path')}


def test_boost_installs_b2_and_the_headers_where_configure_finds_them(scratch: Path) -> None:
    script, runner = boost_install_tree(scratch)
    prefix = scratch / 'prefix'
    result = run(script, 'install', prefix, env=runner)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    installed = sorted(str(p.relative_to(prefix)) for p in prefix.rglob('*'))
    assert (prefix / 'bin/b2').is_file(), installed
    assert (prefix / 'include/boost/version.hpp').is_file(), installed
    result = subprocess.run(['bash', str(script), 'configure', str(prefix)], capture_output=True,
                            text=True, check=False, cwd=scratch, env={**os.environ, **runner})
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert (scratch / 'path').read_text() == f'{prefix}/bin\n'


def test_boost_install_fails_when_the_prefix_is_incomplete(scratch: Path) -> None:
    script, runner = boost_install_tree(scratch)
    prefix = scratch / 'prefix'
    result = run(script, 'install', prefix, env={**runner, 'STAND_IN_INSTALLS_NOTHING': '1'})
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert f'install.sh: {prefix} holds no Boost headers or no b2' in result.stderr, (
        result.stderr)


def serving_tree(scratch: Path, action: str, script: Path, archives: dict[str, Path]) -> Path:
    """A copy of the action's install.sh where it lives, beside a download.sh that serves each
    archive by the URL it is downloaded from, and writes each URL and digest it is given to
    downloads.log; any other URL fails it."""
    directory = scratch / 'tools/ci/actions' / action
    directory.mkdir(parents=True)
    shutil.copy2(script, directory / 'install.sh')
    cases = ''.join(f'    {url}) cp "{archive}" "$3" ;;\n' for url, archive in archives.items())
    stand_in = scratch / 'tools/ci/download.sh'
    stand_in.write_text('#!/bin/sh\n'
                        f'printf \'%s %s\\n\' "$1" "$2" >> "{scratch}/downloads.log"\n'
                        'case "$1" in\n'
                        f'{cases}'
                        '    *) echo "download.sh: not served: $1" >&2; exit 1 ;;\n'
                        'esac\n')
    stand_in.chmod(0o755)
    (scratch / 'temp').mkdir()
    return directory / 'install.sh'


def downloads(scratch: Path) -> list[tuple[str, str]]:
    """The (URL, digest) of each download the stand-in was asked for, in order."""
    log = scratch / 'downloads.log'
    if not log.exists():
        return []
    return [(url, digest) for url, _, digest in
            (line.partition(' ') for line in log.read_text().splitlines())]


def tar_gz(archive: Path, root: Path, top: str) -> Path:
    """archive, a gzip tarball of root's tree under the top directory top."""
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(root, arcname=top)
    return archive


WIT_BINDGEN_RELEASE = 'https://github.com/bytecodealliance/wit-bindgen/releases/download/v0.62.0'

# The runners the action pins a build of wit-bindgen 0.62.0 for, and the build's name.
WIT_BINDGEN_BUILDS = {
    ('Linux', 'X64'): 'x86_64-linux',
    ('Linux', 'ARM64'): 'aarch64-linux',
    ('macOS', 'ARM64'): 'aarch64-macos',
    ('macOS', 'X64'): 'x86_64-macos',
}


def wit_bindgen_archive(scratch: Path, build: str) -> Path:
    """A stand-in of the release's archive of build: its top directory, the program, which says
    its version, and the files beside it, which the action leaves out."""
    top = f'wit-bindgen-0.62.0-{build}'
    tree = scratch / 'archive' / build
    tree.mkdir(parents=True)
    program = tree / 'wit-bindgen'
    program.write_text(f'#!/bin/sh\necho "wit-bindgen-cli 0.62.0 (stand-in {build})"\n')
    program.chmod(0o755)
    (tree / 'LICENSE-MIT').write_text('licence\n')
    (tree / 'README.md').write_text('readme\n')
    return tar_gz(scratch / f'{top}.tar.gz', tree, top)


def test_wit_bindgen_installs_the_runners_build_alone(scratch: Path) -> None:
    digests = set()
    for (system, processor), build in WIT_BINDGEN_BUILDS.items():
        root = scratch / build
        root.mkdir()
        url = f'{WIT_BINDGEN_RELEASE}/wit-bindgen-0.62.0-{build}.tar.gz'
        script = serving_tree(root, 'wit-bindgen', WIT_BINDGEN,
                              {url: wit_bindgen_archive(root, build)})
        # What an earlier install left is not kept beside the new one.
        stale = root / '.local/wit-bindgen/stale'
        stale.parent.mkdir(parents=True)
        stale.write_text('stale\n')
        runner = {'RUNNER_OS': system, 'RUNNER_ARCH': processor,
                  'RUNNER_TEMP': str(root / 'temp')}
        result = subprocess.run(['bash', str(script)], capture_output=True, text=True,
                                check=False, cwd=root, env={**os.environ, **runner})
        assert result.returncode == 0, (build, result.returncode, result.stderr)
        installed = root / '.local/wit-bindgen'
        assert sorted(p.name for p in installed.iterdir()) == ['wit-bindgen'], (
            build, list(installed.iterdir()))
        assert os.access(installed / 'wit-bindgen', os.X_OK), build
        assert f'wit-bindgen-cli 0.62.0 (stand-in {build})' in result.stdout, (
            build, result.stdout)
        [(downloaded, digest)] = downloads(root)
        assert downloaded == url, (build, downloaded)
        assert len(digest) == 64 and set(digest) <= set('0123456789abcdef'), (build, digest)
        digests.add(digest)
        assert list((root / 'temp').iterdir()) == [], build
    assert len(digests) == len(WIT_BINDGEN_BUILDS), digests


def test_wit_bindgen_refuses_a_runner_it_pins_no_build_for(scratch: Path) -> None:
    script = serving_tree(scratch, 'wit-bindgen', WIT_BINDGEN, {})
    for system, processor in (('Windows', 'X64'), ('Linux', 'ARM'), ('', '')):
        runner = {'RUNNER_OS': system, 'RUNNER_ARCH': processor,
                  'RUNNER_TEMP': str(scratch / 'temp')}
        result = subprocess.run(['bash', str(script)], capture_output=True, text=True,
                                check=False, cwd=scratch, env={**os.environ, **runner})
        assert result.returncode == 1, (system, processor, result.returncode, result.stderr)
        assert (f'install.sh: no wit-bindgen 0.62.0 is pinned for {system} on {processor}'
                in result.stderr), result.stderr
    assert downloads(scratch) == []
    assert not (scratch / '.local').exists()


# Each version's crate, the URL it is downloaded from, and its top directory.
WASI_CRATES = {
    'p2': ('https://static.crates.io/crates/wasip2/wasip2-1.0.4+wasi-0.2.12.crate',
           'wasip2-1.0.4+wasi-0.2.12'),
    'p3': ('https://static.crates.io/crates/wasip3/wasip3-0.9.0+wasi-0.3.0.crate',
           'wasip3-0.9.0+wasi-0.3.0'),
}


def wasi_crate(scratch: Path, version: str, deps: dict[str, str] | None) -> Path:
    """A stand-in of version's crate: its manifest, the crate's own world, and wit/deps with
    deps, each file's name and text; none when deps is None."""
    top = WASI_CRATES[version][1]
    tree = scratch / 'crates' / version
    (tree / 'wit').mkdir(parents=True)
    (tree / 'Cargo.toml').write_text('[package]\n')
    (tree / 'wit/wasi-crate.wit').write_text('package wasi:crate;\n')
    if deps is not None:
        (tree / 'wit/deps').mkdir()
        for name, text in deps.items():
            (tree / 'wit/deps' / name).write_text(text)
    return tar_gz(scratch / f'{top}.crate', tree, top)


WASI_DEPS = {
    'p2': {'http.wit': 'package wasi:http@0.2.12;\n', 'io.wit': 'package wasi:io@0.2.12;\n'},
    'p3': {'http.wit': 'package wasi:http@0.3.0;\n', 'cli.wit': 'package wasi:cli@0.3.0;\n'},
}


def test_wasi_wit_installs_each_crates_wit_deps(scratch: Path) -> None:
    archives = {WASI_CRATES[version][0]: wasi_crate(scratch, version, WASI_DEPS[version])
                for version in WASI_CRATES}
    script = serving_tree(scratch, 'wasi-wit', WASI_WIT, archives)
    stale = scratch / '.local/wasi-wit/p2/stale.wit'
    stale.parent.mkdir(parents=True)
    stale.write_text('stale\n')
    runner = {'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64', 'RUNNER_TEMP': str(scratch / 'temp')}
    result = subprocess.run(['bash', str(script)], capture_output=True, text=True, check=False,
                            cwd=scratch, env={**os.environ, **runner})
    assert result.returncode == 0, (result.returncode, result.stderr)
    for version, deps in WASI_DEPS.items():
        installed = scratch / '.local/wasi-wit' / version
        found = {p.name: p.read_text() for p in installed.iterdir()}
        assert found == deps, (version, found)
    assert [url for url, _ in downloads(scratch)] == [url for url, _ in WASI_CRATES.values()]
    digests = [digest for _, digest in downloads(scratch)]
    assert all(len(d) == 64 and set(d) <= set('0123456789abcdef') for d in digests), digests
    assert len(set(digests)) == 2, digests
    assert list((scratch / 'temp').iterdir()) == []


def test_wasi_wit_fails_on_a_crate_without_its_wit(scratch: Path) -> None:
    archives = {WASI_CRATES['p2'][0]: wasi_crate(scratch, 'p2', WASI_DEPS['p2']),
                WASI_CRATES['p3'][0]: wasi_crate(scratch, 'p3', None)}
    script = serving_tree(scratch, 'wasi-wit', WASI_WIT, archives)
    runner = {'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64', 'RUNNER_TEMP': str(scratch / 'temp')}
    result = subprocess.run(['bash', str(script)], capture_output=True, text=True, check=False,
                            cwd=scratch, env={**os.environ, **runner})
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert (f'install.sh: {WASI_CRATES["p3"][0]} holds no wit/deps/http.wit' in result.stderr), (
        result.stderr)
    assert not (scratch / '.local/wasi-wit/p3').exists()


EMSDK_COMMIT = 'dd8e25632640cfc1fb570c7fa4cc374e8a5e5a72'
EMSDK_REPOSITORY = 'https://github.com/emscripten-core/emsdk'
RELEASE = 'f6264d4a4dd9ba24a9f0a5702835a44d1463de13'
BUILDS = 'https://storage.googleapis.com/webassembly/emscripten-releases-builds'

# What emsdk 6.0.11 downloads for each runner, by URL, each saved under the name emsdk gives it in
# its downloads directory: the release's binaries, Node, and on macOS Python.
EMSDK_DOWNLOADS = {
    ('Linux', 'X64'): {
        f'{BUILDS}/linux/{RELEASE}/wasm-binaries.tar.xz': f'{RELEASE}-wasm-binaries.tar.xz',
        f'{BUILDS}/deps/node-v24.19.0-linux-x64.tar.xz': 'node-v24.19.0-linux-x64.tar.xz',
    },
    ('Linux', 'ARM64'): {
        f'{BUILDS}/linux/{RELEASE}/wasm-binaries-arm64.tar.xz':
            f'{RELEASE}-wasm-binaries-arm64.tar.xz',
        f'{BUILDS}/deps/node-v24.19.0-linux-arm64.tar.xz': 'node-v24.19.0-linux-arm64.tar.xz',
    },
    ('macOS', 'X64'): {
        f'{BUILDS}/mac/{RELEASE}/wasm-binaries.tar.xz': f'{RELEASE}-wasm-binaries.tar.xz',
        f'{BUILDS}/deps/node-v24.19.0-darwin-x64.tar.gz': 'node-v24.19.0-darwin-x64.tar.gz',
        f'{BUILDS}/deps/python-3.13.3-0-macos-x86_64.tar.gz':
            'python-3.13.3-0-macos-x86_64.tar.gz',
    },
    ('macOS', 'ARM64'): {
        f'{BUILDS}/mac/{RELEASE}/wasm-binaries-arm64.tar.xz':
            f'{RELEASE}-wasm-binaries-arm64.tar.xz',
        f'{BUILDS}/deps/node-v24.19.0-darwin-arm64.tar.gz': 'node-v24.19.0-darwin-arm64.tar.gz',
        f'{BUILDS}/deps/python-3.13.3-0-macos-arm64.tar.gz': 'python-3.13.3-0-macos-arm64.tar.gz',
    },
}

EMSCRIPTEN_VERSION = '6.0.11 (a0014542110d6078c3a1a7941fa1ddb3a2281f16)'

# The system libraries the action builds into the cache it saves: those that em++ links a program
# with at -O2 and at -O0 -g, with and without -fwasm-exceptions.
SYSTEM_LIBRARIES = [
    'libGL-getprocaddr', 'libal', 'libc', 'libc-debug', 'libc++-debug-legacyexcept',
    'libc++-debug-noexcept', 'libc++-legacyexcept', 'libc++-noexcept',
    'libc++abi-debug-legacyexcept', 'libc++abi-debug-noexcept', 'libc++abi-legacyexcept',
    'libc++abi-noexcept', 'libclang_rt.builtins', 'libclang_rt.builtins-legacysjlj', 'libdlmalloc',
    'libdlmalloc-debug', 'libhtml5', 'libnoexit', 'libsockets', 'libstubs', 'libstubs-debug',
    'libunwind-legacyexcept',
]

# A stand-in of git, for the commands the action runs: `init -q <dir>`, `-C <dir> fetch --depth 1
# <repository> <commit>`, which logs its repository and commit to git.log and copies the stand-in
# emsdk, STAND_IN_EMSDK, into <dir>, `-C <dir> checkout -q FETCH_HEAD`, and `-C <dir> rev-parse
# HEAD`, which prints STAND_IN_HEAD, else the commit fetched.
FAKE_GIT = r'''#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = init ]; then
    mkdir -p "$3/.git"
    exit 0
fi
[ "$1" = -C ] || { echo "git: not a command of the stand-in: $*" >&2; exit 1; }
directory="$2"
shift 2
case "$*" in
    'fetch --depth 1 '*)
        printf '%s %s\n' "$4" "$5" >> "${STAND_IN_LOG}"
        cp -R "${STAND_IN_EMSDK}/." "${directory}/"
        echo "$5" > "${directory}/.git/FETCH_HEAD"
        ;;
    'checkout -q FETCH_HEAD') ;;
    'rev-parse HEAD') echo "${STAND_IN_HEAD:-$(cat "${directory}/.git/FETCH_HEAD")}" ;;
    *) echo "git: not a command of the stand-in: $*" >&2; exit 1 ;;
esac
'''

# A stand-in of emsdk's own script: `install 6.0.11` installs nothing it would have to download,
# so it needs each archive the action pins in downloads/ and EMSDK_KEEP_DOWNLOADS=1, under which
# emsdk takes a file there for the download; it writes STAND_IN_EXTRA there too when that names a
# file, as an emsdk that downloads more than the action pins would. It installs an emcc and an
# em++ that print STAND_IN_VERSION, else 6.0.11's, and check Emscripten's configuration the first
# time they meet a cache, as Emscripten does, saying so on standard error; and an embuilder that
# logs what it is asked to build, and with which cache, to embuilder.log. `activate 6.0.11` writes
# the configuration, and fails when an unpinned download is still there.
FAKE_EMSDK = r'''#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
case "$*" in
    'install 6.0.11')
        [ "${EMSDK_KEEP_DOWNLOADS-}" = 1 ] || { echo 'emsdk: would download' >&2; exit 1; }
        for name in $(cat "$here/expected-downloads"); do
            [ -f "$here/downloads/$name" ] || { echo "emsdk: would download $name" >&2; exit 1; }
        done
        if [ -n "${STAND_IN_EXTRA-}" ]; then
            echo extra > "$here/downloads/$STAND_IN_EXTRA"
        fi
        mkdir -p "$here/upstream/emscripten/node_modules"
        for tool in emcc em++; do
            cat > "$here/upstream/emscripten/$tool" <<'TOOL'
#!/usr/bin/env bash
if [ ! -f "$EM_CACHE/sanity.txt" ]; then
    echo 'shared:INFO: (Emscripten: Running sanity checks)' >&2
    mkdir -p "$EM_CACHE" && echo checked > "$EM_CACHE/sanity.txt"
fi
version="${STAND_IN_VERSION:-6.0.11 (a0014542110d6078c3a1a7941fa1ddb3a2281f16)}"
echo "emcc (Emscripten gcc/clang-like replacement + linker emulating GNU ld) ${version}"
TOOL
            chmod +x "$here/upstream/emscripten/$tool"
        done
        cat > "$here/upstream/emscripten/embuilder" <<'TOOL'
#!/usr/bin/env bash
printf '%s %s\n' "$EM_CACHE" "$*" >> "$(dirname "$0")/../../embuilder.log"
TOOL
        chmod +x "$here/upstream/emscripten/embuilder"
        ;;
    'activate 6.0.11')
        if [ -n "${STAND_IN_EXTRA-}" ] && [ -e "$here/downloads/$STAND_IN_EXTRA" ]; then
            echo 'emsdk: activated with an unpinned download' >&2
            exit 1
        fi
        echo "LLVM_ROOT = '$here/upstream/bin'" > "$here/.emscripten"
        ;;
    *) echo "emsdk: not a command of the stand-in: $*" >&2; exit 1 ;;
esac
'''


def release_archive(path: Path, node_modules: bool) -> Path:
    """A stand-in of the release's binaries, an xz tarball under install/, with Emscripten's
    node_modules unless node_modules is False."""
    with tarfile.open(path, 'w:xz') as tar:
        for name in ('install/emscripten/emcc.py',
                     *(['install/emscripten/node_modules/acorn/package.json']
                       if node_modules else [])):
            data = f'{name}\n'.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    return path


def emsdk_tree(scratch: Path, system: str, processor: str,
               node_modules: bool = True) -> tuple[Path, dict[str, str]]:
    """The emsdk action's files where they live, beside a download.sh that serves a stand-in of
    each archive the action pins for the runner, a stand-in git that serves the stand-in emsdk,
    and the runner's variables, its workspace reached through a link."""
    tree = scratch / 'stand-in emsdk'
    tree.mkdir(parents=True)
    script = tree / 'emsdk'
    script.write_text(FAKE_EMSDK)
    script.chmod(0o755)
    downloads = EMSDK_DOWNLOADS.get((system, processor), {})
    (tree / 'expected-downloads').write_text(''.join(f'{name}\n' for name in downloads.values()))
    (scratch / 'archive').mkdir()
    archives = {}
    for url, name in downloads.items():
        stand_in = scratch / 'archive' / name
        if 'wasm-binaries' in name:
            release_archive(stand_in, node_modules)
        else:
            stand_in.write_text(f'{url}\n')
        archives[url] = stand_in
    install = serving_tree(scratch, 'emsdk', EMSDK, archives)
    for name in ('node.sh', 'action.yml'):
        shutil.copy2(EMSDK.parent / name, install.parent / name)
    tools = scratch / 'tools-on-path'
    tools.mkdir()
    (tools / 'git').write_text(FAKE_GIT)
    (tools / 'git').chmod(0o755)
    # The workspace, by a link to it: what is installed lands in scratch itself.
    workspace = scratch / 'workspace link'
    workspace.symlink_to(scratch)
    return install, {'RUNNER_OS': system, 'RUNNER_ARCH': processor,
                     'RUNNER_TEMP': str(scratch / 'temp'), 'GITHUB_WORKSPACE': str(workspace),
                     'GITHUB_ENV': str(scratch / 'github-env'),
                     'GITHUB_OUTPUT': str(scratch / 'github-output'),
                     'PATH': f'{tools}{os.pathsep}{os.environ["PATH"]}',
                     'STAND_IN_EMSDK': str(tree), 'STAND_IN_LOG': str(scratch / 'git.log')}


def emsdk_step(scratch: Path, script: Path, step: str, runner: dict[str, str],
               **extra: str) -> subprocess.CompletedProcess:
    """Runs the emsdk action's step from the workspace, as the action does."""
    environment = {**os.environ, **runner, **extra}
    environment.pop('EM_CACHE', None)
    return subprocess.run(['bash', str(script), step], capture_output=True, text=True,
                          check=False, cwd=runner['GITHUB_WORKSPACE'], env=environment)


def fetched(scratch: Path) -> list[str]:
    """The (repository, commit) of each fetch the stand-in git was asked for, one line each."""
    log = scratch / 'git.log'
    return log.read_text().splitlines() if log.exists() else []


def test_emsdk_installs_the_pinned_emsdk_into_local_emsdk(scratch: Path) -> None:
    for (system, processor), pinned in EMSDK_DOWNLOADS.items():
        root = scratch / f'{system}-{processor}'
        root.mkdir()
        script, runner = emsdk_tree(root, system, processor)
        # What an earlier install left is not kept beside the new one.
        stale = root / '.local/emsdk/stale'
        stale.parent.mkdir(parents=True)
        stale.write_text('stale\n')
        result = emsdk_step(root, script, 'install', runner)
        assert result.returncode == 0, (system, processor, result.returncode, result.stderr)
        emsdk = root / '.local/emsdk'
        assert (emsdk / 'emsdk').is_file() and not stale.exists(), sorted(emsdk.iterdir())
        assert (emsdk / 'upstream/emscripten/emcc').is_file(), sorted(emsdk.iterdir())
        assert (emsdk / '.emscripten').is_file(), sorted(emsdk.iterdir())
        # emsdk is the repository at the pinned commit, without its git directory.
        assert fetched(root) == [f'{EMSDK_REPOSITORY} {EMSDK_COMMIT}'], fetched(root)
        assert not (emsdk / '.git').exists(), sorted(emsdk.iterdir())
        # The archives emsdk installed from are checked, then left out of what is cached.
        assert not (emsdk / 'downloads').exists(), sorted((emsdk / 'downloads').iterdir())
        assert [url for url, _ in downloads(root)] == [*pinned], downloads(root)
        digests = [digest for _, digest in downloads(root)]
        assert all(len(d) == 64 and set(d) <= set('0123456789abcdef') for d in digests), digests
        assert len(set(digests)) == len(digests), digests
        assert list((root / 'temp').iterdir()) == [], (system, processor)
        # The cache key names the version and the runner.
        result = emsdk_step(root, script, 'key', runner)
        assert result.returncode == 0, (result.returncode, result.stderr)
        key = (root / 'github-output').read_text()
        assert key.startswith('key=emsdk-6.0.11-') and f'-{processor}-' in key, key


def test_emsdk_fails_on_another_commit(scratch: Path) -> None:
    # The commit is the pin: a fetch that checks out another fails the install, naming both.
    script, runner = emsdk_tree(scratch, 'Linux', 'X64')
    other = '1' * 40
    result = emsdk_step(scratch, script, 'install', runner, STAND_IN_HEAD=other)
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert (f'install.sh: {EMSDK_REPOSITORY} at {EMSDK_COMMIT} checked out {other}') in (
        result.stderr), result.stderr
    assert not (scratch / '.local/emsdk').exists()
    assert downloads(scratch) == []


def test_emsdk_fails_on_a_release_without_its_node_modules(scratch: Path) -> None:
    # emsdk would run npm ci against the registry for a release without Emscripten's
    # node_modules: the install fails first, naming the archive, and emsdk installs nothing.
    script, runner = emsdk_tree(scratch, 'Linux', 'X64', node_modules=False)
    result = emsdk_step(scratch, script, 'install', runner)
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert (f'install.sh: {RELEASE}-wasm-binaries.tar.xz holds no install/emscripten/'
            'node_modules, which emsdk would install with npm from the registry') in (
                result.stderr), result.stderr
    assert not (scratch / '.local/emsdk').exists()


def test_emsdk_configure_installs_the_wrapper_and_warms_the_cache(scratch: Path) -> None:
    script, runner = emsdk_tree(scratch, 'Linux', 'X64')
    result = emsdk_step(scratch, script, 'install', runner)
    assert result.returncode == 0, (result.returncode, result.stderr)
    result = emsdk_step(scratch, script, 'configure', runner)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    # EM_CACHE by its resolved path, though the workspace is reached through a link, and outside
    # the emsdk.
    cache = scratch.resolve() / '.local/emscripten-cache'
    assert (scratch / 'github-env').read_text() == f'EM_CACHE={cache}\n', (
        (scratch / 'github-env').read_text())
    # Warmed: Emscripten checked its configuration here, in the action's log, and the b2 of a job
    # meets a cache that is checked already.
    assert (cache / 'sanity.txt').is_file(), sorted(cache.iterdir())
    assert 'Running sanity checks' in result.stdout + result.stderr, (result.stdout, result.stderr)
    # The node wrapper, which refuses b2's probe without a word, and runs node otherwise.
    wrapper = scratch / '.local/emscripten/node'
    assert os.access(wrapper, os.X_OK), wrapper
    probe = subprocess.run([str(wrapper), '--version', '--experimental-wasm-threads'],
                           capture_output=True, text=True, check=False)
    assert probe.returncode != 0 and probe.stdout == probe.stderr == '', probe
    (scratch / 'bin').mkdir()
    stand_in = scratch / 'bin/node'
    stand_in.write_text('#!/bin/sh\necho "node $*"\n')
    stand_in.chmod(0o755)
    ran = subprocess.run([str(wrapper), 'x y.js', '--flag'], capture_output=True, text=True,
                         check=False,
                         env={**os.environ, 'PATH': f'{scratch / "bin"}:/usr/bin:/bin'})
    assert (ran.returncode, ran.stdout) == (0, 'node x y.js --flag\n'), ran
    # Configured again over a restored cache, it checks nothing more and says so on no line.
    result = emsdk_step(scratch, script, 'configure', runner)
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert 'Running sanity checks' not in result.stdout + result.stderr, result.stderr


def test_emsdk_builds_the_system_libraries_into_the_cache(scratch: Path) -> None:
    # The cache the action saves holds the system libraries the lanes link, built with embuilder
    # in the cache configure gives the jobs, so that no lane builds them.
    script, runner = emsdk_tree(scratch, 'Linux', 'X64')
    for step in ('install', 'configure', 'libraries'):
        result = emsdk_step(scratch, script, step, runner)
        assert result.returncode == 0, (step, result.returncode, result.stdout, result.stderr)
    cache = scratch.resolve() / '.local/emscripten-cache'
    built = (scratch / '.local/emsdk/embuilder.log').read_text().splitlines()
    assert built == [f'{cache} build {" ".join(SYSTEM_LIBRARIES)}'], built


def test_emsdk_for_a_job_that_only_parses(scratch: Path) -> None:
    # A job that parses Emscripten's headers and links nothing, the docs and the lint, gives the
    # input libraries: 'false': the key is the same, so it restores the cache the lanes save,
    # its system libraries built; on a miss it writes the headers and the sysroot alone, with
    # embuilder build sysroot, and never saves that cache, which the lanes would restore without
    # their libraries.
    script, runner = emsdk_tree(scratch, 'Linux', 'X64')
    keys = []
    for libraries in ('true', 'false'):
        (scratch / 'github-output').unlink(missing_ok=True)
        result = emsdk_step(scratch, script, 'key', runner, LIBRARIES=libraries)
        assert result.returncode == 0, (result.returncode, result.stderr)
        written = dict(line.split('=', 1)
                       for line in (scratch / 'github-output').read_text().splitlines())
        assert written['libraries'] == libraries, written
        keys.append(written['key'])
    assert keys[0] == keys[1], keys
    result = emsdk_step(scratch, script, 'key', runner, LIBRARIES='some')
    assert result.returncode == 2, (result.returncode, result.stderr)
    assert "install.sh: the input libraries is 'true' or 'false', not 'some'" in result.stderr, (
        result.stderr)
    for step in ('install', 'configure'):
        result = emsdk_step(scratch, script, step, runner)
        assert result.returncode == 0, (step, result.returncode, result.stderr)
    result = emsdk_step(scratch, script, 'libraries', runner, LIBRARIES='false')
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    cache = scratch.resolve() / '.local/emscripten-cache'
    built = (scratch / '.local/emsdk/embuilder.log').read_text().splitlines()
    assert built == [f'{cache} build sysroot'], built
    # The action passes the input to both steps, and saves the cache only when the libraries
    # were built.
    action = (EMSDK.parent / 'action.yml').read_text()
    steps = {step.split('\n', 1)[0]: step for step in action.split('    - name: ')[1:]}
    assert "LIBRARIES: ${{ inputs.libraries }}" in steps['Cache key'], steps['Cache key']
    assert "steps.key.outputs.libraries == 'true'" in steps['Save emsdk'], steps['Save emsdk']
    assert "LIBRARIES: ${{ inputs.libraries }}" in steps["Build Emscripten's system libraries"]
    assert re.search(r"^  libraries:\n(    .*\n)*    default: 'true'$", action, re.MULTILINE), (
        action)


def test_the_jamroot_pins_the_action_s_version(_: Path) -> None:
    # The Jamroot refuses an emsdk of another version than the one the action installs, for a
    # reference's Emscripten headers: both name one version.
    pinned = re.search(r'^version=(\S+)$', EMSDK.read_text(), re.MULTILINE)
    jamroot = re.search(r'^\.emscripten-version = (\S+) ;$',
                        (CI.parents[1] / 'Jamroot').read_text(), re.MULTILINE)
    assert pinned and jamroot and pinned.group(1) == jamroot.group(1), (pinned, jamroot)


def test_emsdk_configure_fails_naming_both_versions(scratch: Path) -> None:
    script, runner = emsdk_tree(scratch, 'Linux', 'X64')
    result = emsdk_step(scratch, script, 'install', runner)
    assert result.returncode == 0, (result.returncode, result.stderr)
    other = '6.0.10 (0000000000000000000000000000000000000000)'
    result = emsdk_step(scratch, script, 'configure', runner, STAND_IN_VERSION=other)
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert (f'install.sh: .local/emsdk/upstream/emscripten/emcc is not Emscripten '
            f'{EMSCRIPTEN_VERSION}: emcc --version printed') in result.stderr, result.stderr
    assert other in result.stderr, result.stderr
    assert not (scratch / 'github-env').exists()


def test_emsdk_fails_on_a_download_it_does_not_pin(scratch: Path) -> None:
    # Before emsdk activate, which runs on macOS with the Python the install just unpacked.
    script, runner = emsdk_tree(scratch, 'Linux', 'X64')
    result = emsdk_step(scratch, script, 'install', runner, STAND_IN_EXTRA='llvm.tar.xz')
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert ('install.sh: emsdk downloaded llvm.tar.xz, which this action does not pin') in (
        result.stderr), result.stderr
    assert 'activated with an unpinned download' not in result.stderr, result.stderr
    assert not (scratch / '.local/emsdk').exists()


def test_emsdk_refuses_a_runner_it_pins_nothing_for(scratch: Path) -> None:
    for system, processor in (('Windows', 'X64'), ('Linux', 'ARM'), ('', '')):
        root = scratch / f'runner {system or "none"}'
        root.mkdir()
        script, runner = emsdk_tree(root, system, processor)
        for step in ('install', 'configure', 'libraries'):
            result = emsdk_step(root, script, step, runner)
            assert result.returncode == 1, (system, processor, step, result.returncode)
            assert (f'install.sh: no emsdk 6.0.11 is pinned for {system} on {processor}: the '
                    'action runs on Linux and macOS, on X64 and ARM64') in result.stderr, (
                        result.stderr)
        assert downloads(root) == [] and fetched(root) == []
        assert not (root / '.local').exists()


# The external dependencies, which the lanes of a library that needs them build or lay out in
# .local/, until webcpp builds them from third_party/.
SECP256K1 = CI / 'actions/secp256k1/install.sh'
LIBDATACHANNEL = CI / 'actions/libdatachannel/install.sh'
OPENSSL = CI / 'actions/openssl/install.sh'

SECP256K1_COMMIT = '6e2c8bc4ecdc6e71dbe7a368f360d8d453ce435d'
SECP256K1_URL = f'https://github.com/bitcoin-core/secp256k1/archive/{SECP256K1_COMMIT}.tar.gz'
SECP256K1_SHA256 = '3fe9fd705f4fdf2fe90d6e04b6c1fedd7e8f244a119315886f6468f52c2dfc33'
LIBDATACHANNEL_COMMIT = '6b1e2e620f1e37f0eafeee702eaea0043cb305fd'
LIBDATACHANNEL_REPOSITORY = 'https://github.com/paullouisageneau/libdatachannel.git'
OPENSSL_INSTALLER = 'https://slproweb.com/download/Win64OpenSSL-3_6_5.exe'
OPENSSL_INSTALLER_SHA256 = '8b2fcf66088fa0d13fa5729ef374a182adf72edfffde89089b3b1bf48c3f257f'

# The options each build is configured with, as trystero's page builds it.
SECP256K1_OPTIONS = [
    '-DBUILD_SHARED_LIBS=OFF', '-DCMAKE_POSITION_INDEPENDENT_CODE=ON', '-DCMAKE_INSTALL_LIBDIR=lib',
    '-DSECP256K1_ENABLE_MODULE_SCHNORRSIG=ON', '-DSECP256K1_ENABLE_MODULE_EXTRAKEYS=ON',
    '-DSECP256K1_ECMULT_WINDOW_SIZE=4', '-DSECP256K1_ECMULT_GEN_KB=2',
    '-DSECP256K1_BUILD_TESTS=OFF', '-DSECP256K1_BUILD_EXHAUSTIVE_TESTS=OFF',
    '-DSECP256K1_BUILD_BENCHMARK=OFF', '-DSECP256K1_BUILD_CTIME_TESTS=OFF',
]
LIBDATACHANNEL_OPTIONS = ['-DCMAKE_INSTALL_LIBDIR=lib', '-DBUILD_SHARED_LIBS=ON',
                          '-DNO_WEBSOCKET=ON', '-DNO_EXAMPLES=ON', '-DNO_TESTS=ON',
                          '-DNO_MEDIA=OFF']

# A stand-in of cmake: each call's words to cmake.log, one line each; --install <work> --config
# <config> --prefix <prefix> also writes every file STAND_IN_INSTALLS names, relative to the
# prefix.
FAKE_CMAKE = r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "cmake $*" >> "${STAND_IN_LOG}"
if [ "$1" = --install ]; then
    prefix="${@: -1}"
    for file in ${STAND_IN_INSTALLS-}; do
        mkdir -p "$(dirname "${prefix}/${file}")"
        echo installed > "${prefix}/${file}"
    done
fi
"""

# A stand-in of Emscripten's emcmake, which says it ran, then runs what it wraps.
FAKE_EMCMAKE = r"""#!/usr/bin/env bash
printf '%s\n' "emcmake $*" >> "${STAND_IN_LOG}"
exec "$@"
"""

# A stand-in of a compiler, which says what it is as gcc's --version's first line does.
FAKE_COMPILER = '#!/bin/sh\necho "$(basename "$0") (stand-in) ${STAND_IN_VERSION:-14.2.0}"\n'

# A stand-in of git for the libdatachannel action: `clone ... <repository> <dir>` logs its words
# and makes the directory, `-C <dir> submodule ...` logs its words, and `-C <dir> rev-parse HEAD`
# prints STAND_IN_HEAD, else the pin.
FAKE_CLONE = r"""#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = clone ]; then
    printf '%s\n' "git $*" >> "${STAND_IN_LOG}"
    mkdir -p "${@: -1}"
    exit 0
fi
if [ "$1 $3" = '-C submodule' ]; then
    printf '%s\n' "git $*" >> "${STAND_IN_LOG}"
    exit 0
fi
if [ "$1 $3 $4" != '-C rev-parse HEAD' ]; then
    echo "git: not a command of the stand-in: $*" >&2
    exit 1
fi
echo "${STAND_IN_HEAD:-""" + LIBDATACHANNEL_COMMIT + r"""}"
"""

# A stand-in of cygpath, which a Windows runner's Git Bash has: the path as it is.
FAKE_CYGPATH = '#!/bin/sh\nprintf \'%s\\n\' "$2"\n'


def stand_ins(scratch: Path, tools: dict[str, str]) -> Path:
    """A directory of the stand-in programs tools names, each by its text."""
    directory = scratch / 'tools-on-path'
    directory.mkdir(exist_ok=True)
    for name, text in tools.items():
        (directory / name).write_text(text)
        (directory / name).chmod(0o755)
    return directory


def logged(scratch: Path) -> list[str]:
    """The lines the stand-ins wrote, in order."""
    log = scratch / 'stand-in.log'
    return log.read_text().splitlines() if log.exists() else []


def dependency_runner(scratch: Path, system: str, processor: str, tools: Path,
                      **extra: str) -> dict[str, str]:
    """A runner's variables, with the stand-ins first on PATH."""
    return {'RUNNER_OS': system, 'RUNNER_ARCH': processor, 'RUNNER_TEMP': str(scratch / 'temp'),
            'ImageOS': 'ubuntu24', 'ImageVersion': '20261004.327.1',
            'GITHUB_OUTPUT': str(scratch / 'github-output'),
            'GITHUB_ENV': str(scratch / 'github-env'), 'GITHUB_PATH': str(scratch / 'github-path'),
            'PATH': f'{tools}{os.pathsep}{os.environ["PATH"]}',
            'STAND_IN_LOG': str(scratch / 'stand-in.log'), **extra}


def dependency_step(scratch: Path, script: Path, runner: dict[str, str],
                    *arguments: str) -> subprocess.CompletedProcess:
    """Runs the action's script from the scratch superproject, as the action does."""
    environment = {**os.environ, **runner}
    for name in ('CC', 'CXX', 'EMSCRIPTEN', 'OPENSSL_ROOT'):
        if name not in runner:
            environment.pop(name, None)
    return subprocess.run(['bash', str(script), *arguments], capture_output=True, text=True,
                          check=False, cwd=scratch, env=environment)


def secp256k1_archive(scratch: Path) -> Path:
    """A stand-in of the archive of the pinned commit: its top directory and a CMakeLists.txt."""
    tree = scratch / 'archive/secp256k1'
    tree.mkdir(parents=True)
    (tree / 'CMakeLists.txt').write_text('project(secp256k1)\n')
    return tar_gz(scratch / 'secp256k1.tar.gz', tree, f'secp256k1-{SECP256K1_COMMIT}')


SECP256K1_FILES = 'include/secp256k1.h include/secp256k1_schnorrsig.h lib/libsecp256k1.a'


def secp256k1_tree(scratch: Path, system: str = 'Linux', processor: str = 'X64',
                   **extra: str) -> tuple[Path, dict[str, str]]:
    """The secp256k1 action where it lives, beside a download.sh that serves the stand-in
    archive, with stand-ins of cmake, Emscripten's emcmake and the compilers, and a runner's
    variables."""
    script = serving_tree(scratch, 'secp256k1', SECP256K1,
                          {SECP256K1_URL: secp256k1_archive(scratch)})
    shutil.copy2(SECP256K1.parent / 'action.yml', script.parent / 'action.yml')
    # The emsdk action, whose version the emscripten build's key names.
    (scratch / 'tools/ci/actions/emsdk').mkdir()
    shutil.copy2(EMSDK, scratch / 'tools/ci/actions/emsdk/install.sh')
    emcmake = scratch / '.local/emsdk/upstream/emscripten/emcmake'
    emcmake.parent.mkdir(parents=True)
    emcmake.write_text(FAKE_EMCMAKE)
    emcmake.chmod(0o755)
    tools = stand_ins(scratch, {'cmake': FAKE_CMAKE, 'gcc-14': FAKE_COMPILER,
                                'clang-18': FAKE_COMPILER, 'cygpath': FAKE_CYGPATH})
    return script, dependency_runner(scratch, system, processor, tools,
                                     **{'STAND_IN_INSTALLS': SECP256K1_FILES, **extra})


def test_secp256k1_builds_the_pinned_archive_natively_and_for_emscripten(scratch: Path) -> None:
    script, runner = secp256k1_tree(scratch, CC='gcc-14', EMSCRIPTEN='true')
    # What an earlier install left is not kept.
    stale = scratch / '.local/secp256k1-native/stale'
    stale.parent.mkdir(parents=True)
    stale.write_text('stale\n')
    result = dependency_step(scratch, script, runner, 'install')
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert downloads(scratch) == [(SECP256K1_URL, SECP256K1_SHA256)], downloads(scratch)
    source = f'.local/.build/secp256k1/secp256k1-{SECP256K1_COMMIT}'
    # The prefixes by the resolved path of the directory the step runs in, as $PWD has it.
    native = f'{scratch.resolve()}/.local/secp256k1-native'
    emscripten = f'{scratch.resolve()}/.local/secp256k1-emscripten'
    assert logged(scratch) == [
        f'cmake -DCMAKE_C_COMPILER=gcc-14 -S {source} -B .local/.build/secp256k1/native '
        f'-DCMAKE_BUILD_TYPE=Release {" ".join(SECP256K1_OPTIONS)} '
        f'-DCMAKE_INSTALL_PREFIX={native}',
        'cmake --build .local/.build/secp256k1/native --config Release --parallel',
        f'cmake --install .local/.build/secp256k1/native --config Release --prefix {native}',
        f'emcmake cmake -S {source} -B .local/.build/secp256k1/emscripten '
        f'-DCMAKE_BUILD_TYPE=Release {" ".join(SECP256K1_OPTIONS)} '
        f'-DCMAKE_INSTALL_PREFIX={emscripten}',
        'cmake -S {0} -B .local/.build/secp256k1/emscripten -DCMAKE_BUILD_TYPE=Release {1} '
        '-DCMAKE_INSTALL_PREFIX={2}'.format(source, ' '.join(SECP256K1_OPTIONS), emscripten),
        'cmake --build .local/.build/secp256k1/emscripten --config Release --parallel',
        f'cmake --install .local/.build/secp256k1/emscripten --config Release --prefix '
        f'{emscripten}'], logged(scratch)
    assert not stale.exists() and not (scratch / '.local/.build/secp256k1').exists()
    result = dependency_step(scratch, script, runner, 'configure')
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert (scratch / 'github-env').read_text() == (f'SECP256K1_ROOT={native}\n'
                                                   f'SECP256K1_EMSCRIPTEN_ROOT={emscripten}\n')
    # The key names the version, the runner, the build and the compiler: another compiler, or the
    # emscripten build left out, is another entry of the cache.
    keys = []
    for extra in ({'CC': 'gcc-14', 'EMSCRIPTEN': 'true'}, {'CC': 'clang-18', 'EMSCRIPTEN': 'true'},
                  {'CC': 'gcc-14', 'EMSCRIPTEN': 'false'}, {'CC': 'gcc-14', 'EMSCRIPTEN': 'true',
                                                            'STAND_IN_VERSION': '14.3.0'}):
        (scratch / 'github-output').unlink(missing_ok=True)
        result = dependency_step(scratch, script, {**runner, **extra}, 'key')
        assert result.returncode == 0, (result.returncode, result.stderr)
        key = (scratch / 'github-output').read_text()
        assert key.startswith('key=secp256k1-0.8.0-Linux-X64-ubuntu24-'), key
        keys.append(key)
    assert len(set(keys)) == len(keys), keys
    assert '-native-emscripten-6.0.11-' in keys[0] and '-native-emscripten' not in keys[2], keys
    # The Emscripten version is the emsdk action's, read from it: a bump of emsdk is another entry.
    emsdk = scratch / 'tools/ci/actions/emsdk/install.sh'
    emsdk.write_text(emsdk.read_text().replace('\nversion=6.0.11\n', '\nversion=6.0.12\n'))
    (scratch / 'github-output').unlink()
    result = dependency_step(scratch, script, runner, 'key')
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert '-native-emscripten-6.0.12-' in (scratch / 'github-output').read_text()
    emsdk.write_text('# no version\n')
    result = dependency_step(scratch, script, runner, 'key')
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert (f'install.sh: {emsdk.resolve()} names no version=') in result.stderr, result.stderr


def test_secp256k1_on_windows_builds_debug_with_visual_studio(scratch: Path) -> None:
    # No compiler named: CMake's own, Visual Studio's; the Debug configuration, whose /MDd the
    # lanes' debug variant links with; and the library CMake names libsecp256k1.lib there.
    script, runner = secp256k1_tree(scratch, 'Windows', 'X64',
                                    STAND_IN_INSTALLS=SECP256K1_FILES.replace('.a', '.lib'))
    result = dependency_step(scratch, script, runner, 'install')
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert logged(scratch)[0].startswith('cmake -S '), logged(scratch)
    assert '-DCMAKE_BUILD_TYPE=Debug ' in logged(scratch)[0], logged(scratch)
    assert logged(scratch)[1].endswith('--config Debug --parallel'), logged(scratch)
    assert not any('emcmake' in line for line in logged(scratch)), logged(scratch)
    result = dependency_step(scratch, script, runner, 'configure')
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert (scratch / 'github-env').read_text() == (
        f'SECP256K1_ROOT={scratch.resolve()}/.local/secp256k1-native\n'), (
            (scratch / 'github-env').read_text())
    # A build without its library is no install.
    (scratch / '.local/secp256k1-native/lib/libsecp256k1.lib').unlink()
    result = dependency_step(scratch, script, runner, 'configure')
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert 'holds no include/secp256k1.h, include/secp256k1_schnorrsig.h or ' in result.stderr
    assert 'lib/libsecp256k1.lib' in result.stderr, result.stderr


def test_secp256k1_refuses_an_archive_it_does_not_pin(scratch: Path) -> None:
    # The download is checked by download.sh itself: an archive whose SHA-256 is not the pinned
    # one fails the install before CMake runs, and leaves nothing to be cached.
    script, runner = secp256k1_tree(scratch, CC='gcc-14')
    archive = scratch / 'secp256k1.tar.gz'
    (scratch / 'tools/ci/download.sh').write_text(
        f'#!/bin/sh\nexec bash "{DOWNLOAD}" "{archive.as_uri()}" "$2" "$3"\n')
    result = dependency_step(scratch, script, runner, 'install')
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert f'has SHA-256 {actual}, and {SECP256K1_SHA256} is pinned' in result.stderr, (
        result.stderr)
    assert f'install.sh: {SECP256K1_URL} could not be downloaded as pinned' in result.stderr
    assert logged(scratch) == [], logged(scratch)
    assert not (scratch / '.local/secp256k1-native').exists()
    assert not (scratch / '.local/.build/secp256k1').exists()


def test_secp256k1_refuses_a_runner_it_builds_nothing_for(scratch: Path) -> None:
    script, runner = secp256k1_tree(scratch)
    for system, processor, emscripten in (('Linux', 'ARM', 'false'), ('', '', 'false'),
                                          ('Windows', 'ARM64', 'false'),
                                          ('Windows', 'X64', 'true')):
        for step in ('key', 'install', 'configure'):
            result = dependency_step(scratch, script, {**runner, 'RUNNER_OS': system,
                                                       'RUNNER_ARCH': processor,
                                                       'EMSCRIPTEN': emscripten}, step)
            assert result.returncode == 1, (system, processor, step, result.returncode)
            if emscripten == 'true':
                assert ('install.sh: the emscripten build of libsecp256k1 is made on Linux and '
                        'macOS') in result.stderr, result.stderr
            else:
                assert (f'and Windows on X64, not for {system} on {processor}'
                        in result.stderr), result.stderr
    result = dependency_step(scratch, script, {**runner, 'EMSCRIPTEN': 'yes'}, 'install')
    assert result.returncode == 2, (result.returncode, result.stderr)
    assert "the input emscripten is 'true' or 'false', not 'yes'" in result.stderr
    assert downloads(scratch) == [] and logged(scratch) == []
    assert not (scratch / '.local/secp256k1-native').exists()


def openssl_root(scratch: Path, name: str = 'openssl', major: str | None = '3') -> Path:
    """A stand-in installation of OpenSSL: include/openssl/ssl.h and opensslv.h, which states
    major as its OPENSSL_VERSION_MAJOR, or none, as OpenSSL 1.1's."""
    root = scratch / name
    (root / 'include/openssl').mkdir(parents=True)
    (root / 'include/openssl/ssl.h').write_text('/* ssl.h */\n')
    version = f'# define OPENSSL_VERSION_MAJOR  {major}\n' if major else ''
    (root / 'include/openssl/opensslv.h').write_text(
        f'{version}# define OPENSSL_VERSION_TEXT "OpenSSL {major or "1.1"}.0.13"\n')
    (root / 'lib').mkdir()
    return root


def libdatachannel_tree(scratch: Path, system: str = 'Linux', processor: str = 'X64',
                        **extra: str) -> tuple[Path, dict[str, str]]:
    """The libdatachannel action where it lives, with stand-ins of git, cmake and the compilers,
    an OpenSSL where OPENSSL_ROOT names it, and a runner's variables."""
    directory = scratch / 'tools/ci/actions/libdatachannel'
    directory.mkdir(parents=True)
    shutil.copy2(LIBDATACHANNEL, directory / 'install.sh')
    shutil.copy2(LIBDATACHANNEL.parent / 'action.yml', directory / 'action.yml')
    tools = stand_ins(scratch, {'git': FAKE_CLONE, 'cmake': FAKE_CMAKE, 'gcc-14': FAKE_COMPILER,
                                'g++-14': FAKE_COMPILER, 'clang-18': FAKE_COMPILER,
                                'clang++-18': FAKE_COMPILER, 'cygpath': FAKE_CYGPATH})
    installs = {'Linux': 'lib/libdatachannel.so', 'macOS': 'lib/libdatachannel.dylib',
                'Windows': 'lib/datachannel.lib bin/datachannel.dll'}.get(system, '')
    return directory / 'install.sh', dependency_runner(
        scratch, system, processor, tools, OPENSSL_ROOT=str(openssl_root(scratch)),
        STAND_IN_INSTALLS=f'include/rtc/rtc.hpp {installs}', **extra)


def test_libdatachannel_builds_the_pinned_tag_with_the_lanes_compilers(scratch: Path) -> None:
    script, runner = libdatachannel_tree(scratch, CC='gcc-14', CXX='g++-14')
    result = dependency_step(scratch, script, runner, 'install')
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    work = '.local/.build/libdatachannel/build'
    prefix = f'{scratch.resolve()}/.local/libdatachannel'
    assert logged(scratch) == [
        # The submodules are fetched only once HEAD is the pin, at the commits its gitlinks name.
        f'git clone --quiet --depth 1 --branch v0.24.6 {LIBDATACHANNEL_REPOSITORY} '
        '.local/.build/libdatachannel/source',
        'git -C .local/.build/libdatachannel/source submodule update --quiet --init --recursive '
        '--depth 1',
        f'cmake -S .local/.build/libdatachannel/source -B {work} -DCMAKE_C_COMPILER=gcc-14 '
        f'-DCMAKE_CXX_COMPILER=g++-14 -DCMAKE_BUILD_TYPE=Release '
        f'{" ".join(LIBDATACHANNEL_OPTIONS)} -DOPENSSL_ROOT_DIR={scratch}/openssl '
        f'-DCMAKE_INSTALL_PREFIX={prefix}',
        f'cmake --build {work} --config Release --parallel',
        f'cmake --install {work} --config Release --prefix {prefix}'], logged(scratch)
    assert not (scratch / '.local/.build/libdatachannel').exists()
    result = dependency_step(scratch, script, runner, 'configure')
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert (scratch / 'github-env').read_text() == f'LIBDATACHANNEL_ROOT={prefix}\n'
    assert not (scratch / 'github-path').exists()
    # The key names the compilers and the OpenSSL it is built against.
    keys = []
    for extra in ({'CC': 'gcc-14', 'CXX': 'g++-14'}, {'CC': 'clang-18', 'CXX': 'clang++-18'},
                  {'CC': 'gcc-14', 'CXX': 'g++-14', 'STAND_IN_VERSION': '14.3.0'},
                  {'CC': '', 'CXX': ''}):
        (scratch / 'github-output').unlink(missing_ok=True)
        result = dependency_step(scratch, script, {**runner, **extra}, 'key')
        assert result.returncode == 0, (result.returncode, result.stderr)
        keys.append((scratch / 'github-output').read_text())
    (scratch / 'openssl/include/openssl/opensslv.h').write_text(
        '# define OPENSSL_VERSION_MAJOR  3\n# define OPENSSL_VERSION_TEXT "OpenSSL 3.5.5"\n')
    (scratch / 'github-output').unlink()
    dependency_step(scratch, script, runner, 'key')
    keys.append((scratch / 'github-output').read_text())
    assert all(key.startswith('key=libdatachannel-0.24.6-Linux-X64-ubuntu24-') for key in keys)
    assert len(set(keys)) == len(keys), keys


def test_libdatachannel_on_windows_builds_debug_and_puts_its_dll_on_path(scratch: Path) -> None:
    script, runner = libdatachannel_tree(scratch, 'Windows', 'X64')
    result = dependency_step(scratch, script, runner, 'install')
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert '-DCMAKE_C_COMPILER' not in logged(scratch)[2], logged(scratch)
    assert '-DCMAKE_BUILD_TYPE=Debug ' in logged(scratch)[2], logged(scratch)
    result = dependency_step(scratch, script, runner, 'configure')
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert (scratch / 'github-path').read_text() == (
        f'{scratch.resolve()}/.local/libdatachannel/bin\n'), (scratch / 'github-path').read_text()


def test_libdatachannel_refuses_another_commit(scratch: Path) -> None:
    # The tag's commit is the pin: a clone that checks out another fails, naming both, before
    # CMake runs, and leaves nothing to be cached.
    script, runner = libdatachannel_tree(scratch, CC='gcc-14', CXX='g++-14')
    other = '1' * 40
    result = dependency_step(scratch, script, {**runner, 'STAND_IN_HEAD': other}, 'install')
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert (f'install.sh: {LIBDATACHANNEL_REPOSITORY} at v0.24.6 checked out {other}, and '
            f'{LIBDATACHANNEL_COMMIT} is pinned') in result.stderr, result.stderr
    # Nothing but the clone ran: no submodule was fetched, and CMake never ran.
    assert logged(scratch) == [
        f'git clone --quiet --depth 1 --branch v0.24.6 {LIBDATACHANNEL_REPOSITORY} '
        '.local/.build/libdatachannel/source'], logged(scratch)
    assert not (scratch / '.local/libdatachannel').exists()
    assert not (scratch / '.local/.build/libdatachannel').exists()


def test_libdatachannel_refuses_a_runner_or_no_openssl(scratch: Path) -> None:
    script, runner = libdatachannel_tree(scratch)
    for system, processor in (('Linux', 'ARM'), ('Windows', 'ARM64'), ('', '')):
        result = dependency_step(scratch, script, {**runner, 'RUNNER_OS': system,
                                                   'RUNNER_ARCH': processor}, 'install')
        assert result.returncode == 1, (system, processor, result.returncode)
        assert f'and Windows on X64, not for {system} on {processor}' in result.stderr, (
            result.stderr)
    for openssl in ('', str(scratch / 'nothing')):
        result = dependency_step(scratch, script, {**runner, 'OPENSSL_ROOT': openssl}, 'install')
        assert result.returncode == 1, (openssl, result.returncode)
        assert (f'install.sh: OPENSSL_ROOT names no OpenSSL ({openssl}): the openssl action runs '
                'first') in result.stderr, result.stderr
    assert logged(scratch) == []


def openssl_tree(scratch: Path, system: str, processor: str,
                 tools: dict[str, str]) -> tuple[Path, dict[str, str]]:
    """The openssl action where it lives, beside a download.sh that only says it was called, with
    the stand-ins tools names, and a runner's variables."""
    directory = scratch / 'tools/ci/actions/openssl'
    directory.mkdir(parents=True)
    shutil.copy2(OPENSSL, directory / 'install.sh')
    download = scratch / 'tools/ci/download.sh'
    download.write_text(f'#!/bin/sh\nprintf \'%s %s\\n\' "$1" "$2" >> "{scratch}/downloads.log"\n'
                        f'echo "{CALLED}" >&2\nexit {CALLED_STATUS}\n')
    download.chmod(0o755)
    (scratch / 'temp').mkdir()
    return directory / 'install.sh', dependency_runner(
        scratch, system, processor, stand_ins(scratch, {'cygpath': FAKE_CYGPATH, **tools}))


def test_openssl_lays_out_the_runners_own(scratch: Path) -> None:
    # On Linux the system's, which pkg-config names; on macOS Homebrew's openssl@3: links to its
    # headers and its two libraries, in a directory of their own, and OPENSSL_ROOT.
    for system, tool, extension in (('Linux', 'pkg-config', 'so'), ('macOS', 'brew', 'dylib')):
        root = scratch / system
        root.mkdir()
        system_openssl = openssl_root(root, 'system openssl')
        for library in ('libssl', 'libcrypto'):
            (system_openssl / 'lib' / f'{library}.{extension}').write_text(library)
        answers = {'pkg-config': '#!/bin/sh\ncase "$1" in\n'
                                 f'    --variable=includedir) echo "{system_openssl}/include" ;;\n'
                                 f'    --variable=libdir) echo "{system_openssl}/lib" ;;\n'
                                 '    *) exit 1 ;;\nesac\n',
                   'brew': '#!/bin/sh\n[ "$*" = "--prefix openssl@3" ] && '
                           f'echo "{system_openssl}"\n'}
        script, runner = openssl_tree(root, system, 'ARM64', {tool: answers[tool]})
        result = dependency_step(root, script, runner)
        assert result.returncode == 0, (system, result.returncode, result.stderr)
        laid = root.resolve() / '.local/openssl'
        assert (laid / 'include/openssl').resolve() == (
            system_openssl.resolve() / 'include/openssl'), system
        assert sorted(p.name for p in (laid / 'lib').iterdir()) == [
            f'libcrypto.{extension}', f'libssl.{extension}'], system
        assert (laid / f'lib/libssl.{extension}').resolve() == (
            system_openssl.resolve() / f'lib/libssl.{extension}'), system
        assert (root / 'github-env').read_text() == f'OPENSSL_ROOT={laid}\n', (
            system, (root / 'github-env').read_text())
        assert 'install.sh: OpenSSL 3 in .local/openssl' in result.stdout, result.stdout
        assert downloads(root) == [], system


def test_openssl_on_windows_copies_the_images_and_puts_its_dlls_on_path(scratch: Path) -> None:
    # The image's, in %ProgramFiles%\OpenSSL: its headers, and the import libraries of the first
    # of lib/VC/x64/MD, lib/VC/x64/MDd and lib that holds both.
    programs = scratch / 'Program Files'
    installed = openssl_root(programs, 'OpenSSL')
    (installed / 'lib/VC/x64/MD').mkdir(parents=True)
    for library in ('libssl.lib', 'libcrypto.lib'):
        (installed / 'lib/VC/x64/MD' / library).write_text(f'MD {library}')
        (installed / 'lib' / library).write_text(f'top {library}')
    script, runner = openssl_tree(scratch, 'Windows', 'X64', {})
    runner['ProgramFiles'] = str(programs)
    result = dependency_step(scratch, script, runner)
    assert result.returncode == 0, (result.returncode, result.stderr)
    laid = scratch.resolve() / '.local/openssl'
    assert (laid / 'include/openssl/ssl.h').is_file()
    assert not (laid / 'include/openssl').is_symlink()
    assert (laid / 'lib/libssl.lib').read_text() == 'MD libssl.lib'
    assert (laid / 'lib/libcrypto.lib').read_text() == 'MD libcrypto.lib'
    assert (scratch / 'github-path').read_text() == f'{installed}/bin\n', (
        (scratch / 'github-path').read_text())
    assert (scratch / 'github-env').read_text() == f'OPENSSL_ROOT={laid}\n'
    assert downloads(scratch) == []


def test_openssl_on_windows_without_one_downloads_the_pinned_installer(scratch: Path) -> None:
    script, runner = openssl_tree(scratch, 'Windows', 'X64', {})
    runner['ProgramFiles'] = str(scratch / 'Program Files')
    result = dependency_step(scratch, script, runner)
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert CALLED in result.stderr, result.stderr
    assert downloads(scratch) == [(OPENSSL_INSTALLER, OPENSSL_INSTALLER_SHA256)]
    assert not (scratch / '.local/openssl').exists()


def test_openssl_refuses_one_that_is_not_3_or_a_runner_it_has_none_for(scratch: Path) -> None:
    root = scratch / 'old'
    root.mkdir()
    old = openssl_root(root, 'openssl@1.1', None)
    brew = f'#!/bin/sh\necho "{old}"\n'
    script, runner = openssl_tree(root, 'macOS', 'X64', {'brew': brew})
    result = dependency_step(root, script, runner)
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert (f"install.sh: {old}/include/openssl/opensslv.h is not OpenSSL 3's: "
            "OPENSSL_VERSION_MAJOR is ''") in result.stderr, result.stderr
    assert not (root / '.local/openssl').exists() and not (root / 'github-env').exists()
    for system, processor in (('Windows', 'ARM64'), ('Linux', 'ARM'), ('', '')):
        result = dependency_step(root, script, {**runner, 'RUNNER_OS': system,
                                                'RUNNER_ARCH': processor})
        assert result.returncode == 1, (system, processor, result.returncode)
        assert (f'install.sh: no OpenSSL 3 is found or pinned for {system} on {processor}'
                in result.stderr), result.stderr
    assert downloads(root) == []


def test_openssl_on_macos_installs_openssl_3_when_the_image_lacks_it(scratch: Path) -> None:
    # Homebrew's openssl@3 is in the image today only as a dependency of other formulae: when it
    # is not installed, the action installs it with brew (whose bottle Homebrew checks against its
    # SHA-256), says so, and lays it out as it would the image's.
    staged = openssl_root(scratch, 'staged')
    for library in ('libssl', 'libcrypto'):
        (staged / 'lib' / f'{library}.dylib').write_text(library)
    prefix = scratch / 'homebrew/opt/openssl@3'
    brew = ('#!/bin/sh\n'
            f'printf \'%s\\n\' "brew $*" >> "{scratch}/stand-in.log"\n'
            'case "$*" in\n'
            f'    "--prefix openssl@3") echo "{prefix}" ;;\n'
            f'    "install openssl@3") mkdir -p "{prefix.parent}" && '
            f'cp -R "{staged}" "{prefix}" ;;\n'
            '    *) exit 1 ;;\n'
            'esac\n')
    script, runner = openssl_tree(scratch, 'macOS', 'ARM64', {'brew': brew})
    result = dependency_step(scratch, script, runner)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert logged(scratch) == ['brew --prefix openssl@3', 'brew install openssl@3'], (
        logged(scratch))
    assert (f"install.sh: Homebrew's openssl@3 is not installed in {prefix}: installing it with "
            'brew') in result.stdout, result.stdout
    laid = scratch.resolve() / '.local/openssl'
    assert (laid / 'include/openssl').resolve() == (prefix.resolve() / 'include/openssl')
    # A brew that cannot install it fails the step, naming the formula.
    (scratch / 'stand-in.log').unlink()
    shutil.rmtree(prefix)
    failing = brew.replace('cp -R', 'false && cp -R')
    (scratch / 'tools-on-path/brew').write_text(failing)
    result = dependency_step(scratch, script, runner)
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert 'install.sh: brew install openssl@3 failed' in result.stderr, result.stderr
    assert not (scratch / '.local/openssl').exists()


CHROME = CI / 'actions/chrome/install.sh'
CHROME_VERSION = '155.0.8059.39'
CHROME_BUILDS = {
    'X64': ('linux64', '39dcb8c46550632a3d911850ab3b8af840b4e3f6d8622faa2018eb8756278786'),
    'ARM64': ('linux-arm64', '9fb86f7c0b2734c5febc0bbb4e85f37da43553f3f8a7970949828c5713e87e94'),
}


def chrome_archive(scratch: Path, build: str) -> Path:
    """A stand-in of the shell's zip: its top directory, a program that prints its arguments, and
    the files beside it."""
    archive = scratch / f'chrome-headless-shell-{build}.zip'
    with zipfile.ZipFile(archive, 'w') as zipped:
        program = zipfile.ZipInfo(f'chrome-headless-shell-{build}/chrome-headless-shell')
        program.external_attr = 0o755 << 16
        zipped.writestr(program, '#!/bin/sh\necho "shell $*"\n')
        zipped.writestr(f'chrome-headless-shell-{build}/ABOUT', 'about\n')
    return archive


def test_chrome_installs_the_pinned_headless_shell(scratch: Path) -> None:
    # Chrome for Testing's chrome-headless-shell at its pinned version, checked against the
    # SHA-256 recorded for the runner's build, in .local/chrome-headless-shell, and CHROME its
    # wrapper, which runs it with --no-sandbox and the arguments it is given.
    for processor, (build, digest) in CHROME_BUILDS.items():
        root = scratch / processor
        root.mkdir()
        url = (f'https://storage.googleapis.com/chrome-for-testing-public/{CHROME_VERSION}/{build}/'
               f'chrome-headless-shell-{build}.zip')
        script = serving_tree(root, 'chrome', CHROME, {url: chrome_archive(root, build)})
        stale = root / '.local/chrome-headless-shell/stale'
        stale.parent.mkdir(parents=True)
        stale.write_text('stale\n')
        runner = dependency_runner(root, 'Linux', processor, stand_ins(root, {}))
        result = dependency_step(root, script, runner)
        assert result.returncode == 0, (processor, result.returncode, result.stderr)
        assert downloads(root) == [(url, digest)], downloads(root)
        assert not stale.exists() and list((root / 'temp').iterdir()) == []
        wrapper = root.resolve() / '.local/chrome-headless-shell/chrome'
        assert (root / 'github-env').read_text() == f'CHROME={wrapper}\n'
        ran = subprocess.run([str(wrapper), '--headless=new', 'x y'], capture_output=True,
                             text=True, check=False)
        assert (ran.returncode, ran.stdout) == (0, 'shell --no-sandbox --headless=new x y\n'), ran
        assert f'chrome-headless-shell {CHROME_VERSION}' in result.stdout, result.stdout


def test_chrome_refuses_a_shell_it_does_not_pin_or_a_runner_it_has_none_for(scratch: Path) -> None:
    build, digest = CHROME_BUILDS['X64']
    url = (f'https://storage.googleapis.com/chrome-for-testing-public/{CHROME_VERSION}/{build}/'
           f'chrome-headless-shell-{build}.zip')
    archive = chrome_archive(scratch, build)
    script = serving_tree(scratch, 'chrome', CHROME, {url: archive})
    # The real download.sh, given the stand-in: its SHA-256 is not the pinned one.
    (scratch / 'tools/ci/download.sh').write_text(
        f'#!/bin/sh\nexec bash "{DOWNLOAD}" "{archive.as_uri()}" "$2" "$3"\n')
    runner = dependency_runner(scratch, 'Linux', 'X64', stand_ins(scratch, {}))
    result = dependency_step(scratch, script, runner)
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert f'and {digest} is pinned' in result.stderr, result.stderr
    assert not (scratch / '.local/chrome-headless-shell').exists()
    assert not (scratch / 'github-env').exists()
    for system, processor in (('macOS', 'ARM64'), ('Windows', 'X64'), ('Linux', 'ARM'), ('', '')):
        result = dependency_step(scratch, script, {**runner, 'RUNNER_OS': system,
                                                   'RUNNER_ARCH': processor})
        assert result.returncode == 1, (system, processor, result.returncode)
        assert (f'install.sh: no chrome-headless-shell {CHROME_VERSION} is pinned for {system} on '
                f'{processor}') in result.stderr, result.stderr


CONTAINER = CI / 'actions/container/install.sh'

# A stand-in of docker for the container action: each call's words to stand-in.log; `save
# --output <file> <tag>` writes the file, `load --input <file>` reads it and remembers the tag
# it held, and `image inspect <tag>` succeeds when that tag was loaded or built.
FAKE_IMAGE_DOCKER = r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "docker $*" >> "${STAND_IN_LOG}"
images="${STAND_IN_LOG}.images"
case "$1" in
    build) printf '%s\n' "$3" >> "${images}" ;;
    save) printf '%s\n' "${@: -1}" > "$3" ;;
    load) cat "$3" >> "${images}" ;;
    image) grep -qx "$3" "${images}" 2>/dev/null ;;
    *) exit 1 ;;
esac
"""


def container_tree(scratch: Path) -> tuple[Path, dict[str, str]]:
    """The container action where it lives, the Dockerfile beside it, a stand-in docker, and a
    runner's variables."""
    directory = scratch / 'tools/ci/actions/container'
    directory.mkdir(parents=True)
    for name in ('install.sh', 'action.yml'):
        shutil.copy2(CONTAINER.parent / name, directory / name)
    (scratch / 'tools/ci/container').mkdir()
    shutil.copy2(CI / 'container/Dockerfile', scratch / 'tools/ci/container/Dockerfile')
    tools = stand_ins(scratch, {'docker': FAKE_IMAGE_DOCKER})
    return directory / 'install.sh', dependency_runner(scratch, 'Linux', 'X64', tools)


def test_container_builds_the_image_once_and_loads_it_after(scratch: Path) -> None:
    # The key and the tag are the Dockerfile's, as tools/ci/matrix.py tags the image; on a miss
    # the image is built and saved where the action caches it, and on a hit loaded from there.
    script, runner = container_tree(scratch)
    result = dependency_step(scratch, script, runner, 'key')
    assert result.returncode == 0, (result.returncode, result.stderr)
    digest = hashlib.sha256((CI / 'container/Dockerfile').read_bytes()).hexdigest()[:16]
    tag = f'webcpp-lane:{digest}'
    sys.path.insert(0, str(CI))
    import matrix
    assert matrix.CONTAINER_IMAGE == tag, (matrix.CONTAINER_IMAGE, tag)
    assert (scratch / 'github-output').read_text() == (
        f'tag={tag}\nkey=container-{digest}-ubuntu24-X64\n'), (
            (scratch / 'github-output').read_text())
    result = dependency_step(scratch, script, runner, 'build')
    assert result.returncode == 0, (result.returncode, result.stderr)
    archive = '.local/container/image.tar'
    assert logged(scratch) == [f'docker build --tag {tag} tools/ci/container',
                               f'docker save --output {archive} {tag}'], logged(scratch)
    (scratch / 'stand-in.log').unlink()
    (scratch / 'stand-in.log.images').unlink()
    result = dependency_step(scratch, script, runner, 'load')
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert logged(scratch) == [f'docker load --input {archive}', f'docker image inspect {tag}']
    # An archive that holds another image fails the load, naming the tag it lacks.
    (scratch / archive).write_text('webcpp-lane:0000000000000000\n')
    (scratch / 'stand-in.log.images').unlink()
    result = dependency_step(scratch, script, runner, 'load')
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert f'install.sh: {archive} holds no image {tag}' in result.stderr, result.stderr


CASES: list[Callable[[Path], None]] = [
    test_a_pinned_download_is_kept,
    test_another_digest_leaves_no_file,
    test_a_failed_download_exits_1_and_leaves_no_file,
    test_a_usage_error_exits_2,
    test_boost_refuses_an_empty_or_relative_prefix,
    test_boost_installs_b2_and_the_headers_where_configure_finds_them,
    test_boost_install_fails_when_the_prefix_is_incomplete,
    test_wit_bindgen_installs_the_runners_build_alone,
    test_wit_bindgen_refuses_a_runner_it_pins_no_build_for,
    test_wasi_wit_installs_each_crates_wit_deps,
    test_wasi_wit_fails_on_a_crate_without_its_wit,
    test_emsdk_installs_the_pinned_emsdk_into_local_emsdk,
    test_emsdk_fails_on_another_commit,
    test_emsdk_fails_on_a_release_without_its_node_modules,
    test_emsdk_configure_installs_the_wrapper_and_warms_the_cache,
    test_emsdk_builds_the_system_libraries_into_the_cache,
    test_emsdk_for_a_job_that_only_parses,
    test_the_jamroot_pins_the_action_s_version,
    test_emsdk_configure_fails_naming_both_versions,
    test_emsdk_fails_on_a_download_it_does_not_pin,
    test_emsdk_refuses_a_runner_it_pins_nothing_for,
    test_secp256k1_builds_the_pinned_archive_natively_and_for_emscripten,
    test_secp256k1_on_windows_builds_debug_with_visual_studio,
    test_secp256k1_refuses_an_archive_it_does_not_pin,
    test_secp256k1_refuses_a_runner_it_builds_nothing_for,
    test_libdatachannel_builds_the_pinned_tag_with_the_lanes_compilers,
    test_libdatachannel_on_windows_builds_debug_and_puts_its_dll_on_path,
    test_libdatachannel_refuses_another_commit,
    test_libdatachannel_refuses_a_runner_or_no_openssl,
    test_openssl_lays_out_the_runners_own,
    test_openssl_on_macos_installs_openssl_3_when_the_image_lacks_it,
    test_openssl_on_windows_copies_the_images_and_puts_its_dlls_on_path,
    test_openssl_on_windows_without_one_downloads_the_pinned_installer,
    test_openssl_refuses_one_that_is_not_3_or_a_runner_it_has_none_for,
    test_container_builds_the_image_once_and_loads_it_after,
    test_chrome_installs_the_pinned_headless_shell,
    test_chrome_refuses_a_shell_it_does_not_pin_or_a_runner_it_has_none_for,
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
