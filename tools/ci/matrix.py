#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""The CI's lanes: which ones run, each lane's b2 command, and the report that merges them.

Usage: matrix.py plan [--library NAME] [--user-config FILE]
       matrix.py lane LANE [--user-config FILE] [--out-dir DIR] [-- B2-ARGUMENT ...]
       matrix.py register ID [ID ...] [--user-config FILE]
       matrix.py report --plan MATRIX --lanes DIR --out DIR

plan runs `b2 -d0 declared-targets` from the superproject's root and prints the JSON matrix of
the lanes to run, {"include": [LANE, ...]}: one lane per compiler of LANES for each target a
library declares, of the library --library names, else of every library. A lane builds the tests
and examples of the libraries that declare its target, and no other: a lane of a target no
library declares would build nothing. A target the CI has no lane for (emscripten, until emsdk
is pinned: AGENTS.md, Roadmap) is a failure, never a lane left out.

lane runs one lane, LANE being one entry of that matrix as JSON: it registers the lane's toolset
in the user-config.jam (unless it is there already), then runs the lane command the Jamroot
documents,

    b2 --user-config=FILE -a --dump-tests --out-xml=DIR/<lane>.xml toolset=<toolset> \\
        <options> <B2-ARGUMENT ...> libs/<library>/test libs/<library>/example ...

without CPATH, CPLUS_INCLUDE_PATH and C_INCLUDE_PATH. A lane is named after the directory b2
builds it in, which tools/report/report.py checks: gcc-14, clang-linux-18, msvc-14.3, wasip2.
Apple Clang's version is the image's, so its lane reads it from `clang++ -dumpversion` and
registers clang under it: clang-darwin-17. With --out-xml, b2 exits 0 even when a test fails;
the report is the verdict. B2-ARGUMENT is for a local run beside others, such as
--build-dir=bin/lane-gcc-15; the CI passes none.

register adds the toolsets of the lanes named by id to the user-config.jam, in their order, the
first being b2's default toolset: what the CI's tools job builds the tests of the tools with.

report merges what the lanes of the matrix MATRIX wrote under DIR, one directory per lane,
lane-<id>/<lane>.xml (as the CI downloads the lanes' artifacts), with tools/report/report.py into
--out. A lane of the matrix that wrote no XML, as when its job failed before b2 ran, fails the
report by name: the matrix would otherwise be green without it.

The user-config.jam is .local/user-config.jam by default, where tools/ci/actions/boost writes the
`using boost` line. Exit 0 on success; 1 when b2 or the report fails, or when a lane wrote no
XML; 2 on a usage error, a target with no lane, or a planned lane missing from the report.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REPORT = ROOT / 'tools/report/report.py'

COMPILER_PATHS = ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH')

# Where tools/ci/actions/wasi-sdk installs wasi-sdk, as the README installs it.
WASI_SDK = '.local/wasi-sdk'

# MSVC's lanes build 64-bit programs, embed their manifest with the linker and abbreviate b2's
# paths against Windows's MAX_PATH, as xstate-cpp's green Windows jobs did. b2 abbreviates each
# word of the toolset directory too, and msvc-14.3 and msvc-14.5 are their own abbreviations,
# so the lanes keep their names (tools/ci/matrix_test.py checks it with b2's own rule).
MSVC_OPTIONS = ('address-model=64', 'embed-manifest-via=linker', '--abbreviate-paths')


@dataclass(frozen=True)
class Lane:
    """A lane: one toolset, one runner, for the libraries that declare its target."""

    # Unique in a matrix, and fixed: the lane's job and artifact are named after it.
    id: str
    # What the CI shows for its job.
    name: str
    # The runner image.
    os: str
    # The target it builds for (tools/webcpp.jam): native, wasip2 or wasip3.
    target: str
    # The directory b2 builds the lane in, and the lane's column in the report. {version} is the
    # major version of the compiler `detect` names.
    lane: str
    toolset: str
    # The line that registers the toolset in user-config.jam. {wasi_sdk} is wasi-sdk's absolute
    # directory.
    using: str
    # The compiler whose major version is {version}, or nothing.
    detect: str = ''
    options: tuple[str, ...] = ()
    # Whether the lane needs wasi-sdk and wasmtime.
    wasm: bool = False
    # The b2 projects it builds: libs/<library>/test and libs/<library>/example of each library.
    projects: tuple[str, ...] = field(default_factory=tuple)


def wasm_lane(target: str) -> Lane:
    flags = ' '.join(f'<{flag}>--target=wasm32-{target}' for flag in ('cflags', 'cxxflags',
                                                                        'linkflags'))
    return Lane(id=target, name=f'wasm32-{target} (wasi-sdk 34, wasmtime 47.0.3)',
                os='ubuntu-24.04', target=target, lane=target, toolset=f'clang-{target}',
                using=(f'using clang : {target} : {{wasi_sdk}}/bin/clang++ : {flags} '
                       '<archiver>{wasi_sdk}/bin/llvm-ar <ranlib>{wasi_sdk}/bin/llvm-ranlib ;'),
                options=('testing.launcher=wasmtime',), wasm=True)


# Every lane the CI knows, by target. GCC and Clang on Linux build with libstdc++, the system's
# standard library there: Clang on libstdc++ alone catches a regression of xactor's guarantee 28.
LANES = (
    Lane(id='gcc-14', name='GCC 14', os='ubuntu-24.04', target='native', lane='gcc-14',
         toolset='gcc-14', using='using gcc : 14 : g++-14 ;'),
    Lane(id='gcc-15', name='GCC 15', os='ubuntu-26.04', target='native', lane='gcc-15',
         toolset='gcc-15', using='using gcc : 15 : g++-15 ;'),
    Lane(id='clang-18', name='Clang 18 (libstdc++)', os='ubuntu-24.04', target='native',
         lane='clang-linux-18', toolset='clang-18', using='using clang : 18 : clang++-18 ;'),
    Lane(id='clang-22', name='Clang 22 (libstdc++)', os='ubuntu-26.04', target='native',
         lane='clang-linux-22', toolset='clang-22', using='using clang : 22 : clang++-22 ;'),
    Lane(id='apple-clang', name='Apple Clang (macOS 15)', os='macos-15', target='native',
         lane='clang-darwin-{version}', toolset='clang-{version}',
         using='using clang : {version} : clang++ ;', detect='clang++'),
    Lane(id='msvc-14.3', name='MSVC 14.3 (Visual Studio 2022)', os='windows-2022',
         target='native', lane='msvc-14.3', toolset='msvc-14.3', using='using msvc : 14.3 ;',
         options=MSVC_OPTIONS),
    Lane(id='msvc-14.5', name='MSVC 14.5 (Visual Studio 2026)', os='windows-2025',
         target='native', lane='msvc-14.5', toolset='msvc-14.5', using='using msvc : 14.5 ;',
         options=MSVC_OPTIONS),
    wasm_lane('wasip2'),
    wasm_lane('wasip3'),
)

# The targets tools/webcpp.jam knows, which a library may declare.
KNOWN = ('native', 'emscripten', 'wasip2', 'wasip3')


class Failure(Exception):
    """What stops a command, said to the user, with the exit status it gives."""

    def __init__(self, message: str, status: int = 1) -> None:
        super().__init__(message)
        self.status = status


def environment() -> dict[str, str]:
    """This process's environment without the variables the Jamroot refuses."""
    return {name: value for name, value in os.environ.items() if name not in COMPILER_PATHS}


def declared(user_config: Path) -> list[tuple[str, str]]:
    """The pairs (library, target) `b2 declared-targets` prints."""
    command = ['b2', f'--user-config={user_config}', '-d0', 'declared-targets']
    try:
        completed = subprocess.run(command, cwd=ROOT, env=environment(), capture_output=True,
                                   text=True, check=False)
    except OSError as error:
        raise Failure(f'cannot run b2: {error.strerror}') from error
    if completed.returncode != 0:
        raise Failure(f'{completed.stdout}{completed.stderr}{shlex.join(command)} exited '
                      f'{completed.returncode}')
    pairs = []
    for line in completed.stdout.splitlines():
        # b2's own warnings, such as the default toolset it configures when user-config.jam
        # registers none, as the plan job's does; -d0 does not hide them.
        if line.startswith('warning: '):
            continue
        words = line.split()
        if len(words) != 2:
            raise Failure(f'b2 declared-targets printed {line!r}, not "<library> <target>"')
        pairs.append((words[0], words[1]))
    return pairs


def plan(pairs: list[tuple[str, str]], library: str | None) -> list[Lane]:
    """The lanes for the pairs (library, target), of library alone when it is given."""
    if library is not None:
        if library not in {name for name, _ in pairs}:
            raise Failure(f'libs/{library} declares no target, or is no library of libs/ '
                          '(a directory with a build.jam)', 2)
        pairs = [(name, target) for name, target in pairs if name == library]
    if not pairs:
        raise Failure('no library declares a target: there is nothing to build', 2)
    unknown = sorted({target for _, target in pairs if target not in KNOWN})
    if unknown:
        raise Failure(f'b2 declared-targets names targets the CI does not know: '
                      f'{", ".join(unknown)}', 2)
    targets = {target for _, target in pairs}
    missing = sorted(targets - {lane.target for lane in LANES})
    if missing:
        declaring = sorted({name for name, target in pairs if target in missing})
        raise Failure(f'{", ".join(declaring)} declare {", ".join(missing)}, which the CI has '
                      'no lane for: the CI gets an emscripten lane when emsdk is pinned '
                      '(AGENTS.md, Roadmap); a target is never left untested', 2)
    lanes = []
    for lane in LANES:
        libraries = sorted({name for name, target in pairs if target == lane.target})
        if libraries:
            projects = tuple(f'libs/{name}/{part}' for name in libraries
                             for part in ('test', 'example'))
            lanes.append(replace(lane, projects=projects))
    return lanes


def matrix(lanes: list[Lane]) -> str:
    """The lanes as the JSON of a job's strategy.matrix, on one line."""
    return json.dumps({'include': [asdict(lane) for lane in lanes]}, separators=(',', ':'))


def parsed_lane(text: str) -> Lane:
    """The Lane of an entry of the matrix, given as JSON."""
    try:
        entry = json.loads(text)
        entry['options'] = tuple(entry['options'])
        entry['projects'] = tuple(entry['projects'])
        return Lane(**entry)
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise Failure(f'the lane is not an entry of the matrix plan writes: {error}', 2) from None


def major_version(compiler: str) -> str:
    """The major version of compiler: 17 for an Apple Clang that says 17.0.0."""
    try:
        completed = subprocess.run([compiler, '-dumpversion'], capture_output=True, text=True,
                                   check=False)
    except OSError as error:
        raise Failure(f'cannot run {compiler}: {error.strerror}') from error
    major = completed.stdout.strip().split('.')[0]
    if completed.returncode != 0 or not major.isdigit():
        raise Failure(f'{compiler} -dumpversion printed {completed.stdout.strip()!r}, exit '
                      f'status {completed.returncode}: no version to name the lane by')
    return major


def resolved(lane: Lane) -> Lane:
    """lane with its {version} and {wasi_sdk} filled in."""
    version = major_version(lane.detect) if lane.detect else ''
    wasi_sdk = (ROOT / WASI_SDK).as_posix()

    def fill(text: str) -> str:
        return text.replace('{version}', version).replace('{wasi_sdk}', wasi_sdk)

    return replace(lane, lane=fill(lane.lane), toolset=fill(lane.toolset), using=fill(lane.using))


def register(lane: Lane, user_config: Path) -> None:
    """Adds the lane's using line to user_config, unless it holds that line already."""
    text = user_config.read_text() if user_config.is_file() else ''
    if lane.using in text.splitlines():
        return
    if text and not text.endswith('\n'):
        text += '\n'
    user_config.parent.mkdir(parents=True, exist_ok=True)
    user_config.write_text(f'{text}{lane.using}\n')


def lane_command(lane: Lane, user_config: Path, xml: Path, extra: list[str]) -> list[str]:
    """The lane command: b2, from scratch, writing xml, for the lane's toolset and projects."""
    return ['b2', f'--user-config={user_config}', '-a', '--dump-tests', f'--out-xml={xml}',
            f'toolset={lane.toolset}', *lane.options, *extra, *lane.projects]


def run_lane(lane: Lane, user_config: Path, out_dir: Path, extra: list[str]) -> int:
    """Runs the lane, and returns its exit status."""
    lane = resolved(lane)
    register(lane, user_config)
    out_dir.mkdir(parents=True, exist_ok=True)
    xml = out_dir / f'{lane.lane}.xml'
    if xml.exists():
        xml.unlink()
    command = lane_command(lane, user_config, xml, extra)
    print(f'lane {lane.lane}: {shlex.join(command)}', flush=True)
    try:
        status = subprocess.run(command, cwd=ROOT, env=environment(), check=False).returncode
    except OSError as error:
        raise Failure(f'cannot run b2: {error.strerror}') from error
    # The job's outputs: the lane's name, and its XML only when b2 wrote it, so that the upload
    # step runs only on a file that is there.
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a') as output:
            output.write(f'lane={lane.lane}\n')
            if xml.is_file():
                output.write(f'xml={xml.as_posix()}\n')
    if status != 0:
        raise Failure(f'lane {lane.lane}: b2 exited {status}; with --out-xml it does so only when '
                      'it cannot build at all, a test failing is the report\'s to say')
    if not xml.is_file():
        raise Failure(f'lane {lane.lane}: b2 wrote no {xml}')
    return 0


def register_lanes(ids: list[str], user_config: Path) -> None:
    """Registers the toolsets of the lanes ids in user_config, in their order: the first is b2's
    default toolset."""
    known = {lane.id: lane for lane in LANES}
    unknown = [lane_id for lane_id in ids if lane_id not in known]
    if unknown:
        raise Failure(f'no lane {", ".join(unknown)}; the lanes are {", ".join(known)}', 2)
    for lane_id in ids:
        register(resolved(known[lane_id]), user_config)


def lane_files(lanes: list[Lane], directory: Path) -> tuple[list[tuple[str, Path]], list[Lane]]:
    """The (name, file) of each lane's XML under directory/lane-<id>/, and the lanes with none."""
    found = []
    missing = []
    for lane in lanes:
        files = sorted((directory / f'lane-{lane.id}').glob('*.xml'))
        if len(files) == 1:
            found.append((files[0].stem, files[0]))
        else:
            missing.append(lane)
    return found, missing


def run_report(lanes: list[Lane], directory: Path, out: Path) -> int:
    """Runs tools/report/report.py on what the lanes wrote, and returns the verdict."""
    found, missing = lane_files(lanes, directory)
    status = 0
    if found:
        arguments = [argument for name, file in found for argument in ('--lane', f'{name}={file}')]
        status = subprocess.run([sys.executable, str(REPORT), *arguments, '--out', str(out)],
                                check=False).returncode
    for lane in missing:
        print(f'matrix.py: the lane {lane.id} ({lane.name}) wrote no XML under '
              f'{directory / f"lane-{lane.id}"}: its job failed before b2 ran, or b2 could not '
              'build at all', file=sys.stderr)
    if missing:
        return 2
    return status


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='matrix.py',
                                     description=(__doc__ or '').split('\n', 1)[0])
    commands = parser.add_subparsers(dest='command', required=True)
    default_config = ROOT / '.local/user-config.jam'

    planning = commands.add_parser('plan', help='print the JSON matrix of the lanes')
    planning.add_argument('--library', help='plan the lanes of this library alone')
    planning.add_argument('--user-config', type=Path, default=default_config)

    running = commands.add_parser(
        'lane', help='run one lane of the matrix',
        epilog='After --, more arguments for b2, such as --build-dir=bin/lane-gcc-15.')
    running.add_argument('entry', metavar='LANE', help='an entry of the matrix, as JSON')
    running.add_argument('--user-config', type=Path, default=default_config)
    running.add_argument('--out-dir', type=Path, default=Path('bin/ci'))

    registering = commands.add_parser(
        'register', help="register lanes' toolsets in user-config.jam, the first the default")
    registering.add_argument('ids', nargs='+', metavar='ID', help='a lane id: gcc-14, wasip2')
    registering.add_argument('--user-config', type=Path, default=default_config)

    reporting = commands.add_parser('report', help="merge the lanes' XML into the test matrix")
    reporting.add_argument('--plan', required=True, metavar='MATRIX',
                           help='the matrix plan printed, as JSON')
    reporting.add_argument('--lanes', required=True, type=Path, metavar='DIR')
    reporting.add_argument('--out', required=True, type=Path, metavar='DIR')

    # What follows the first -- goes to b2 as it is: argparse's own reading of -- after a
    # subcommand differs from one Python to the next.
    extra: list[str] = []
    if '--' in arguments:
        extra = arguments[arguments.index('--') + 1:]
        arguments = arguments[:arguments.index('--')]
    options = parser.parse_args(arguments)
    try:
        if options.command == 'plan':
            print(matrix(plan(declared(options.user_config.resolve()), options.library)))
            return 0
        if options.command == 'lane':
            out_dir = options.out_dir if options.out_dir.is_absolute() else ROOT / options.out_dir
            return run_lane(parsed_lane(options.entry), options.user_config.resolve(), out_dir,
                            extra)
        if options.command == 'register':
            register_lanes(options.ids, options.user_config.resolve())
            return 0
        try:
            planned = json.loads(options.plan)['include']
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise Failure(f'--plan is not the matrix plan writes: {error}', 2) from None
        lanes = [parsed_lane(json.dumps(entry)) for entry in planned]
        return run_report(lanes, options.lanes, options.out)
    except Failure as failure:
        print(f'matrix.py: {failure}', file=sys.stderr)
        return failure.status


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
