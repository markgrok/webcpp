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
there, and fails, naming the crate, on one that holds no WIT. Nothing is fetched from the network:
the downloads are file:// URLs, and install.sh runs against a download.sh that only says it was
called, or that hands it a stand-in archive. Run with the names of some cases to run only
those."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path

CI = Path(__file__).resolve().parent
DOWNLOAD = CI / 'download.sh'
BOOST = CI / 'actions/boost/install.sh'
WIT_BINDGEN = CI / 'actions/wit-bindgen/install.sh'
WASI_WIT = CI / 'actions/wasi-wit/install.sh'

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
