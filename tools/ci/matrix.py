#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""The CI's lanes: which ones run, each lane's b2 command, and the report that merges them.

Usage: matrix.py plan [--library NAME] [--user-config FILE]
       matrix.py own-lanes [--library NAME] [--user-config FILE]
       matrix.py lane LANE [--user-config FILE] [--out-dir DIR] [-- B2-ARGUMENT ...]
       matrix.py own-lane OWN-LANE [--user-config FILE] [--out-dir DIR] [-- B2-ARGUMENT ...]
       matrix.py register ID [ID ...] [--user-config FILE]
       matrix.py report --plan MATRIX [--own-lanes MATRIX] --lanes DIR --out DIR

plan runs `b2 -d0 declared-targets` from the superproject's root and prints the JSON matrix of
the lanes to run, {"include": [LANE, ...]}: one lane per compiler of LANES for each target a
library declares, of the library --library names, else of every library. A lane builds the tests
and examples of the libraries that declare its target, and no other: a lane of a target no
library declares would build nothing. A target the CI has no lane for (emscripten, until emsdk
is pinned: AGENTS.md, Roadmap) is a failure, never a lane left out.

own-lanes runs `b2 -d0 declared-lanes` and prints the JSON matrix of the libraries' own lanes, of
the library --library names, else of every library; empty, {"include":[]}, when none declares one,
and a failure when --library names no library of libs/, as plan's does. An own lane is one a
library declares with webcpp.lane, such as its oracle, or its served tests. One that names no
target is the entry {"library": L, "lane": N, "directory": D}, which the CI runs as
`b2 -a toolset=clang-18 D//N`, whose exit status is its verdict: it writes no XML, so it is no
column of the report. One that names targets is an entry per target T, which adds "platform": T,
the "id" <T>.<L>.<D under libs/L/, its slashes as dots>.<N> (wasip2.wasi.test.http), and the "os"
and "wasm" of the lane whose setup it shares: T's own lane, and the oracle's Clang 18 for native.
It runs as that lane runs, with --dump-tests and --out-xml, and its XML, <id>.xml, is a column of
the report under its id, which tools/report/report.py checks against the toolset it was built
with and the library whose tests it lists. A target the CI cannot set up an own lane on,
emscripten until emsdk is pinned (AGENTS.md, Roadmap), fails the listing by name: an own lane is
never run natively in its place.

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

own-lane runs one own lane, OWN-LANE being one entry of the own-lanes matrix as JSON: it registers
the toolset of the lane it shares (Clang 18 when it names no target), prints its b2 command and runs
it. Without a target, b2's exit status is its verdict; with one, it writes DIR/<id>.xml, which the
job uploads, and fails only when b2 cannot build at all, as a lane does.

register adds the toolsets of the lanes named by id to the user-config.jam, in their order, the
first being b2's default toolset: what the CI's tools job builds the tests of the tools with. A
WASI lane's toolset is the region of tools/ci/wasi-sdk.jam between `# tag::<target>[]` and
`# end::<target>[]`, after its region wasi-sdk, which names wasi-sdk's directory and gives it to
the build as WASI_SDK, read as this module loads, with wasi-sdk's directory, quoted, in place of
/path/to/wasi-sdk and of $(wasi-sdk): the lines the documentation shows. Each block of lines, the
regions apart, is added once. A wasi-sdk.jam without them stops every command, naming the file
and the tag.

report merges what the lanes of the matrix MATRIX wrote under DIR, one directory per lane,
lane-<id>/<lane>.xml (as the CI downloads the lanes' artifacts), with tools/report/report.py into
--out, and what the own lanes on a target of --own-lanes wrote, lane-<id>/<id>.xml. A lane of
either that wrote no XML, as when its job failed before b2 ran, fails the report by name: the
matrix would otherwise be green without it.

The user-config.jam is .local/user-config.jam by default, where tools/ci/actions/boost writes the
`using boost` line. Exit 0 on success; 1 when b2 or the report fails; 2 on a usage error, a
--library that names no library, a target with no lane, a line of declared-lanes that is no own
lane, an own lane on a target the CI cannot set up, a planned lane that wrote no XML, missing from
the report, or a tools/ci/wasi-sdk.jam that does not hold the WASI toolsets.
"""

from __future__ import annotations

import argparse
import json
import os
import re
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

# The lines that register each WASI toolset against $(wasi-sdk), each target's between its tag::
# and end:: lines.
WASI_SDK_JAM = ROOT / 'tools/ci/wasi-sdk.jam'

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
    # The lines that register the toolset in user-config.jam, in blocks an empty line apart, each
    # added once. {wasi_sdk} is wasi-sdk's absolute directory, quoted.
    using: str
    # The compiler whose major version is {version}, or nothing.
    detect: str = ''
    options: tuple[str, ...] = ()
    # Whether the lane needs wasi-sdk and wasmtime.
    wasm: bool = False
    # The b2 projects it builds: libs/<library>/test and libs/<library>/example of each library.
    projects: tuple[str, ...] = field(default_factory=tuple)


class Failure(Exception):
    """What stops a command, said to the user, with the exit status it gives."""

    def __init__(self, message: str, status: int = 1) -> None:
        super().__init__(message)
        self.status = status


# The directory the region wasi-sdk of WASI_SDK_JAM names, which register writes wasi-sdk's own in
# place of.
PLACEHOLDER = '/path/to/wasi-sdk'


def region_lines(tag: str, needed: str, what: str) -> str:
    """The lines of WASI_SDK_JAM's region tag, which must hold needed and say what, with
    {wasi_sdk} in place of PLACEHOLDER and of $(wasi-sdk)."""
    try:
        text = WASI_SDK_JAM.read_text()
    except OSError as error:
        raise Failure(f'cannot read {WASI_SDK_JAM}: {error.strerror}', 2) from error
    found = re.search(rf'^# tag::{tag}\[\]\n(.*?)^# end::{tag}\[\]$', text,
                      re.MULTILINE | re.DOTALL)
    if found is None or needed not in found.group(1):
        raise Failure(f'{WASI_SDK_JAM} holds no lines tag::{tag}[] to end::{tag}[] that {what}', 2)
    lines = found.group(1).rstrip('\n')
    return lines.replace(PLACEHOLDER, '{wasi_sdk}').replace('$(wasi-sdk)', '{wasi_sdk}')


def toolset_lines(target: str) -> str:
    """The lines that register target's toolset: the region wasi-sdk of WASI_SDK_JAM, then the
    region target, an empty line between the two blocks, with {wasi_sdk} in place of wasi-sdk's
    directory."""
    sdk = region_lines('wasi-sdk', PLACEHOLDER, f'name wasi-sdk\'s directory, {PLACEHOLDER}')
    toolset = region_lines(target, '$(wasi-sdk)', f'register clang-{target} against $(wasi-sdk)')
    return f'{sdk}\n\n{toolset}'


# Read as the module loads: a wasi-sdk.jam that does not hold them stops it, naming the file and
# the tag, before any command runs.
try:
    WASM_USING = {target: toolset_lines(target) for target in ('wasip2', 'wasip3')}
except Failure as unreadable:
    print(f'matrix.py: {unreadable}', file=sys.stderr)
    sys.exit(unreadable.status)


def wasm_lane(target: str) -> Lane:
    return Lane(id=target, name=f'wasm32-{target} (wasi-sdk 34, wasmtime 47.0.3)',
                os='ubuntu-24.04', target=target, lane=target, toolset=f'clang-{target}',
                using=WASM_USING[target], options=('testing.launcher=wasmtime',), wasm=True)


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


def environment() -> dict[str, str]:
    """This process's environment without the variables the Jamroot refuses."""
    return {name: value for name, value in os.environ.items() if name not in COMPILER_PATHS}


def printed(target: str, user_config: Path) -> list[str]:
    """The lines `b2 -d0 <target>` prints, without b2's own warnings."""
    command = ['b2', f'--user-config={user_config}', '-d0', target]
    try:
        completed = subprocess.run(command, cwd=ROOT, env=environment(), capture_output=True,
                                   text=True, check=False)
    except OSError as error:
        raise Failure(f'cannot run b2: {error.strerror}') from error
    if completed.returncode != 0:
        raise Failure(f'{completed.stdout}{completed.stderr}{shlex.join(command)} exited '
                      f'{completed.returncode}')
    # b2's own warnings, such as the default toolset it configures when user-config.jam
    # registers none, as the plan job's does; -d0 does not hide them.
    return [line for line in completed.stdout.splitlines() if not line.startswith('warning: ')]


def declared(user_config: Path) -> list[tuple[str, str]]:
    """The pairs (library, target) `b2 declared-targets` prints."""
    pairs = []
    for line in printed('declared-targets', user_config):
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


# A line of `b2 declared-lanes`: a library, the name of one of its lanes, the directory of the
# Jamfile that declares it, under the library's test or example directory, and the target it runs
# on, when it names one. The job runs `b2 -a <directory>//<lane>` from these words, so each is
# checked whole.
OWN_LANE = re.compile(r'([a-z][a-z0-9_]*) ([A-Za-z0-9][A-Za-z0-9_.-]*) (libs/[^ ]+)(?: ([^ ]+))?')

# The lane whose toolset, options and setup an own lane shares, by the target it runs on: the
# target's own lane, and Clang 18's, the oracle's, for native and for an own lane that names no
# target (None). Each runs on Linux x86-64. emscripten has none until emsdk is pinned (AGENTS.md,
# Roadmap).
OWN_LANE_BASES = {None: 'clang-18', 'native': 'clang-18', 'wasip2': 'wasip2', 'wasip3': 'wasip3'}


@dataclass(frozen=True)
class OwnLane:
    """An own lane, as a line of `b2 declared-lanes` names it."""

    library: str
    lane: str
    directory: str
    # The target it runs on, or None for one that names none.
    target: str | None = None

    @property
    def id(self) -> str:
        """Its name in the report, its XML's and its artifact's: <target>.<library>.<directory
        under libs/<library>/, its slashes as dots>.<lane>, which no lane of LANES is named, so
        that its column stands beside the target's own."""
        under = self.directory.removeprefix(f'libs/{self.library}/').replace('/', '.')
        return f'{self.target}.{self.library}.{under}.{self.lane}'

    @property
    def name(self) -> str:
        """What the CI shows for its job."""
        words = [self.library, self.lane, self.directory, *([self.target] if self.target else [])]
        return f'Own lane ({", ".join(words)})'

    @property
    def request(self) -> str:
        """The b2 target that runs it."""
        return f'{self.directory}//{self.lane}'


def parsed_own_lanes(text: str) -> list[OwnLane]:
    """The own lanes of the lines text holds, as `b2 declared-lanes` prints them."""
    lanes = []
    for line in text.splitlines():
        found = OWN_LANE.fullmatch(line)
        if found is None:
            raise Failure(f'b2 declared-lanes printed {line!r}, not "<library> <lane> '
                          '<directory> [<target>]"', 2)
        library, lane, directory, target = found.groups()
        under = re.fullmatch(rf'libs/{library}/(test|example)(/[A-Za-z0-9_.-]+)*', directory)
        if under is None or '/..' in directory or '/./' in f'{directory}/':
            raise Failure(f'b2 declared-lanes printed {line!r}, whose directory is not in '
                          f'libs/{library}/test or libs/{library}/example', 2)
        if target is not None and target not in KNOWN:
            raise Failure(f'b2 declared-lanes printed {line!r}: {target} is not a target; the '
                          f'targets are {", ".join(KNOWN)}', 2)
        lanes.append(OwnLane(library, lane, directory, target))
    return lanes


def own_lane_base(target: str | None) -> Lane:
    """The lane an own lane on target, or on none, shares its toolset and its setup with."""
    known = {lane.id: lane for lane in LANES}
    if target not in OWN_LANE_BASES:
        raise Failure(f"an own lane on {target} needs the {target} lane's setup, which comes when "
                      'emsdk is pinned (AGENTS.md, Roadmap)', 2)
    return known[OWN_LANE_BASES[target]]


def own_lane_entry(own: OwnLane) -> dict[str, str | bool]:
    """The own lane as an entry of the own-lanes matrix: its three words alone when it names no
    target, as before targets were; else its target, its id, and the image and the setup of the
    lane it shares."""
    entry: dict[str, str | bool] = {'library': own.library, 'lane': own.lane,
                                    'directory': own.directory}
    if own.target is None:
        return entry
    base = own_lane_base(own.target)
    return {**entry, 'platform': own.target, 'id': own.id, 'os': base.os, 'wasm': base.wasm}


def own_lanes(user_config: Path, library: str | None) -> list[OwnLane]:
    """The own lanes the libraries declare, of library alone when it is given, which must be a
    library of libs/: one that declares no own lane has none, one that does not exist fails. An
    own lane on a target the CI cannot set up fails, by name."""
    if library is not None and not (ROOT / 'libs' / library / 'build.jam').is_file():
        raise Failure(f'libs/{library} is no library of libs/ (a directory with a build.jam)', 2)
    lanes = parsed_own_lanes('\n'.join(printed('declared-lanes', user_config)))
    lanes = [lane for lane in lanes if library is None or lane.library == library]
    for own in lanes:
        try:
            own_lane_base(own.target)
        except Failure as failure:
            raise Failure(f'{own.library} declares its own lane {own.lane} in {own.directory} on '
                          f'{own.target}, which the CI cannot set up yet: {failure}', 2) from None
    return lanes


def parsed_own_lane(text: str) -> OwnLane:
    """The OwnLane of an entry of the own-lanes matrix, given as JSON, read again from its words
    as `b2 declared-lanes` prints them, so that each is checked as the listing checks it."""
    try:
        entry = json.loads(text)
        words = [entry['library'], entry['lane'], entry['directory']]
        if 'platform' in entry:
            words.append(entry['platform'])
        if not all(isinstance(word, str) for word in words):
            raise TypeError('a word that is not a string')
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise Failure(f'the own lane is not an entry of the matrix own-lanes writes: {error}',
                      2) from None
    lanes = parsed_own_lanes(' '.join(words))
    if len(lanes) != 1:
        raise Failure(f'the own lane {text} is not one entry of the matrix own-lanes writes', 2)
    return lanes[0]


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
    # Quoted, one word of Jam however many spaces the checkout's path holds; the quotes end
    # where the directory does, so that <archiver>"<wasi-sdk>"/bin/llvm-ar stays one word too.
    wasi_sdk = f'"{(ROOT / WASI_SDK).as_posix()}"'

    def fill(text: str) -> str:
        return text.replace('{version}', version).replace('{wasi_sdk}', wasi_sdk)

    return replace(lane, lane=fill(lane.lane), toolset=fill(lane.toolset), using=fill(lane.using))


def holds(text: str, lines: str) -> bool:
    """Whether text holds lines, whole lines one after the other."""
    held, wanted = text.splitlines(), lines.splitlines()
    return any(held[start:start + len(wanted)] == wanted
               for start in range(len(held) - len(wanted) + 1))


def register(lane: Lane, user_config: Path) -> None:
    """Adds each block of the lane's using lines, an empty line apart, to user_config, unless it
    holds those lines already: the region wasi-sdk, which two WASI lanes share, is added once."""
    text = user_config.read_text() if user_config.is_file() else ''
    added = text
    for block in lane.using.split('\n\n'):
        if holds(added, block):
            continue
        if added and not added.endswith('\n'):
            added += '\n'
        added += f'{block}\n'
    if added == text:
        return
    user_config.parent.mkdir(parents=True, exist_ok=True)
    user_config.write_text(added)


def lane_command(lane: Lane, user_config: Path, xml: Path, extra: list[str]) -> list[str]:
    """The lane command: b2, from scratch, writing xml, for the lane's toolset and projects."""
    return ['b2', f'--user-config={user_config}', '-a', '--dump-tests', f'--out-xml={xml}',
            f'toolset={lane.toolset}', *lane.options, *extra, *lane.projects]


def own_lane_command(own: OwnLane, user_config: Path, xml: Path | None,
                     extra: list[str]) -> list[str]:
    """The own lane's command: b2, from scratch, on <directory>//<lane>; with Clang 18 when it
    names no target, and otherwise with the toolset and the options of the lane it shares,
    writing xml, as that lane does."""
    base = own_lane_base(own.target)
    if own.target is None:
        return ['b2', f'--user-config={user_config}', '-a', f'toolset={base.toolset}', *extra,
                own.request]
    return ['b2', f'--user-config={user_config}', '-a', '--dump-tests', f'--out-xml={xml}',
            f'toolset={base.toolset}', *base.options, *extra, own.request]


def run_b2(label: str, command: list[str]) -> int:
    """Prints command after label, runs it from the superproject's root, and returns its exit
    status."""
    print(f'{label}: {shlex.join(command)}', flush=True)
    try:
        return subprocess.run(command, cwd=ROOT, env=environment(), check=False).returncode
    except OSError as error:
        raise Failure(f'cannot run b2: {error.strerror}') from error


def recorded(label: str, name: str, xml: Path, status: int) -> int:
    """Writes the job's outputs, the lane's name and its XML only when b2 wrote it, so that the
    upload step runs only on a file that is there; and fails when b2, which ran with --out-xml,
    could not build at all or wrote no XML."""
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a') as output:
            output.write(f'lane={name}\n')
            if xml.is_file():
                output.write(f'xml={xml.as_posix()}\n')
    if status != 0:
        raise Failure(f'{label}: b2 exited {status}; with --out-xml it does so only when it '
                      'cannot build at all, a test failing is the report\'s to say')
    if not xml.is_file():
        raise Failure(f'{label}: b2 wrote no {xml}')
    return 0


def fresh_xml(out_dir: Path, name: str) -> Path:
    """out_dir/<name>.xml, with no file left there by an earlier run."""
    out_dir.mkdir(parents=True, exist_ok=True)
    xml = out_dir / f'{name}.xml'
    if xml.exists():
        xml.unlink()
    return xml


def run_lane(lane: Lane, user_config: Path, out_dir: Path, extra: list[str]) -> int:
    """Runs the lane, and returns its exit status."""
    lane = resolved(lane)
    register(lane, user_config)
    xml = fresh_xml(out_dir, lane.lane)
    status = run_b2(f'lane {lane.lane}', lane_command(lane, user_config, xml, extra))
    return recorded(f'lane {lane.lane}', lane.lane, xml, status)


def run_own_lane(own: OwnLane, user_config: Path, out_dir: Path, extra: list[str]) -> int:
    """Runs the own lane, and returns its exit status."""
    register(resolved(own_lane_base(own.target)), user_config)
    if own.target is None:
        label = f'own lane {own.request}'
        status = run_b2(label, own_lane_command(own, user_config, None, extra))
        if status != 0:
            raise Failure(f'{label}: b2 exited {status}')
        return 0
    xml = fresh_xml(out_dir, own.id)
    label = f'own lane {own.id}'
    status = run_b2(label, own_lane_command(own, user_config, xml, extra))
    return recorded(label, own.id, xml, status)


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

    owning = commands.add_parser('own-lanes',
                                 help="print the JSON matrix of the libraries' own lanes")
    owning.add_argument('--library', help='list the own lanes of this library alone')
    owning.add_argument('--user-config', type=Path, default=default_config)

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

    own_running = commands.add_parser(
        'own-lane', help='run one own lane of the own-lanes matrix',
        epilog='After --, more arguments for b2, such as --build-dir=bin/lane-http.')
    own_running.add_argument('entry', metavar='OWN-LANE',
                             help='an entry of the own-lanes matrix, as JSON')
    own_running.add_argument('--user-config', type=Path, default=default_config)
    own_running.add_argument('--out-dir', type=Path, default=Path('bin/ci'))

    reporting = commands.add_parser('report', help="merge the lanes' XML into the test matrix")
    reporting.add_argument('--plan', required=True, metavar='MATRIX',
                           help='the matrix plan printed, as JSON')
    reporting.add_argument('--own-lanes', default='{"include":[]}', metavar='MATRIX',
                           help='the matrix own-lanes printed, as JSON')
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
        if options.command == 'own-lanes':
            listed = [own_lane_entry(own)
                      for own in own_lanes(options.user_config.resolve(), options.library)]
            print(json.dumps({'include': listed}, separators=(',', ':')))
            return 0
        if options.command in ('lane', 'own-lane'):
            out_dir = options.out_dir if options.out_dir.is_absolute() else ROOT / options.out_dir
            if options.command == 'lane':
                return run_lane(parsed_lane(options.entry), options.user_config.resolve(),
                                out_dir, extra)
            return run_own_lane(parsed_own_lane(options.entry), options.user_config.resolve(),
                                out_dir, extra)
        if options.command == 'register':
            register_lanes(options.ids, options.user_config.resolve())
            return 0
        try:
            planned = json.loads(options.plan)['include']
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise Failure(f'--plan is not the matrix plan writes: {error}', 2) from None
        try:
            owned = json.loads(options.own_lanes)['include']
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise Failure(f'--own-lanes is not the matrix own-lanes writes: {error}', 2) from None
        lanes = [parsed_lane(json.dumps(entry)) for entry in planned]
        # An own lane on a target writes XML as a lane does, under its id; one that names none
        # writes none, and its job is its verdict.
        for own in (parsed_own_lane(json.dumps(entry)) for entry in owned):
            if own.target is not None:
                lanes.append(replace(own_lane_base(own.target), id=own.id, name=own.name,
                                     lane=own.id))
        return run_report(lanes, options.lanes, options.out)
    except Failure as failure:
        print(f'matrix.py: {failure}', file=sys.stderr)
        return failure.status


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
