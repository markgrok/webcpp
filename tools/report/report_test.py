#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/report/report.py on the samples b2 wrote for lanes over the fixture libraries demo
and component_demo, and the libraries record_samples.py plants beside them: a lane that passes, its
failures named by kind with their output a click away, an expected failure told from a real one, an
empty lane failed by name, and so a library a lane built nothing of, two lanes merged into one
matrix, input it cannot read or report truthfully refused before anything is written (a lane whose
name says another target than its toolset builds for, among them), a failure outside every test,
output that b2's XML cannot hold, and a served component's test that passes and one whose transcript
differs, a run failure, and a library's own lane on a target, named after the target and the
library, which its column and its failures show and which it must hold true. One case uses lanes.py
and pages.py alone; one checks that no sample names the machine's temporary directory; a last one
records every sample afresh, untrimmed, and checks that the report reads it as it reads the
committed one. Every page written is checked to be self-contained, to link only to the report's own
pages, to the site it is served in (its index and each library's page) and to github.com/webcpporg,
and to name its lane on every lane cell, which a phone shows as a chip. Run with the names of some
cases to run only those."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

# The harness lives beside the other tests of the build, in tools/test.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'test'))

import harness
import lanes
import pages
import record_samples

HERE = Path(__file__).resolve().parent
REPORT = HERE / 'report.py'
SAMPLES = HERE / 'samples'

# What a failure cell may say.
KINDS = {'compile', 'link', 'run', 'compiled', 'linked', 'ran', 'build', 'not run'}

FOOTER = 'Copyright (c) 2026 WebCpp.org'

# What an n/a cell says: a served program declares wasip2, and its own lane runs it there, so the
# wasip2 lane's cell must not say it declares no wasip2.
NOT_BUILT = ("Not built in this lane, as when it does not declare the lane's target, or when a "
             "lane of its own runs it.")

# The only site outside the report that a page may link to.
OWN_SITE = 'https://github.com/webcpporg/'

# U+2014, written as a code point so that this file never contains it.
EM_DASH = chr(0x2014)


def sample(name: str) -> Path:
    return SAMPLES / f'{name}.xml'


def report(out: Path, *given: tuple[str, Path | str]) -> subprocess.CompletedProcess:
    """Runs report.py with one --lane NAME=FILE per pair given, writing into out."""
    arguments = [sys.executable, str(REPORT)]
    for name, path in given:
        arguments += ['--lane', f'{name}={path}']
    arguments += ['--out', str(out)]
    return subprocess.run(arguments, capture_output=True, text=True, check=False)


def outcome(result: subprocess.CompletedProcess) -> str:
    return f'exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}'


@dataclass
class Cell:
    """A cell of a page's table: its tag, its attributes, its text and the first link in it."""

    tag: str
    attributes: dict[str, str | None] = field(default_factory=dict)
    text: str = ''
    href: str | None = None

    @property
    def classes(self) -> set[str]:
        return set((self.attributes.get('class') or '').split())

    @property
    def lane(self) -> str | None:
        return self.attributes.get('data-lane')


class Page(HTMLParser):
    """A page's tables, each a list of rows of cells; its links; and its text, unescaped."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.tables: list[list[list[Cell]]] = []
        self.links: list[str] = []
        self.text = ''
        self.cell: Cell | None = None
        self.source = path.read_text(encoding='utf-8')
        self.feed(self.source)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        for name in ('href', 'src'):
            value = attributes.get(name)
            if value is not None:
                self.links.append(value)
        if tag == 'table':
            self.tables.append([])
        elif tag == 'tr' and self.tables:
            self.tables[-1].append([])
        elif tag in ('td', 'th') and self.tables and self.tables[-1]:
            self.cell = Cell(tag, attributes)
            self.tables[-1][-1].append(self.cell)
        elif tag == 'a' and self.cell is not None and self.cell.href is None:
            self.cell.href = attributes.get('href')

    def handle_endtag(self, tag: str) -> None:
        if tag in ('td', 'th') and self.cell is not None:
            self.cell.text = self.cell.text.strip()
            self.cell = None

    def handle_data(self, data: str) -> None:
        self.text += data
        if self.cell is not None:
            self.cell.text += data


def column_name(column: Cell) -> str:
    """A column's name: its lane for a lane's column, whose header also shows its toolset."""
    return column.lane or column.text


@dataclass
class Matrix:
    """The first table of a page: its header cells, and its cells by row name and column name."""

    columns: list[Cell]
    cells: dict[tuple[str, str], Cell]

    def names(self) -> list[str]:
        return [column_name(column) for column in self.columns]

    def rows(self) -> set[str]:
        return {row for row, _ in self.cells}

    def verdict(self, row: str, lane: str) -> str:
        """What the cell of row in lane says: pass, n/a or the kind of a failure, checked
        against its class."""
        cell = self.cells[(row, lane)]
        if 'pass' in cell.classes:
            assert cell.text == 'pass', (row, lane, cell)
        elif 'na' in cell.classes:
            assert cell.text == 'n/a' and cell.href is None, (row, lane, cell)
            assert cell.attributes.get('title') == NOT_BUILT, (row, lane, cell)
        else:
            assert 'fail' in cell.classes and cell.text in KINDS, (row, lane, cell)
            assert cell.href, ('a failure links to its output', row, lane, cell)
        return cell.text


def matrix(path: Path) -> Matrix:
    page = Page(path)
    assert page.tables, (path, 'no table')
    header, *rows = page.tables[0]
    names = [column_name(column) for column in header]
    cells = {}
    for row in rows:
        for name, cell in zip(names[1:], row[1:]):
            cells[(row[0].text, name)] = cell
    return Matrix(header, cells)


def linked(page: Path, href: str | None) -> Page:
    """The page that href, a link of page, opens."""
    assert href, (page, 'no link')
    return Page(page.parent / unquote(urlsplit(href).path))


def check_pages(out: Path) -> None:
    """Every page under out is self-contained, carries the footer, and names its lane on every lane
    cell of a matrix, the label of the chip a phone shows. Its links name pages that exist beside
    it, github.com/webcpporg, or the site the report is served in, at its report/: the brand
    links the site's index, `../` from out, and each library's page links its documentation,
    `../libs/<library>/`, which assemble.py checks once the site is laid out."""
    written = sorted(out.rglob('*.html'))
    assert out / 'index.html' in written, written
    top = out.resolve()
    libraries = {path.stem for path in out.glob('*.html') if path.name != 'index.html'}
    site_pages = {top.parent} | {top.parent / 'libs' / name for name in libraries}
    for library in libraries:
        assert f'../libs/{library}/' in Page(out / f'{library}.html').links, library
    for path in written:
        page = Page(path)
        lowered = page.source.lower()
        assert lowered.startswith('<!doctype html>'), path
        assert '<meta name="viewport"' in lowered, path
        for banned in ('<script', '<link', '<img', '<iframe', '@import', 'url('):
            assert banned not in lowered, (path, banned)
        assert FOOTER in page.text, path
        assert EM_DASH not in page.source, path
        assert page.links and (path.parent / page.links[0]).resolve() == top.parent, (
            path, 'the brand links the site\'s index', page.links[:1])
        for href in page.links:
            parts = urlsplit(href)
            if parts.scheme or parts.netloc:
                assert href.startswith(OWN_SITE), (path, href)
            elif parts.path:
                target = (path.parent / unquote(parts.path)).resolve()
                if target.is_relative_to(top):
                    assert target.is_file(), (path, href)
                else:
                    assert href.endswith('/') and target in site_pages, (path, href)
        for header, *rows in page.tables:
            lane_names = [column.lane for column in header if column.lane]
            assert lane_names, (path, 'a matrix without lanes')
            for row in rows:
                cells = [cell for cell in row if 'cell' in cell.classes]
                assert [cell.lane for cell in cells] == lane_names, (path, row)


DEMO_TYPES = {
    'pass': 'run',
    'fails': 'run-fail',
    'rejects': 'compile-fail',
    'native_only': 'run',
    'native_only_compiles': 'compile',
    'alone-demo': 'compile',
    'alone-demo-answer': 'compile',
    'hello': 'example',
    'catches': 'example',
    'suite': 'run',
    'parses_json': 'run',
}

# What wasip2 builds of demo: neither the native-only programs, nor the Boost.Test suite, nor
# catches, an example that throws.
WASIP2_DEMO = {'pass', 'fails', 'rejects', 'alone-demo', 'alone-demo-answer', 'hello',
               'parses_json'}


def test_all_pass_exits_0_and_matrix_has_cells(root: Path) -> None:
    out = root / 'report'
    result = report(out, ('native', sample('native-pass')))
    assert result.returncode == 0, outcome(result)
    assert result.stderr == '', outcome(result)
    assert 'index.html' in result.stdout, outcome(result)
    index = matrix(out / 'index.html')
    assert index.names() == ['Library', 'native'], index.names()
    assert index.rows() == {'demo'}, index.rows()
    assert index.verdict('demo', 'native') == 'pass'
    assert index.cells[('demo', 'native')].href == 'demo.html'
    demo = matrix(out / 'demo.html')
    assert demo.names() == ['Test', 'Type', 'native'], demo.names()
    assert demo.rows() == set(DEMO_TYPES), demo.rows()
    for name, kind in DEMO_TYPES.items():
        assert demo.cells[(name, 'Type')].text == kind, (name, demo.cells[(name, 'Type')])
        assert demo.verdict(name, 'native') == 'pass', name
    check_pages(out)


def test_run_failure_exits_1_and_cell_links_output(root: Path) -> None:
    out = root / 'report'
    result = report(out, ('native', sample('native-failures')))
    assert result.returncode == 1, outcome(result)
    named = 'native: planted/fails_to_run: run'
    assert named in result.stderr, (named, outcome(result))
    assert 'demo/' not in result.stderr, outcome(result)
    index = matrix(out / 'index.html')
    assert index.verdict('demo', 'native') == 'pass'
    # A library's cell shows its most significant failure, the way Boost's summary does.
    assert index.verdict('planted', 'native') == 'compile'
    assert index.cells[('planted', 'native')].href == 'planted.html'
    planted = matrix(out / 'planted.html')
    assert planted.verdict('fails_to_run', 'native') == 'run'
    output = linked(out / 'planted.html', planted.cells[('fails_to_run', 'native')].href)
    assert "test '1 + 1 == 3' ('2' == '3') failed" in output.text, output.text
    assert 'EXIT STATUS: 1' in output.text, output.text
    assert 'planted/fails_to_run' in output.text and 'native' in output.text, output.text
    check_pages(out)


def test_compile_error_and_expected_compile_fail_are_distinguished(root: Path) -> None:
    out = root / 'report'
    result = report(out, ('native', sample('native-failures')))
    assert result.returncode == 1, outcome(result)
    demo = matrix(out / 'demo.html')
    # rejects does not compile, which it must not: b2 records its compile as failed, and the test
    # passes.
    assert demo.cells[('rejects', 'Type')].text == 'compile-fail'
    assert demo.verdict('rejects', 'native') == 'pass'
    assert demo.verdict('pass', 'native') == 'pass'
    # The tests of demo the lane did not ask for are not built there.
    assert demo.verdict('fails', 'native') == 'n/a'
    planted = matrix(out / 'planted.html')
    expected = {
        # name: (type, cell, a line of its output)
        'fails_to_compile': ('run', 'compile', "use of undeclared identifier 'undeclared'"),
        'fails_to_link': ('run', 'link', 'missing()'),
        'compiles': ('compile-fail', 'compiled', 'compiles.cpp'),
        'exits_with_zero': ('run-fail', 'ran', 'exits_with_zero'),
        'prints_otherwise': ('example', 'run', '+printed'),
        'does_not_compile': ('example', 'compile', "use of undeclared identifier 'undeclared'"),
    }
    for name, (kind, verdict, text) in expected.items():
        assert planted.cells[(name, 'Type')].text == kind, (name, planted.cells[(name, 'Type')])
        assert planted.verdict(name, 'native') == verdict, name
        output = linked(out / 'planted.html', planted.cells[(name, 'native')].href)
        assert text in output.text, (name, text, output.text)
        tests_or_examples = 'example/' if kind == 'example' else ''
        named = f'native: planted/{tests_or_examples}{name}: {verdict}'
        assert named in result.stderr, (named, outcome(result))
    check_pages(out)


def test_empty_lane_exits_1_naming_it(root: Path) -> None:
    out = root / 'alone'
    result = report(out, ('wasip2', sample('wasip2-empty')))
    assert result.returncode == 1, outcome(result)
    assert 'wasip2: the lane built no test and no example' in result.stderr, outcome(result)
    check_pages(out)
    out = root / 'beside'
    result = report(out, ('native', sample('native-pass')), ('wasip2', sample('wasip2-empty')))
    assert result.returncode == 1, outcome(result)
    named = 'report: wasip2: the lane built no test and no example'
    assert result.stderr.splitlines() == [named], outcome(result)
    index = matrix(out / 'index.html')
    assert index.names() == ['Library', 'native', 'wasip2'], index.names()
    # The lane's column is marked, and so is each of its chips, so that its grey cells do not
    # read as a pass.
    assert 'empty' in index.columns[2].classes, index.columns
    assert 'empty' not in index.columns[1].classes, index.columns
    assert index.cells[('demo', 'wasip2')].attributes.get('data-note') == 'empty'
    assert 'data-note' not in index.cells[('demo', 'native')].attributes
    # The toolset of a lane that built nothing is the one its command line names.
    assert 'clang-wasip2' in index.columns[2].text, index.columns
    assert index.verdict('demo', 'native') == 'pass'
    assert index.verdict('demo', 'wasip2') == 'n/a'
    assert index.verdict('nativeonly', 'native') == 'n/a'
    assert index.verdict('nativeonly', 'wasip2') == 'n/a'
    # Every page names the empty lane: a library's page, too.
    for page in ('index.html', 'demo.html', 'nativeonly.html'):
        assert 'wasip2: the lane built no test and no example' in Page(out / page).text, page
    nativeonly = matrix(out / 'nativeonly.html')
    assert nativeonly.rows() == {'works'}, nativeonly.rows()
    assert nativeonly.verdict('works', 'wasip2') == 'n/a'
    check_pages(out)


def test_a_library_the_lane_built_nothing_of_fails_it(root: Path) -> None:
    # The CI puts in a lane only the libraries that declare its target, so a library whose tests
    # --dump-tests lists and none of which the lane built is a failure, not a grey column: here
    # nativeonly, beside demo, which passes.
    out = root / 'report'
    result = report(out, ('wasip2', sample('wasip2-skipped-library')))
    assert result.returncode == 1, outcome(result)
    named = 'report: wasip2: nativeonly: the lane built none of its tests and examples'
    assert result.stderr.splitlines() == [named], outcome(result)
    index = matrix(out / 'index.html')
    assert index.verdict('demo', 'wasip2') == 'pass'
    assert index.verdict('nativeonly', 'wasip2') == 'n/a'
    # The lane is not empty: it built demo.
    assert 'empty' not in index.columns[1].classes, index.columns
    # Every page names the library, and says the matrix fails.
    for page in ('index.html', 'demo.html', 'nativeonly.html'):
        text = Page(out / page).text
        assert 'wasip2: nativeonly: the lane built none of its tests and examples' in text, page
    assert 'Failing.' in Page(out / 'index.html').text
    check_pages(out)
    # lanes.py names it too, and only it.
    lane = lanes.read_lane('wasip2', sample('wasip2-skipped-library'))
    assert lane.unbuilt() == ['nativeonly'], lane.unbuilt()
    assert lanes.exit_status([lane]) == 1


def test_two_lanes_merge_into_one_matrix(root: Path) -> None:
    out = root / 'report'
    result = report(out, ('native', sample('native-pass')), ('wasip2', sample('wasip2-pass')))
    assert result.returncode == 0, outcome(result)
    index = matrix(out / 'index.html')
    assert index.names() == ['Library', 'native', 'wasip2'], index.names()
    # Under each lane's name, the toolset b2 built it with.
    assert index.columns[1].text == 'nativeclang-darwin-21', index.columns
    assert index.columns[2].text == 'wasip2clang-darwin-wasip2', index.columns
    assert index.verdict('demo', 'native') == 'pass'
    assert index.verdict('demo', 'wasip2') == 'pass'
    demo = matrix(out / 'demo.html')
    assert demo.names() == ['Test', 'Type', 'native', 'wasip2'], demo.names()
    assert demo.rows() == set(DEMO_TYPES), demo.rows()
    for name in DEMO_TYPES:
        assert demo.verdict(name, 'native') == 'pass', name
        assert demo.verdict(name, 'wasip2') == ('pass' if name in WASIP2_DEMO else 'n/a'), name
    check_pages(out)
    # The lanes are the columns in the order the command line gives them.
    out = root / 'swapped'
    result = report(out, ('wasip2', sample('wasip2-pass')), ('native', sample('native-pass')))
    assert result.returncode == 0, outcome(result)
    assert matrix(out / 'index.html').names() == ['Library', 'wasip2', 'native']
    assert matrix(out / 'demo.html').names() == ['Test', 'Type', 'wasip2', 'native']


def test_unreadable_xml_exits_2(root: Path) -> None:
    passing = sample('native-pass')
    text = passing.read_text(encoding='utf-8')
    (root / 'garbage.xml').write_text('this is not XML\n')
    (root / 'truncated.xml').write_text(text[:len(text) // 2])
    (root / 'html.xml').write_text('<html><body>a page</body></html>\n')
    # The lane as b2 writes it without --dump-tests, which lists the tests.
    without = re.sub(r'\n  <test .*?</test> ?(?=\n)', '', text, flags=re.DOTALL)
    assert without != text and '<test ' not in without
    (root / 'without-dump-tests.xml').write_text(without)
    # A library whose page would be the summary, on a file system that ignores case.
    (root / 'index-library.xml').write_text(text.replace('libs/demo/', 'libs/Index/'))
    # Tests outside libs/, in a superproject that is itself under a directory named libs.
    outside = re.sub(r'<directory><!\[CDATA\[.*?\]\]>',
                     '<directory><![CDATA[/home/u/libs/webcpp]]>',
                     text.replace('libs/demo/', 'tools/demo/'))
    assert '/home/u/libs/webcpp' in outside and 'libs/demo/' not in outside
    (root / 'outside-libs.xml').write_text(outside)
    unreadable = {
        'missing.xml': 'missing.xml',
        'garbage.xml': 'garbage.xml',
        'truncated.xml': 'truncated.xml',
        'html.xml': 'html.xml',
        'without-dump-tests.xml': '--dump-tests',
        'index-library.xml': 'a library named Index',
        'outside-libs.xml': 'tools/demo/test is not in libs/<library>/',
    }
    for name, named in unreadable.items():
        out = root / f'out-{name}'
        result = report(out, ('native', passing), ('other', root / name))
        assert result.returncode == 2, (name, outcome(result))
        assert named in result.stderr, (name, named, outcome(result))
        assert not out.exists(), (name, 'nothing is written', sorted(out.rglob('*')))
    # A lane given without its file, twice (in any case, since a lane names a directory), or
    # with a name a file cannot have.
    for given in (['native'], [f'native={passing}', f'native={passing}'],
                  [f'Native={passing}', f'native={passing}'], [f'a/b={passing}']):
        out = root / 'out-lanes'
        arguments = [sys.executable, str(REPORT)]
        for lane in given:
            arguments += ['--lane', lane]
        result = subprocess.run([*arguments, '--out', str(out)], capture_output=True, text=True,
                                check=False)
        assert result.returncode == 2, (given, outcome(result))
        assert '--lane' in result.stderr, (given, outcome(result))
        assert not out.exists(), given
    # A directory the pages cannot be written into: a file is where it would be.
    blocked = root / 'a file'
    blocked.write_text('')
    result = report(blocked, ('native', passing))
    assert result.returncode == 2, outcome(result)
    assert f'cannot write {blocked}' in result.stderr, outcome(result)


def test_nine_lanes_fit_the_content_width_at_desktop(_root: Path) -> None:
    """A budget on pages.STYLE, standing in for what a real Chrome measured at 1280px wide (the
    screenshots this change records): the lane header must be free to wrap at a hyphen, since
    nowrap, the rule every other cell keeps, would hold it to its widest line's full width; and
    the content width a 1280px window leaves inside .wrap must then hold a sticky name column
    and 9 lane columns at their minimum width, so the matrix does not need to scroll sideways."""
    style = pages.STYLE
    lane_rule = re.search(r'\.matrix \.lane \{([^}]*)\}', style)
    assert lane_rule and 'white-space: normal' in lane_rule.group(1), style
    wrap_rule = re.search(r'\.wrap \{([^}]*)\}', style)
    assert wrap_rule, style
    max_width_match = re.search(r'max-width:\s*(\d+)px', wrap_rule.group(1))
    side_padding_match = re.search(r'padding-left:\s*(\d+)px', wrap_rule.group(1))
    assert max_width_match and side_padding_match, wrap_rule.group(1)
    content_width = int(max_width_match.group(1)) - 2 * int(side_padding_match.group(1))
    cell_rule = re.search(r'\.matrix td\.cell \{([^}]*)\}', style)
    assert cell_rule, style
    cell_min_width_match = re.search(r'min-width:\s*(\d+)px', cell_rule.group(1))
    assert cell_min_width_match, cell_rule.group(1)
    cell_min_width = int(cell_min_width_match.group(1))
    # A sticky name column at least as wide as a short library name needs, estimated generously
    # (mono 13px, about 12 characters) at 160px, including its own padding and border.
    name_column = 160
    nine_lanes = 9 * cell_min_width
    assert name_column + nine_lanes <= content_width, (
        content_width, name_column, cell_min_width, nine_lanes)


def test_toolset_line_shown_only_when_it_differs_from_the_lane_name(root: Path) -> None:
    out = root / 'report'
    # Clang-Darwin-21 names the same toolset as clang-darwin-21, differing only in case: the
    # header does not repeat it. wasip2 does not name its toolset, clang-darwin-wasip2: the
    # header shows it.
    result = report(out, ('Clang-Darwin-21', sample('native-pass')),
                    ('wasip2', sample('wasip2-pass')))
    assert result.returncode == 0, outcome(result)
    columns = matrix(out / 'index.html').columns
    assert columns[1].text == 'Clang-Darwin-21', columns
    assert columns[2].text == 'wasip2clang-darwin-wasip2', columns
    check_pages(out)


def test_a_lane_is_what_its_name_says(root: Path) -> None:
    # A lane named after a target is built for it, so that a slip in CI cannot show a target
    # green that was never built.
    wasip2 = sample('wasip2-pass')
    refused = {
        'wasip3': (wasip2, 'built with clang-darwin-wasip2, which builds for wasip2'),
        'native': (wasip2, 'built with clang-darwin-wasip2, which builds for wasip2'),
        'Native': (wasip2, 'built with clang-darwin-wasip2, which builds for wasip2'),
        'wasip2': (sample('native-pass'), 'built with clang-darwin-21, which builds for native'),
        # A lane that built nothing is checked against the toolset its command line names.
        'emscripten': (sample('wasip2-empty'), 'built with clang-wasip2, which builds for wasip2'),
    }
    for name, (path, named) in refused.items():
        out = root / f'out-{name}'
        result = report(out, (name, path))
        assert result.returncode == 2, (name, outcome(result))
        assert f'the lane {name} is {named}' in result.stderr, (name, outcome(result))
        assert not out.exists(), name
    # A lane is one toolset: here one test was built with another.
    text = sample('native-pass').read_text(encoding='utf-8')
    mixed = text.replace('pass.test/clang-darwin-21', 'pass.test/gcc-15')
    assert mixed != text
    (root / 'mixed.xml').write_text(mixed)
    result = report(root / 'out-mixed', ('gcc-and-clang', root / 'mixed.xml'))
    assert result.returncode == 2, outcome(result)
    assert 'built with clang-darwin-21, gcc-15; a lane is one toolset' in result.stderr, (
        outcome(result))
    # A lane named after no target is named after the directory b2 built its toolset in, so that
    # a native lane's label cannot claim a compiler it was not built with.
    for name in ('gcc-99', 'clang-21', 'clang'):
        out = root / f'out-{name}'
        result = report(out, (name, sample('native-pass')))
        assert result.returncode == 2, (name, outcome(result))
        named = (f'the lane {name} is built with clang-darwin-21; name it clang-darwin-21, '
                 'after the directory b2 builds its toolset in, or native, after its target')
        assert named in result.stderr, (name, outcome(result))
        assert not out.exists(), name
    out = root / 'out-named'
    result = report(out, ('clang-darwin-21', sample('native-pass')),
                    ('clang-darwin-wasip2', sample('wasip2-pass')))
    assert result.returncode == 0, outcome(result)
    columns = matrix(out / 'index.html').columns
    # The lane's name is already its toolset, so the header does not repeat it.
    assert columns[1].text == 'clang-darwin-21', columns
    assert columns[2].text == 'clang-darwin-wasip2', columns
    # A lane that built nothing has no directory to check its name against: the toolset its
    # command line names (clang-wasip2) is not the directory's name (clang-darwin-wasip2). It
    # fails as empty.
    result = report(root / 'out-empty', ('clang-darwin-wasip2', sample('wasip2-empty')))
    assert result.returncode == 1, outcome(result)
    assert 'clang-darwin-wasip2: the lane built no test and no example' in result.stderr, (
        outcome(result))


def test_an_own_lane_is_named_after_its_target_and_library(root: Path) -> None:
    # An own lane on a target is named <target>.<library>.<directory>.<lane>, its directory under
    # libs/<library>/ with its slashes as dots: never a lane's name, so its column stands beside
    # the target's own. It is counted as any lane is: its tests appear in the matrix under its
    # name, and its failure fails the report.
    own = 'wasip2.component_demo.test.served'
    out = root / 'report'
    result = report(out, ('wasip2', sample('wasip2-pass')), (own, sample('wasip2-served')))
    assert result.returncode == 0, outcome(result)
    index = matrix(out / 'index.html')
    assert index.names()[1:] == ['wasip2', own], index.names()
    assert index.verdict('component_demo', own) == 'pass'
    assert index.verdict('component_demo', 'wasip2') == 'n/a'
    assert index.verdict('demo', own) == 'n/a'
    # The served test, n/a in the target's own column, says why truthfully: its own lane runs it.
    title = index.cells[('component_demo', 'wasip2')].attributes.get('title') or ''
    assert title.endswith('or when a lane of its own runs it.'), title
    assert matrix(out / 'component_demo.html').verdict('answers', own) == 'pass'
    # Its header may wrap after each dot, as a lane's wraps at a hyphen.
    assert 'wasip2.<wbr>component_demo.<wbr>test.<wbr>served' in (out / 'index.html').read_text()
    check_pages(out)
    result = report(root / 'fails', (own, sample('wasip2-served-failure')))
    assert result.returncode == 1, outcome(result)
    assert result.stderr.splitlines() == [f'report: {own}: component_demo/answers: run'], (
        outcome(result))
    # The target its name begins with is the one its toolset builds for, and the library it
    # names is the only one whose tests it lists.
    served = sample('wasip2-served')
    refused = {
        'wasip3.component_demo.test.served': (
            served, 'built with clang-darwin-wasip2, which builds for wasip2'),
        'native.component_demo.test.served': (
            served, 'built with clang-darwin-wasip2, which builds for wasip2'),
        'wasip2.demo.test.served': (
            served, 'an own lane of demo, and lists the tests of component_demo'),
        'wasip2.demo.example.served': (
            sample('wasip2-skipped-library'), 'an own lane of demo, and lists the tests of '
            'nativeonly'),
    }
    for name, (path, named) in refused.items():
        out = root / f'out-{name}'
        result = report(out, (name, path))
        assert result.returncode == 2, (name, outcome(result))
        assert f'the lane {name} is {named}' in result.stderr, (name, outcome(result))
        assert not out.exists(), name
    # A name whose first word is no target is a toolset directory's, checked as before.
    result = report(root / 'out-other', ('wasm.component_demo.test.served', served))
    assert result.returncode == 2, outcome(result)
    assert 'name it clang-darwin-wasip2, after the directory b2 builds its toolset in' in (
        result.stderr), outcome(result)


def test_a_failure_outside_every_test_fails_the_lane(root: Path) -> None:
    # The handler of tools/throw_exception.cpp, which pass links on wasip2, does not compile: the
    # action is no test's, and pass is compiled but never linked nor run.
    out = root / 'report'
    result = report(out, ('wasip2', sample('wasip2-dependency')))
    assert result.returncode == 1, outcome(result)
    lines = result.stderr.splitlines()
    assert 'report: wasip2: demo/pass: not run' in lines, outcome(result)
    outside = [line for line in lines if 'throw_exception.o' in line]
    assert len(outside) == 1 and 'compile' in outside[0], outcome(result)
    full = ('bin/clang-darwin-wasip2/debug/cxxstd-20-iso/exception-handling-off/link-static/'
            'target-os-wasi/')
    assert full in outside[0], outcome(result)
    # The summary names the file; the page it links to, its whole path.
    index = Page(out / 'index.html')
    assert 'wasip2: throw_exception.o: compile, outside every test' in index.text, index.text
    assert full not in index.text, index.text
    problem = [href for href in index.links if href.startswith('output/wasip2/')]
    assert len(problem) == 1, index.links
    page = linked(out / 'index.html', problem[0])
    assert 'planted: the handler does not compile' in page.text, page.text
    assert f'{full}throw_exception.o' in page.text, page.text
    demo = matrix(out / 'demo.html')
    assert demo.verdict('pass', 'wasip2') == 'not run'
    assert demo.verdict('fails', 'wasip2') == 'n/a'
    assert 'outside' in demo.columns[2].classes, demo.columns
    assert demo.cells[('fails', 'wasip2')].attributes.get('data-note') == 'outside failure'
    output = linked(out / 'demo.html', demo.cells[('pass', 'wasip2')].href)
    assert 'throw_exception.o' in output.text, output.text
    check_pages(out)


def test_output_cdata_cannot_hold_is_shown(root: Path) -> None:
    # The test prints ]]>, which ends b2's CDATA early, markup, and a byte that is not UTF-8.
    data = sample('native-odd-output').read_bytes()
    assert b']]>&amp;' in data and b'\xff' in data
    out = root / 'report'
    result = report(out, ('native', sample('native-odd-output')))
    assert result.returncode == 1, outcome(result)
    assert 'native: odd/prints: run' in result.stderr, outcome(result)
    odd = matrix(out / 'odd.html')
    assert odd.verdict('prints', 'native') == 'run'
    output = linked(out / 'odd.html', odd.cells[('prints', 'native')].href)
    replaced = chr(0xFFFD)
    assert f"('<b>]]>&amp;</b>' == '{replaced}')" in output.text, output.text
    check_pages(out)


def test_served_test_passes_and_fails_as_a_run(root: Path) -> None:
    # A served component's test is a test like any other: listed, of type serve, and its
    # failure, a transcript that differs, is a run failure whose output holds the diff.
    out = root / 'passes'
    result = report(out, ('wasip2', sample('wasip2-served')))
    assert result.returncode == 0, outcome(result)
    index = matrix(out / 'index.html')
    assert index.verdict('component_demo', 'wasip2') == 'pass'
    component = matrix(out / 'component_demo.html')
    assert component.rows() == {'bindings', 'native_alone', 'answers', 'alone-component_demo',
                                'alone-component_demo-world'}, component.rows()
    assert component.cells[('answers', 'Type')].text == 'serve'
    assert component.verdict('answers', 'wasip2') == 'pass'
    assert component.verdict('bindings', 'wasip2') == 'pass'
    assert component.verdict('native_alone', 'wasip2') == 'n/a'
    check_pages(out)
    out = root / 'fails'
    result = report(out, ('wasip2', sample('wasip2-served-failure')))
    assert result.returncode == 1, outcome(result)
    assert result.stderr.splitlines() == ['report: wasip2: component_demo/answers: run'], (
        outcome(result))
    assert matrix(out / 'index.html').verdict('component_demo', 'wasip2') == 'run'
    component = matrix(out / 'component_demo.html')
    assert component.verdict('answers', 'wasip2') == 'run'
    assert component.verdict('bindings', 'wasip2') == 'pass'
    output = linked(out / 'component_demo.html', component.cells[('answers', 'wasip2')].href)
    for text in ('the transcript differs from libs/component_demo/test/answers.expected',
                 '-HTTP/1.1 405 Method Not Allowed', '+HTTP/1.1 404 Not Found',
                 "wasmtime's standard error:"):
        assert text in output.text, (text, output.text)
    check_pages(out)


def test_lanes_and_pages_work_alone(root: Path) -> None:
    # lanes.py reads and judges a lane, with no page written.
    lane = lanes.read_lane('native', sample('native-failures'))
    assert lane.toolset == 'clang-darwin-21', lane.toolset
    verdicts = {row_id: row.verdict() for row_id, row in lane.rows.items()}
    assert verdicts['planted/fails_to_run'] == 'run', verdicts
    assert verdicts['planted/compiles'] == 'compiled', verdicts
    assert verdicts['planted/example/prints_otherwise'] == 'run', verdicts
    assert verdicts['demo/rejects'] == 'pass', verdicts
    assert verdicts['demo/fails'] is None, verdicts
    assert lanes.exit_status([lane]) == 1
    assert lanes.worst([None, 'pass', 'run', 'compile']) == 'compile'
    assert lanes.worst(['pass', None]) == 'pass'
    assert lanes.worst([None]) is None
    # pages.py writes the pages of a lane made by hand, with no b2 file.
    made = lanes.Lane('wasip3', toolset='clang-linux-wasip3')
    row = lanes.Row('made', False, 'by_hand', 'run', [lanes.Build('bin/x', 'bin/x/by_hand.test')])
    made.rows[row.id] = row
    assert lanes.exit_status([made]) == 0
    pages.write([made], root / 'pages')
    page = matrix(root / 'pages' / 'made.html')
    assert page.verdict('by_hand', 'wasip3') == 'pass'
    assert page.columns[2].text == 'wasip3clang-linux-wasip3', page.columns
    check_pages(root / 'pages')


def tables(out: Path) -> dict[str, list[list[list[tuple[str, frozenset[str], str | None]]]]]:
    """The tables of the pages directly in out, by page, a lane's header by its lane: the
    toolset under it is the machine's (clang-darwin-21 here, clang-linux-22 on a Linux runner)."""
    def text(cell: Cell) -> str:
        return column_name(cell) if cell.tag == 'th' else cell.text
    return {page.name: [[[(text(cell), frozenset(cell.classes), cell.href) for cell in row]
                         for row in table] for table in Page(page).tables]
            for page in sorted(out.glob('*.html'))}


def test_samples_name_no_temporary_directory(_root: Path) -> None:
    # A sample is recorded in a scratch superproject under the temporary directory, whose path
    # names the machine (macOS's /var/folders/<hash>/T, which b2 also prints resolved, under
    # /private): the recording writes it as a placeholder, in each form, and only where it is a
    # whole directory of a path. No committed sample names it.
    temporary = Path(tempfile.gettempdir())
    forms = sorted({str(temporary), str(temporary.resolve())})
    written = ''.join(f'"{form}/webcpp scratch x/tools" "{form}//jam1.000" {form}more\n'
                      for form in forms).encode()
    scrubbed = record_samples.scrub(written).decode()
    placeholder = record_samples.TEMPORARY.decode()
    assert scrubbed == ''.join(f'"{placeholder}/webcpp scratch x/tools" "{placeholder}//jam1.000" '
                               f'{form}more\n' for form in forms), scrubbed
    for name in sorted(SAMPLES.glob('*.xml')):
        text = name.read_text(encoding='utf-8', errors='replace')
        for machine in ['/private/var/', '/var/folders/', *(f'{form}/' for form in forms)]:
            assert machine not in text, (name, machine)
        assert placeholder in text, name


def test_samples_read_as_b2_writes_them_today(root: Path) -> None:
    # A sample is trimmed, and recorded once: a lane recorded now, untrimmed, gives the same
    # matrix, so the trimming changed nothing the report reads, and the b2 installed still
    # writes what the report expects.
    for name in record_samples.SAMPLES_BY_NAME:
        lane = name.split('-')[0]
        scratch = record_samples.scratch(name)
        try:
            fresh = root / 'fresh' / f'{name}.xml'
            fresh.parent.mkdir(exist_ok=True)
            shutil.copy(record_samples.record(name, scratch), fresh)
        finally:
            shutil.rmtree(scratch)
        now = report(root / 'now' / name, (lane, fresh))
        then = report(root / 'then' / name, (lane, sample(name)))
        assert then.returncode in (0, 1), (name, outcome(then))
        assert now.returncode == then.returncode, (name, outcome(now), outcome(then))
        assert tables(root / 'now' / name) == tables(root / 'then' / name), name


CASES = [
    test_all_pass_exits_0_and_matrix_has_cells,
    test_run_failure_exits_1_and_cell_links_output,
    test_compile_error_and_expected_compile_fail_are_distinguished,
    test_empty_lane_exits_1_naming_it,
    test_a_library_the_lane_built_nothing_of_fails_it,
    test_two_lanes_merge_into_one_matrix,
    test_toolset_line_shown_only_when_it_differs_from_the_lane_name,
    test_nine_lanes_fit_the_content_width_at_desktop,
    test_unreadable_xml_exits_2,
    test_a_lane_is_what_its_name_says,
    test_an_own_lane_is_named_after_its_target_and_library,
    test_a_failure_outside_every_test_fails_the_lane,
    test_output_cdata_cannot_hold_is_shown,
    test_served_test_passes_and_fails_as_a_run,
    test_lanes_and_pages_work_alone,
    test_samples_name_no_temporary_directory,
    test_samples_read_as_b2_writes_them_today,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('report_test', CASES, sys.argv[1:]))
