# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""The lanes of the test report: what one b2 run built and ran, read from the file it wrote with
-a --dump-tests --out-xml, each test and example judged, and the verdict of the lanes.

A test is <library>/<target> and an example <library>/example/<name>, the library being the
directory of libs/ that holds its Jamfile. b2 runs from the superproject's root, as the lane
command does, so <directory> in the file is that root. A test is found by --dump-tests, which
lists it whether or not the lane built it; an example by the <name>.output that webcpp.example
compares. A lane is one toolset: the directory b2 names after it, in which every program of the
lane is built. A lane is named after the target that toolset builds for (native, emscripten,
wasip2, wasip3), or after that directory (clang-darwin-21, gcc-15). A library's own lane on a
target, which webcpp.lane declares, is named <target>.<library>.<lane> (wasip2.wasi.http): its
toolset builds for that target, and it lists the tests of that library alone.

The paths in a file are those of the machine that ran the lane, a CI runner as often as not, and
are never opened: they are matched as text, a backslash read as a slash.
"""

from __future__ import annotations

import html
import posixpath
import re
import textwrap
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

PASS = 'pass'

# What a failure's cell says, from the most significant kind to the least, and what it means.
KINDS = {
    'compile': 'The compiler failed.',
    'compiled': 'The source compiled, and the test expects it not to.',
    'link': 'The linker failed.',
    'linked': 'The program linked, and the test expects it not to.',
    'build': 'A step other than compiling, linking and running failed.',
    'run': 'The program exited with a status other than 0, the example printed other than its '
           '.expected file, or the served component answered other than its .expected file.',
    'ran': 'The program exited with status 0, and the test expects another status.',
    'not run': 'b2 did not take it to the end: a target it needs failed, or the lane was not '
               'built from scratch (b2 -a).',
}

SEVERITY = list(KINDS)

# The kind of a test that expects a step to fail, when that step succeeded.
SUCCEEDED = {'compile': 'compiled', 'link': 'linked', 'run': 'ran'}

# The targets a program is built for (tools/target.jam), which a lane may be named after, and
# the CI knows (tools/ci/matrix.py): spelled here alone.
TARGETS = ('native', 'emscripten', 'wasip2', 'wasip3')

EMPTY = 'the lane built no test and no example'

# What a lane that built something says of a library none of whose programs it built.
UNBUILT = 'the lane built none of its tests and examples'

# A CDATA section that is an element's whole text, the way b2 writes every text. b2 writes it as
# it is, so a ]]> or a byte that is not UTF-8 in a program's output makes the file unreadable as
# XML: a section is read up to the first ]]> that its element's end tag follows.
CDATA = re.compile(r'(<([A-Za-z][\w.-]*)[^<>]*>)<!\[CDATA\[(.*?)\]\]>(</\2>)', re.DOTALL)

# The characters XML 1.0 does not allow, which a program can print.
NOT_XML = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f' + chr(0xFFFE) + chr(0xFFFF) + ']')


def own_lane_name(targets: tuple[str, ...]) -> re.Pattern[str]:
    """The name of an own lane on one of targets: <target>.<library>.<lane> (tools/ci/matrix.py).
    No toolset directory begins with a target and a dot, so the name is never a lane's."""
    return re.compile(rf'({"|".join(map(re.escape, targets))})\.([a-z][a-z0-9_]*)\.(.+)')


OWN_LANE = own_lane_name(TARGETS)

# A toolset the command line names: "toolset=clang-wasip2", as b2 records its arguments.
COMMAND_TOOLSET = re.compile(r'"-{0,2}toolset=([^"]*)"')


class InputError(Exception):
    """An input the report cannot read, or cannot report truthfully, and why."""


@dataclass
class Action:
    """An action b2 ran, as --out-xml records it."""

    # Its rule, as module%rule: clang-darwin%clang-darwin.compile.c++. Empty for b2's own, such
    # as creating a directory.
    name: str
    # The exit status of its command. For a step a test expects to fail, b2 records the status
    # the command had, not the verdict it draws from it.
    status: int
    # The file it built.
    path: str
    command: str
    output: str


@dataclass
class Build:
    """One build of a test or an example in a lane, in a directory of its own: b2 builds one per
    property set the lane asks for."""

    directory: str
    # The file whose action, when it succeeds, says that the build passed: <target>.test, which
    # b2's testing rules write last, or <name>.output, which webcpp.example writes only when the
    # example printed what it should.
    root: str
    # The actions that built one of its files, in the order b2 ran them.
    actions: list[Action] = field(default_factory=list)
    kind: str = PASS
    # The action that explains a failure, or None.
    culprit: Action | None = None


def worst(verdicts: Iterable[str | None]) -> str | None:
    """The verdict of verdicts together, each None for what a lane did not build: the most
    significant kind of failure among them, else pass, else None when nothing was built."""
    built = [verdict for verdict in verdicts if verdict is not None]
    failures = [verdict for verdict in built if verdict != PASS]
    if failures:
        return min(failures, key=SEVERITY.index)
    return PASS if built else None


@dataclass
class Row:
    """A test or an example of a library, as one lane built it."""

    library: str
    example: bool
    name: str
    # run, run-fail, compile, compile-fail, serve (b2's type, as webcpp's rule is named), or
    # example.
    type: str
    # Empty when the lane did not build it.
    builds: list[Build] = field(default_factory=list)

    @property
    def id(self) -> str:
        if self.example:
            return f'{self.library}/example/{self.name}'
        return f'{self.library}/{self.name}'

    def order(self) -> tuple[bool, str]:
        return (self.example, self.name)

    def verdict(self) -> str | None:
        return worst(build.kind for build in self.builds)


@dataclass
class Lane:
    name: str
    # The toolset b2 built it with, as it names its directory (clang-darwin-21), or as the
    # command line names it when the lane built nothing; None when neither says.
    toolset: str | None = None
    rows: dict[str, Row] = field(default_factory=dict)
    # The actions that failed and built no file of a test or an example.
    outside: list[Action] = field(default_factory=list)

    def built(self) -> bool:
        """Whether the lane built a test or an example. An example counts: a library may declare
        a target for its examples alone, and the lane then tests what it declares."""
        return any(row.builds for row in self.rows.values())

    def unbuilt(self) -> list[str]:
        """The libraries whose tests and examples the lane lists and none of which it built,
        sorted; none when the lane built nothing at all, which is a failure of its own. The CI
        puts in a lane only the libraries that declare its target, so such a library is a fault
        that a grey column would hide: a plan gone wrong, or a local lane that names a library
        which does not declare the lane's target."""
        if not self.built():
            return []
        listed = {row.library for row in self.rows.values()}
        built = {row.library for row in self.rows.values() if row.builds}
        return sorted(listed - built)


def step(action: str) -> str:
    """The step an action is, by its rule: compile, link, run, or build for any other. Running
    a program is b2's capture-output and unit-test, webcpp.example's run-and-compare, and
    webcpp.serve's serve-and-compare, which serves a component and sends it its requests."""
    words = set(action.rpartition('%')[2].split('.'))
    if 'compile' in words:
        return 'compile'
    if words & {'link', 'archive'}:
        return 'link'
    if words & {'capture-output', 'run-and-compare', 'unit-test', 'serve-and-compare'}:
        return 'run'
    return 'build'


def judge(build: Build, expects: str | None) -> None:
    """Sets build's kind and culprit. expects is the step its test expects to fail, if any."""
    if any(action.path == build.root and action.status == 0 for action in build.actions):
        return
    for action in build.actions:
        if action.status != 0 and step(action.name) != expects:
            build.kind, build.culprit = step(action.name), action
            return
    for action in build.actions:
        if expects is not None and action.status == 0 and step(action.name) == expects:
            build.kind, build.culprit = SUCCEEDED[expects], action
            return
    build.kind = 'not run'


def target_of(toolset: str) -> str:
    """The target a toolset builds for, by the name b2 gives it or its directory: wasip2 for
    clang-wasip2 and clang-darwin-wasip2, emscripten for emscripten, native for any other."""
    parts = toolset.split('-')
    if parts[0] == 'emscripten':
        return 'emscripten'
    if parts[-1] in ('wasip2', 'wasip3'):
        return parts[-1]
    return 'native'


def slashed(path: str) -> str:
    return path.replace('\\', '/')


def escaped(match: re.Match[str]) -> str:
    """A CDATA section of CDATA's, as escaped text."""
    text = NOT_XML.sub(lambda character: f'\\x{ord(character.group()):02x}', match.group(3))
    return match.group(1) + html.escape(text, quote=False) + match.group(4)


def parse(path: Path) -> ET.Element:
    """The root of the file b2 wrote at path."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise InputError(f'{path}: {error.strerror or error}') from None
    try:
        root = ET.fromstring(CDATA.sub(escaped, data.decode('utf-8', errors='replace')))
    except ET.ParseError as error:
        raise InputError(f'{path}: not XML ({error})') from None
    if root.tag != 'build':
        raise InputError(f'{path}: <{root.tag}> where b2 --out-xml writes <build>')
    return root


def text_of(element: ET.Element, tag: str) -> str:
    return element.findtext(tag) or ''


# A project's location under the superproject's root, in a library: libs/<library>[/...].
IN_LIBRARY = re.compile(r'libs/([^/]+)(?:/.*)?')


def under_root(root: str, location: str) -> str:
    """location, which b2 gives relative to root or absolute, relative to root."""
    root = posixpath.normpath(slashed(root))
    location = slashed(location)
    if location.startswith(root + '/'):
        location = location[len(root) + 1:]
    return posixpath.normpath(location)


def segment_after(directory: str, before: str) -> str | None:
    """The segment of directory right after the segments before, or None."""
    wrapped = f'/{directory}/'
    index = wrapped.rfind(f'/{before}/')
    if index < 0:
        return None
    return wrapped[index + len(before) + 2:].split('/', 1)[0] or None


def closure(graph: dict[tuple[str, str], list[str]], target: str, directory: str) -> set[str]:
    """The files of target, built in directory, and of the targets it needs that are built there
    too, at any depth: those of one test, or of one example."""
    files: set[str] = set()
    pending = [target]
    while pending:
        name = pending.pop()
        file = posixpath.join(directory, name.partition('//')[2])
        if file in files:
            continue
        files.add(file)
        pending += [needed for needed in graph.get((name, directory), [])
                    if (needed, directory) in graph]
    return files


def read_lane(name: str, path: Path) -> Lane:
    """The lane name, from the file b2 wrote at path. Raises InputError when the file cannot be
    read, or does not hold what the lane's name says: one toolset, for the target the name names
    when it names one, and otherwise the toolset whose directory the name is."""
    root = parse(path)
    directory = text_of(root, 'directory')
    lane = Lane(name)

    def row(location: str, example: bool, row_name: str, row_type: str) -> tuple[Row, str]:
        """The row of the program row_name at location, and location under the root."""
        relative = under_root(directory, location)
        library = IN_LIBRARY.fullmatch(relative)
        if library is None:
            raise InputError(f'{path}: {relative} is not in libs/<library>/ of the superproject '
                             f'that b2 ran in, {directory}')
        # Compared without case, as a file system can name files.
        if library.group(1).lower() == 'index':
            raise InputError(f'{path}: a library named {library.group(1)}, whose page would be '
                             'the summary')
        found = Row(library.group(1), example, row_name, row_type)
        return lane.rows.setdefault(found.id, found), relative

    # The tests b2 lists with --dump-tests, by the target that passes them.
    tests: dict[str, Row] = {}
    for element in root.findall('test'):
        target = slashed(text_of(element, 'target'))
        location, separator, file = target.partition('//')
        if not separator or not file.endswith('.test'):
            raise InputError(f'{path}: a <test> whose <target> is {target!r}')
        b2_type = element.get('type') or ''
        tests[target], _ = row(location, False, file[:-len('.test')],
                               b2_type.lower().replace('_', '-'))

    # The targets b2 generated, by name and directory, with the names of those each needs.
    graph: dict[tuple[str, str], list[str]] = {}
    for element in root.findall('targets/target'):
        key = (slashed(text_of(element, 'name')), slashed(text_of(element, 'path')))
        graph.setdefault(key, []).extend(
            slashed(dependency.text or '') for dependency in element.findall(
                'dependencies/dependency'))

    # A build of a test is its <target>.test, in <location>/<target>.test/<toolset>/...; of an
    # example, its <name>.output, in <location>/<toolset>/...
    toolsets: set[str] = set()
    owners: dict[str, list[Build]] = {}
    for target, built_in in graph:
        location, _, file = target.partition('//')
        if target in tests:
            owner, relative = tests[target], under_root(directory, location)
            toolset = segment_after(built_in, f'{relative}/{file}')
        elif file.endswith('.output'):
            owner, relative = row(location, True, file[:-len('.output')], 'example')
            toolset = segment_after(built_in, relative)
        elif file.endswith('.test'):
            raise InputError(f'{path}: b2 built {target}, which no <test> lists: run b2 with '
                             '--dump-tests')
        else:
            continue
        if toolset is None:
            raise InputError(f'{path}: {built_in}, where b2 built {target}, names no toolset')
        toolsets.add(toolset)
        build = Build(built_in, posixpath.join(built_in, file))
        owner.builds.append(build)
        for owned in closure(graph, target, built_in):
            owners.setdefault(owned, []).append(build)

    # A lane that built nothing has no directory, only the toolset its command line names.
    from_directory = bool(toolsets)
    if not toolsets:
        toolsets = {toolset for named in COMMAND_TOOLSET.findall(text_of(root, 'command'))
                    for toolset in named.split(',') if toolset}
    if len(toolsets) > 1:
        raise InputError(f'{path}: the lane {name} is built with {", ".join(sorted(toolsets))}; '
                         'a lane is one toolset')
    lane.toolset = next(iter(toolsets), None)
    own = OWN_LANE.fullmatch(name)
    named_target = own.group(1) if own else name.lower()
    if own:
        others = sorted({row.library for row in lane.rows.values()} - {own.group(2)})
        if others:
            raise InputError(f'{path}: the lane {name} is an own lane of {own.group(2)}, and lists '
                             f'the tests of {", ".join(others)}')
    if lane.toolset is not None and named_target in TARGETS:
        built_for = target_of(lane.toolset)
        if built_for != named_target:
            raise InputError(f'{path}: the lane {name} is built with {lane.toolset}, which '
                             f'builds for {built_for}')
    # Any other name is the directory's: the name a command line gives a toolset (clang) is not
    # the directory b2 builds it in (clang-darwin-21), so a lane that built nothing is not
    # checked, and fails as empty.
    elif from_directory and lane.toolset is not None and name.lower() != lane.toolset.lower():
        raise InputError(f'{path}: the lane {name} is built with {lane.toolset}; name it '
                         f'{lane.toolset}, after the directory b2 builds its toolset in, or '
                         f'{target_of(lane.toolset)}, after its target')

    for element in root.findall('action'):
        try:
            status = int(element.get('status') or '')
        except ValueError:
            raise InputError(f'{path}: an <action> whose status is '
                             f'{element.get("status")!r}') from None
        # b2 indents a command as its actions block is indented.
        command = textwrap.dedent(text_of(element, 'command')).strip('\n')
        action = Action(text_of(element, 'name'), status, slashed(text_of(element, 'path')),
                        command, text_of(element, 'output'))
        builds = owners.get(action.path, [])
        for build in builds:
            build.actions.append(action)
        if not builds and action.status != 0:
            lane.outside.append(action)

    for found in lane.rows.values():
        expects = found.type[:-len('-fail')] if found.type.endswith('-fail') else None
        for build in found.builds:
            judge(build, expects if expects in SUCCEEDED else None)
    return lane


def problems(lane: Lane) -> list[str]:
    """Each failure of lane, named: <lane>: <what>: <kind>."""
    found = []
    if not lane.built():
        found.append(f'{lane.name}: {EMPTY}')
    for library in lane.unbuilt():
        found.append(f'{lane.name}: {library}: {UNBUILT}')
    for row in sorted(lane.rows.values(), key=lambda row: (row.library, row.order())):
        verdict = row.verdict()
        if verdict not in (None, PASS):
            found.append(f'{lane.name}: {row.id}: {verdict}')
    for action in lane.outside:
        found.append(f'{lane.name}: {action.path}: {step(action.name)}, outside every test and '
                     'example')
    return found


def exit_status(lanes: list[Lane]) -> int:
    """0 when every lane built something of every library it lists and everything it built
    passed, else 1."""
    return 1 if any(problems(lane) for lane in lanes) else 0
