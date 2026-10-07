#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Writes webcpp's test matrix from the files b2 wrote for the CI lanes, and gives their verdict.

Usage: report.py --lane NAME=FILE [--lane NAME=FILE ...] --out DIR

Each FILE is what one lane's b2 run wrote with -a --dump-tests --out-xml=FILE (the lane command
the Jamroot documents), and NAME is the lane's column: letters, digits, '.', '_' and '-'. With
--out-xml, b2 exits 0 even when a test fails: the verdict is this script's exit status. It writes
into DIR, which it makes if need be:

  index.html          the libraries by lanes;
  <library>.html      a library's tests and examples by lanes;
  output/<lane>/...   what b2 captured of each failure, which the failure's cell links to.

A test is <library>/<target> and an example <library>/example/<name>, the library being the
directory of libs/ that holds its Jamfile. A cell is green when every build of it in the lane
passed, red with the kind of its most significant failure, and grey (n/a) when the lane did not
build it: <build>no, because it does not declare the lane's target. A library's cell sums its
tests and examples up the same way.

Exit 0 when every lane built something and everything it built passed; 1 when a test or an
example failed, an action outside every test and example failed, or a lane built nothing, each
named on the standard error; 2 when an input cannot be read, each named, and then nothing is
written, or when the pages cannot be written.

The paths in a file are those of the machine that ran the lane, a CI runner as often as not, and
are never opened: the report matches them as text, reading a backslash as a slash, and shows the
commands and the output as b2 recorded them.
"""

from __future__ import annotations

import argparse
import html
import posixpath
import re
import sys
import textwrap
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

PASS = 'pass'

# What a failure's cell says, from the most significant kind to the least, and what it means.
KINDS = {
    'compile': 'The compiler failed.',
    'compiled': 'The source compiled, and the test expects it not to.',
    'link': 'The linker failed.',
    'linked': 'The program linked, and the test expects it not to.',
    'build': 'A step other than compiling, linking and running failed.',
    'run': 'The program exited with a status other than 0, or the example printed other than '
           'its .expected file.',
    'ran': 'The program exited with status 0, and the test expects another status.',
    'not run': 'b2 did not take it to the end: a target it needs failed, or the lane was not '
               'built from scratch (b2 -a).',
}

SEVERITY = list(KINDS)

# The kind of a test that expects a step to fail, when that step succeeded.
SUCCEEDED = {'compile': 'compiled', 'link': 'linked', 'run': 'ran'}

NOT_BUILT = 'Not built for this lane: it does not declare the lane\'s target.'

EMPTY = 'the lane built no test and no example'

OWN_SITE = 'https://github.com/webcpporg/'

LANE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')

# A CDATA section that is an element's whole text, the way b2 writes every text. b2 writes it as
# it is, so a ]]> or a byte that is not UTF-8 in a program's output makes the file unreadable as
# XML: a section is read up to the first ]]> that its element's end tag follows.
CDATA = re.compile(r'(<([A-Za-z][\w.-]*)[^<>]*>)<!\[CDATA\[(.*?)\]\]>(</\2>)', re.DOTALL)

# The characters XML 1.0 does not allow, which a program can print.
NOT_XML = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]')


class Unreadable(Exception):
    """An input the report cannot read, and why."""


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


@dataclass
class Row:
    """A test or an example of a library, as one lane built it."""

    library: str
    example: bool
    name: str
    # run, run-fail, compile, compile-fail (b2's type, as webcpp's rule is named), or example.
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
        """pass, the most significant kind of failure among its builds, or None when the lane
        did not build it."""
        failures = [build.kind for build in self.builds if build.kind != PASS]
        if failures:
            return min(failures, key=SEVERITY.index)
        return PASS if self.builds else None


@dataclass
class Lane:
    name: str
    rows: dict[str, Row] = field(default_factory=dict)
    # The actions that failed and built no file of a test or an example.
    outside: list[Action] = field(default_factory=list)

    def built(self) -> bool:
        return any(row.builds for row in self.rows.values())


def step(action: str) -> str:
    """The step an action is, by its rule: compile, link, run, or build for any other."""
    words = set(action.rpartition('%')[2].split('.'))
    if 'compile' in words:
        return 'compile'
    if words & {'link', 'archive'}:
        return 'link'
    if words & {'capture-output', 'run-and-compare', 'unit-test'}:
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
        raise Unreadable(f'{path}: {error.strerror or error}') from None
    try:
        root = ET.fromstring(CDATA.sub(escaped, data.decode('utf-8', errors='replace')))
    except ET.ParseError as error:
        raise Unreadable(f'{path}: not XML ({error})') from None
    if root.tag != 'build':
        raise Unreadable(f'{path}: <{root.tag}> where b2 --out-xml writes <build>')
    return root


def text_of(element: ET.Element, tag: str) -> str:
    return element.findtext(tag) or ''


def library_of(directory: str, location: str) -> str | None:
    """The library of the project at location, which b2 gives relative to directory, where it
    ran: the directory of libs/ that holds it. None when there is none."""
    parts = posixpath.normpath(posixpath.join(slashed(directory), slashed(location))).split('/')
    found = [index for index, part in enumerate(parts[:-1]) if part == 'libs']
    return parts[found[-1] + 1] if found else None


def file_of(directory: str, target: str) -> str:
    """The file of the target b2 names <location>//<name>, built in directory."""
    return posixpath.join(directory, target.partition('//')[2])


def closure(graph: dict[tuple[str, str], list[str]], target: str, directory: str) -> set[str]:
    """The files of target, built in directory, and of the targets it needs that are built there
    too, at any depth: those of one test, or of one example."""
    files: set[str] = set()
    pending = [target]
    while pending:
        name = pending.pop()
        file = file_of(directory, name)
        if file in files:
            continue
        files.add(file)
        pending += [needed for needed in graph.get((name, directory), [])
                    if (needed, directory) in graph]
    return files


def read_lane(name: str, path: Path) -> Lane:
    """The lane name, from the file b2 wrote at path."""
    root = parse(path)
    directory = text_of(root, 'directory')
    lane = Lane(name)

    def row(location: str, example: bool, row_name: str, row_type: str) -> Row:
        library = library_of(directory, location)
        if library is None:
            raise Unreadable(f'{path}: {location} is in no directory of libs/')
        # Compared without case, as a file system can name files.
        if library.lower() == 'index':
            raise Unreadable(f'{path}: a library named {library}, whose page would be the '
                             'summary')
        found = Row(library, example, row_name, row_type)
        return lane.rows.setdefault(found.id, found)

    # The tests b2 lists with --dump-tests, by the target that passes them.
    tests: dict[str, Row] = {}
    for element in root.findall('test'):
        target = slashed(text_of(element, 'target'))
        location, separator, file = target.partition('//')
        if not separator or not file.endswith('.test'):
            raise Unreadable(f'{path}: a <test> whose <target> is {target!r}')
        b2_type = element.get('type') or ''
        tests[target] = row(location, False, file[:-len('.test')],
                            b2_type.lower().replace('_', '-'))

    # The targets b2 generated, by name and directory, with the names of those each needs.
    graph: dict[tuple[str, str], list[str]] = {}
    for element in root.findall('targets/target'):
        key = (slashed(text_of(element, 'name')), slashed(text_of(element, 'path')))
        graph.setdefault(key, []).extend(
            slashed(dependency.text or '') for dependency in element.findall(
                'dependencies/dependency'))

    # A build of a test is its <target>.test; of an example, its <name>.output.
    owners: dict[str, list[Build]] = {}
    for target, built_in in graph:
        location, _, file = target.partition('//')
        if target in tests:
            owner = tests[target]
        elif file.endswith('.output'):
            owner = row(location, True, file[:-len('.output')], 'example')
        elif file.endswith('.test'):
            raise Unreadable(f'{path}: b2 built {target}, which no <test> lists: run b2 with '
                             '--dump-tests')
        else:
            continue
        build = Build(built_in, file_of(built_in, target))
        owner.builds.append(build)
        for owned in closure(graph, target, built_in):
            owners.setdefault(owned, []).append(build)

    for element in root.findall('action'):
        try:
            status = int(element.get('status') or '')
        except ValueError:
            raise Unreadable(f'{path}: an <action> whose status is '
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
    for row in sorted(lane.rows.values(), key=lambda row: (row.library, row.order())):
        verdict = row.verdict()
        if verdict not in (None, PASS):
            found.append(f'{lane.name}: {row.id}: {verdict}')
    for action in lane.outside:
        found.append(f'{lane.name}: {action.path}: {step(action.name)}, outside every test and '
                     'example')
    return found


# The pages.

STYLE = """
:root {
  --bg: #ffffff; --fg: #1f2328; --muted: #59636e; --line: #d1d9e0; --raised: #f6f8fa;
  --link: #0969da; --pass-bg: #d3f3dc; --pass-fg: #0f5a26; --fail-bg: #cf222e;
  --fail-fg: #ffffff; --na-bg: #eceff2; --na-fg: #6e7781;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117; --fg: #e6edf3; --muted: #9198a1; --line: #30363d; --raised: #151b23;
    --link: #4493f8; --pass-bg: #163d24; --pass-fg: #7ee2a0; --fail-bg: #c4272a;
    --fail-fg: #ffffff; --na-bg: #21262d; --na-fg: #8b949e;
  }
}
*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial,
    sans-serif;
}
/* Only the sides: main and footer set their own top and bottom. */
.wrap { max-width: 1120px; margin: 0 auto; padding-left: 16px; padding-right: 16px; }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
code, pre { font-family: var(--mono); font-size: 13px; }
code { overflow-wrap: anywhere; }
.bar { background: var(--raised); border-bottom: 1px solid var(--line); }
.bar nav {
  display: flex; flex-wrap: wrap; gap: 4px 8px; padding-top: 10px; padding-bottom: 10px;
  font-size: 14px;
}
.bar nav span { color: var(--muted); }
.bar nav .brand { color: var(--fg); font-weight: 700; }
main { padding-top: 28px; padding-bottom: 40px; }
h1 { font-size: 26px; line-height: 1.25; margin: 0 0 14px; overflow-wrap: anywhere; }
h1 code { font-size: 0.85em; }
h2 { font-size: 18px; line-height: 1.3; margin: 32px 0 10px; overflow-wrap: anywhere; }
h2 code { font-size: 14px; }
h3 { font-size: 13px; margin: 16px 0 6px; color: var(--muted); }
p { margin: 0 0 12px; }
.verdict {
  margin: 0 0 24px; padding: 10px 14px; border-radius: 6px; border-left: 4px solid var(--na-fg);
  background: var(--raised);
}
.verdict.passing { border-left-color: var(--pass-fg); background: var(--pass-bg); }
.verdict.failing { border-left-color: var(--fail-bg); }
.problems ul { margin: 0 0 24px; padding-left: 20px; }
.problems li { margin: 4px 0; overflow-wrap: anywhere; }
/* The table scrolls inside its frame when it is wider than the page. */
.scroll {
  width: fit-content; max-width: 100%; overflow-x: auto; margin: 0 0 8px;
  border: 1px solid var(--line); border-radius: 6px;
}
.matrix { border-collapse: separate; border-spacing: 0; }
.matrix th, .matrix td {
  padding: 7px 12px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap;
}
.matrix tbody tr:last-child > * { border-bottom: 0; }
.matrix thead th {
  background: var(--raised); color: var(--muted); font-size: 12px; font-weight: 600;
  vertical-align: bottom;
}
.matrix .name {
  position: sticky; left: 0; z-index: 1; background: var(--bg);
  border-right: 1px solid var(--line);
}
.matrix thead .name { background: var(--raised); z-index: 2; }
.matrix tbody .name { font-family: var(--mono); font-size: 13px; font-weight: 500; }
/* A long name wraps on a narrow screen, so that the column stuck at the left leaves room
   for the lanes: a cell ignores max-width, what it holds does not. */
.matrix tbody .name > * {
  display: block; width: max-content; max-width: 40vw; white-space: normal;
  overflow-wrap: anywhere;
}
.matrix .type { color: var(--muted); font-size: 13px; }
.matrix .lane { text-align: center; font-family: var(--mono); color: var(--fg); }
.matrix .lane.empty, .matrix .lane.outside { color: var(--fail-bg); }
.matrix .lane.empty::after, .matrix .lane.outside::after {
  display: block; font: 700 10px/1.4 system-ui, sans-serif; letter-spacing: 0.04em;
  text-transform: uppercase;
}
.matrix .lane.empty::after { content: "empty"; }
.matrix .lane.outside::after { content: "outside failure"; }
.matrix td.cell {
  padding: 0; min-width: 88px; text-align: center; font-size: 13px; font-weight: 600;
  border-left: 1px solid var(--bg);
}
.matrix td.cell > * { display: block; padding: 7px 12px; }
.matrix td.cell a { color: inherit; }
.pass { background: var(--pass-bg); color: var(--pass-fg); }
.fail { background: var(--fail-bg); color: var(--fail-fg); }
.na { background: var(--na-bg); color: var(--na-fg); font-weight: 400; }
.tag {
  display: inline-block; min-width: 72px; padding: 1px 8px; border-radius: 4px;
  text-align: center; font-size: 12px; font-weight: 600; line-height: 1.6;
  vertical-align: 0.1em;
}
.legend dl { display: grid; grid-template-columns: max-content 1fr; gap: 8px 14px; margin: 0; }
.legend dl div { display: contents; }
.legend dd { margin: 0; color: var(--muted); font-size: 14px; }
.build { margin-top: 28px; border-top: 1px solid var(--line); }
.build h2 { margin-top: 20px; font-size: 15px; font-weight: 600; }
.build h2 code { font-size: 13px; }
.facts {
  display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 4px 14px;
  margin: 0 0 4px; font-size: 14px;
}
.facts dt { color: var(--muted); }
.facts dd { margin: 0; }
pre {
  margin: 0; padding: 12px 14px; background: var(--raised); border: 1px solid var(--line);
  border-radius: 6px; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.45;
}
details { margin-top: 12px; }
summary { cursor: pointer; color: var(--muted); font-size: 13px; }
summary + pre { margin-top: 6px; }
footer {
  border-top: 1px solid var(--line); padding: 16px 0 28px; color: var(--muted);
  font-size: 13px;
}
"""


def e(text: str) -> str:
    return html.escape(text, quote=True)


def plural(count: int, word: str) -> str:
    return f'{count} {word}' if count == 1 else f'{count} {word}s'


def page_of(library: str) -> str:
    return f'{quote(library, safe="")}.html'


def output_of(lane: Lane, row: Row) -> str:
    """The page of row's failure in lane, relative to DIR."""
    category = 'example' if row.example else 'test'
    return (f'output/{lane.name}/{quote(row.library, safe="")}/'
            f'{category}-{quote(row.name, safe="")}.html')


def outside_of(lane: Lane) -> str:
    """The page of lane's failures outside every test and example, relative to DIR."""
    return f'output/{lane.name}/outside.html'


def href(path: str, up: str = '') -> str:
    return e(up + quote(path, safe='/#'))


def page(title: str, crumbs: Sequence[tuple[str, str | None]], up: str,
         body: list[str]) -> str:
    """A whole page: crumbs are the trail at its top, each a label and its link (None for the
    page itself), and up leads from it to DIR."""
    trail = [f'<a class="brand" href="{OWN_SITE}webcpp">webcpp</a>']
    for label, link in [('test matrix', 'index.html'), *crumbs]:
        trail.append('<span>/</span>')
        trail.append(f'<a href="{href(link, up)}">{e(label)}</a>' if link else e(label))
    return '\n'.join([
        '<!doctype html>',
        '<html lang="en">',
        '<head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="color-scheme" content="light dark">',
        f'<title>{e(title)}</title>',
        f'<style>{STYLE}</style>',
        '</head>',
        '<body>',
        f'<header class="bar"><nav class="wrap">{"".join(trail)}</nav></header>',
        '<main class="wrap">',
        *body,
        '</main>',
        '<footer><div class="wrap">Copyright (c) 2026 WebCpp.org &middot; '
        f'<a href="{OWN_SITE}">github.com/webcpporg</a></div></footer>',
        '</body>',
        '</html>',
        '',
    ])


def verdict_paragraph(failures: int, failing_lanes: int, lanes: int, built: bool) -> str:
    if failures:
        return (f'<p class="verdict failing"><strong>Failing.</strong> '
                f'{plural(failures, "failure")} in {failing_lanes} of {plural(lanes, "lane")}.</p>')
    if not built:
        return '<p class="verdict"><strong>Not built.</strong> No lane built any of it.</p>'
    return (f'<p class="verdict passing"><strong>Passing.</strong> Every test and example '
            f'built in {plural(lanes, "lane")} passed.</p>')


def cell(verdict: str | None, link: str | None) -> str:
    if verdict is None:
        return f'<td class="cell na" title="{e(NOT_BUILT)}"><span>n/a</span></td>'
    style = 'pass' if verdict == PASS else 'fail'
    text = f'<a href="{href(link)}">{e(verdict)}</a>' if link else f'<span>{e(verdict)}</span>'
    return f'<td class="cell {style}">{text}</td>'


def lane_header(lane: Lane) -> str:
    if not lane.built():
        return f'<th scope="col" class="lane empty" title="{e(EMPTY)}">{e(lane.name)}</th>'
    if lane.outside:
        return (f'<th scope="col" class="lane outside" title="an action outside every test and '
                f'example failed">{e(lane.name)}</th>')
    return f'<th scope="col" class="lane">{e(lane.name)}</th>'


def legend() -> list[str]:
    entries = [('pass', PASS, 'Every build of it in the lane passed.')]
    entries += [('fail', kind, meaning) for kind, meaning in KINDS.items()]
    entries.append(('na', 'n/a', NOT_BUILT))
    lines = ['<section class="legend">', '<h2>Legend</h2>', '<dl>']
    for style, label, meaning in entries:
        lines.append(f'<div><dt><span class="tag {style}">{e(label)}</span></dt>'
                     f'<dd>{e(meaning)}</dd></div>')
    lines += ['</dl>', '</section>']
    return lines


def table(heads: list[str], lanes: list[Lane],
          rows: list[tuple[list[str], list[str]]]) -> list[str]:
    """A matrix: heads name the columns before the lanes, and each row is the cells before the
    lanes, the first its name, and one cell per lane."""
    first, *others = heads
    head = (f'<th scope="col" class="name">{e(first)}</th>'
            + ''.join(f'<th scope="col">{e(text)}</th>' for text in others))
    lines = ['<div class="scroll">', '<table class="matrix">',
             f'<thead><tr>{head}{"".join(lane_header(lane) for lane in lanes)}</tr></thead>',
             '<tbody>']
    for before, cells in rows:
        lines.append(f'<tr>{"".join(before)}{"".join(cells)}</tr>')
    lines += ['</tbody>', '</table>', '</div>']
    return lines


def index_page(lanes: list[Lane], libraries: dict[str, list[Row]]) -> str:
    rows = []
    for library, library_rows in libraries.items():
        cells = []
        for lane in lanes:
            verdicts = [lane.rows[row.id].verdict() for row in library_rows if row.id in lane.rows]
            failures = [verdict for verdict in verdicts if verdict not in (None, PASS)]
            verdict = (min(failures, key=SEVERITY.index) if failures
                       else PASS if PASS in verdicts else None)
            cells.append(cell(verdict, page_of(library) if verdict else None))
        link = href(page_of(library))
        rows.append(([f'<th scope="row" class="name"><a href="{link}">{e(library)}</a></th>'],
                     cells))
    failures = [len(problems(lane)) for lane in lanes]
    body = ['<h1>Test matrix</h1>',
            verdict_paragraph(sum(failures), sum(1 for count in failures if count), len(lanes),
                              any(lane.built() for lane in lanes))]
    lane_problems = []
    for lane in lanes:
        if not lane.built():
            lane_problems.append(f'<li><strong>{e(lane.name)}</strong>: {e(EMPTY)}.</li>')
        for number, action in enumerate(lane.outside, 1):
            link = href(f'{outside_of(lane)}#failure-{number}')
            lane_problems.append(
                f'<li><strong>{e(lane.name)}</strong>: <a href="{link}"><code>{e(action.path)}'
                f'</code>: {e(step(action.name))}</a>, outside every test and example.</li>')
    if lane_problems:
        body += ['<section class="problems">', '<h2>Lanes</h2>', '<ul>', *lane_problems, '</ul>',
                 '</section>']
    body += table(['Library'], lanes, rows)
    body += legend()
    return page('Test matrix - webcpp', [], '', body)


def library_page(library: str, lanes: list[Lane], library_rows: list[Row]) -> str:
    rows = []
    failures = 0
    failing_lanes = set()
    for row in library_rows:
        cells = []
        for lane in lanes:
            found = lane.rows.get(row.id)
            verdict = found.verdict() if found else None
            failed = verdict not in (None, PASS)
            if failed:
                failures += 1
                failing_lanes.add(lane.name)
            cells.append(cell(verdict, output_of(lane, row) if failed else None))
        # A long name breaks after an underscore first, as it does after a dash.
        name = e(row.name).replace('_', '_<wbr>')
        before = [f'<th scope="row" class="name"><span>{name}</span></th>',
                  f'<td class="type">{e(row.type)}</td>']
        rows.append((before, cells))
    built = any(lane.rows[row.id].builds for lane in lanes for row in library_rows
                if row.id in lane.rows)
    body = [f'<h1>{e(library)}</h1>',
            verdict_paragraph(failures, len(failing_lanes), len(lanes), built)]
    body += table(['Test', 'Type'], lanes, rows)
    body += legend()
    return page(f'{library} - webcpp test matrix', [(library, None)], '', body)


def action_lines(action: Action, file: str) -> list[str]:
    """What b2 recorded of an action that built file: its rule and exit status, its output, and
    its command."""
    output = action.output.strip('\n') or '(no output)'
    rule = action.name or "one of b2's own"
    return ['<dl class="facts">',
            f'<dt>Action</dt><dd><code>{e(rule)}</code></dd>',
            f'<dt>Exit status</dt><dd>{action.status}</dd>',
            f'<dt>File</dt><dd><code>{e(file)}</code></dd>',
            '</dl>',
            '<h3>Output</h3>',
            f'<pre>{e(output)}</pre>',
            f'<details><summary>Command</summary><pre>{e(action.command or "(none)")}</pre>'
            '</details>']


def output_page(lane: Lane, row: Row) -> str:
    verdict = row.verdict() or ''
    title = f'{row.id} on {lane.name}'
    up = '../../../'
    body = [f'<h1><code>{e(row.id)}</code> on {e(lane.name)}</h1>',
            f'<p class="verdict failing"><span class="tag fail">{e(verdict)}</span> '
            f'{e(KINDS.get(verdict, ""))}</p>']
    for build in row.builds:
        if build.kind == PASS:
            continue
        body += ['<section class="build">',
                 f'<h2>Built in <code>{e(build.directory)}</code></h2>']
        # Builds that fail otherwise than the page's verdict says, which is the most significant.
        if build.kind != verdict:
            body.append(f'<p><span class="tag fail">{e(build.kind)}</span> '
                        f'{e(KINDS[build.kind])}</p>')
        if build.culprit is not None:
            body += action_lines(build.culprit, posixpath.basename(build.culprit.path))
        elif lane.outside:
            body.append('<p>The failures of the lane outside every test and example:</p><ul>')
            for number, action in enumerate(lane.outside, 1):
                link = href(f'outside.html#failure-{number}', '../')
                body.append(f'<li><a href="{link}"><code>{e(action.path)}</code>: '
                            f'{e(step(action.name))}</a></li>')
            body.append('</ul>')
        else:
            body.append('<p>No action of the lane outside every test and example failed: the '
                        'lane was likely not built from scratch.</p>')
        body.append('</section>')
    crumbs = [(row.library, page_of(row.library)), (f'{row.name} on {lane.name}', None)]
    return page(f'{title} - webcpp test matrix', crumbs, up, body)


def outside_page(lane: Lane) -> str:
    body = [f'<h1>{e(lane.name)}: failures outside every test and example</h1>',
            '<p>b2 skips what needs a target that failed: the tests and examples that need these '
            'are not run.</p>']
    for number, action in enumerate(lane.outside, 1):
        body += [f'<section class="build" id="failure-{number}">',
                 f'<h2><span class="tag fail">{e(step(action.name))}</span> '
                 f'<code>{e(posixpath.basename(action.path))}</code></h2>',
                 *action_lines(action, action.path), '</section>']
    crumbs = [(f'{lane.name}: outside every test and example', None)]
    return page(f'{lane.name}: failures outside every test and example - webcpp test matrix',
                crumbs, '../../', body)


def write(lanes: list[Lane], out: Path) -> None:
    """Writes the pages of lanes into out."""
    libraries: dict[str, list[Row]] = {}
    for library in sorted({row.library for lane in lanes for row in lane.rows.values()}):
        by_id: dict[str, Row] = {}
        for lane in lanes:
            for row in lane.rows.values():
                if row.library == library:
                    by_id.setdefault(row.id, row)
        libraries[library] = sorted(by_id.values(), key=Row.order)
    pages = {'index.html': index_page(lanes, libraries)}
    for library, library_rows in libraries.items():
        pages[page_of(library)] = library_page(library, lanes, library_rows)
    for lane in lanes:
        for row in lane.rows.values():
            if row.verdict() not in (None, PASS):
                pages[output_of(lane, row)] = output_page(lane, row)
        if lane.outside:
            pages[outside_of(lane)] = outside_page(lane)
    for name, text in pages.items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


def lane_argument(text: str) -> tuple[str, Path]:
    name, separator, file = text.partition('=')
    if not separator or not file:
        raise argparse.ArgumentTypeError(f'{text!r} is not NAME=FILE')
    if not LANE_NAME.fullmatch(name):
        raise argparse.ArgumentTypeError(
            f'the lane name {name!r} is not letters, digits, ".", "_" and "-", from a letter or '
            'a digit')
    return name, Path(file)


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog='report.py', description=(__doc__ or '').split('\n', 1)[0])
    parser.add_argument('--lane', action='append', required=True, type=lane_argument,
                        metavar='NAME=FILE', help="a lane's name and the file b2 wrote for it")
    parser.add_argument('--out', required=True, type=Path, metavar='DIR',
                        help='the directory the pages are written into')
    options = parser.parse_args(arguments)
    given: list[tuple[str, Path]] = options.lane
    names = [name for name, _ in given]
    for name in names:
        if names.count(name) > 1:
            parser.error(f'argument --lane: the lane {name} is given twice')
    lanes = []
    unreadable = []
    for name, path in given:
        try:
            lanes.append(read_lane(name, path))
        except Unreadable as error:
            unreadable.append(f'report: {name}: {error}')
    if unreadable:
        print('\n'.join(unreadable), file=sys.stderr)
        return 2
    found = [text for lane in lanes for text in problems(lane)]
    try:
        write(lanes, options.out)
    except OSError as error:
        print(f'report: cannot write {options.out}: {error}', file=sys.stderr)
        return 2
    index = options.out / 'index.html'
    if found:
        print('\n'.join(f'report: {text}' for text in found), file=sys.stderr)
        print(f'report: {plural(len(found), "failure")}; wrote {index}')
        return 1
    print(f'report: every test and example built in {plural(len(lanes), "lane")} passed; '
          f'wrote {index}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
