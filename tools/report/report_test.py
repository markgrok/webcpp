#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/report/report.py on the samples b2 wrote for lanes over the fixture library demo
and the libraries record_samples.py plants beside it: a lane that passes, its failures named by
kind with their output a click away, an expected failure told from a real one, an empty lane
failed by name, two lanes merged into one matrix, input it cannot read refused before anything is
written, a failure outside every test, and output that b2's XML cannot hold. A last case records
every sample afresh, untrimmed, and checks that the report reads it as it reads the committed one.
Every page written is checked to be self-contained and to link only to github.com/webcpporg. Run
with the names of some cases to run only those."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

# The harness lives beside the other tests of the build, in tools/test.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'test'))

import harness
import record_samples

HERE = Path(__file__).resolve().parent
REPORT = HERE / 'report.py'
SAMPLES = HERE / 'samples'

# What a failure cell may say.
KINDS = {'compile', 'link', 'run', 'compiled', 'linked', 'ran', 'build', 'not run'}

FOOTER = 'Copyright (c) 2026 WebCpp.org'

# The only site outside the report that a page may link to.
OWN_SITE = 'https://github.com/webcpporg/'

# U+2014, written as an escape so that this file never contains it.
EM_DASH = '\u2014'


def sample(name: str) -> Path:
    return SAMPLES / f'{name}.xml'


def report(out: Path, *lanes: tuple[str, Path | str]) -> subprocess.CompletedProcess:
    """Runs report.py with one --lane NAME=FILE per pair of lanes, writing into out."""
    arguments = [sys.executable, str(REPORT)]
    for name, path in lanes:
        arguments += ['--lane', f'{name}={path}']
    arguments += ['--out', str(out)]
    return subprocess.run(arguments, capture_output=True, text=True, check=False)


def outcome(result: subprocess.CompletedProcess) -> str:
    return f'exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}'


@dataclass
class Cell:
    """A cell of a page's table: its text, its classes and the first link in it."""

    text: str = ''
    classes: set[str] = field(default_factory=set)
    href: str | None = None


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
            self.cell = Cell(classes=set((attributes.get('class') or '').split()))
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


@dataclass
class Matrix:
    """The first table of a page: its header cells, and its cells by row name and column name."""

    columns: list[Cell]
    cells: dict[tuple[str, str], Cell]

    def names(self) -> list[str]:
        return [column.text for column in self.columns]

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
        else:
            assert 'fail' in cell.classes and cell.text in KINDS, (row, lane, cell)
            assert cell.href, ('a failure links to its output', row, lane, cell)
        return cell.text


def matrix(path: Path) -> Matrix:
    page = Page(path)
    assert page.tables, (path, 'no table')
    header, *rows = page.tables[0]
    names = [column.text for column in header]
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
    """Every page under out is self-contained, carries the footer, and links only to pages that
    exist beside it or to github.com/webcpporg."""
    pages = sorted(out.rglob('*.html'))
    assert out / 'index.html' in pages, pages
    for path in pages:
        page = Page(path)
        lowered = page.source.lower()
        assert lowered.startswith('<!doctype html>'), path
        assert '<meta name="viewport"' in lowered, path
        for banned in ('<script', '<link', '<img', '<iframe', '@import', 'url('):
            assert banned not in lowered, (path, banned)
        assert FOOTER in page.text, path
        assert EM_DASH not in page.source, path
        for href in page.links:
            parts = urlsplit(href)
            if parts.scheme or parts.netloc:
                assert href.startswith(OWN_SITE), (path, href)
            elif parts.path:
                assert (path.parent / unquote(parts.path)).is_file(), (path, href)


DEMO_TYPES = {
    'pass': 'run',
    'pass-noexcept': 'run',
    'fails': 'run-fail',
    'rejects': 'compile-fail',
    'native_only': 'run',
    'native_only-noexcept': 'run',
    'native_only_compiles': 'compile',
    'alone-demo': 'compile',
    'alone-demo-answer': 'compile',
    'hello': 'example',
    'catches': 'example',
}

# What wasip2 builds of demo: neither the native-only programs, nor the -noexcept variants, which
# are native, nor catches, an example that throws.
WASIP2_DEMO = {'pass', 'fails', 'rejects', 'alone-demo', 'alone-demo-answer', 'hello'}


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
    for named in ('native: planted/fails_to_run: run',
                  'native: planted/fails_to_run-noexcept: run'):
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
    # The lane's column is marked, so that its grey cells do not read as a pass.
    assert 'empty' in index.columns[2].classes, index.columns
    assert 'empty' not in index.columns[1].classes, index.columns
    assert index.verdict('demo', 'native') == 'pass'
    assert index.verdict('demo', 'wasip2') == 'n/a'
    assert index.verdict('nativeonly', 'native') == 'n/a'
    assert index.verdict('nativeonly', 'wasip2') == 'n/a'
    assert 'wasip2: the lane built no test and no example' in Page(out / 'index.html').text
    nativeonly = matrix(out / 'nativeonly.html')
    assert nativeonly.rows() == {'works', 'works-noexcept'}, nativeonly.rows()
    assert nativeonly.verdict('works', 'wasip2') == 'n/a'
    check_pages(out)


def test_two_lanes_merge_into_one_matrix(root: Path) -> None:
    out = root / 'report'
    result = report(out, ('native', sample('native-pass')), ('wasip2', sample('wasip2-pass')))
    assert result.returncode == 0, outcome(result)
    index = matrix(out / 'index.html')
    assert index.names() == ['Library', 'native', 'wasip2'], index.names()
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
    unreadable = {
        'missing.xml': 'missing.xml',
        'garbage.xml': 'garbage.xml',
        'truncated.xml': 'truncated.xml',
        'html.xml': 'html.xml',
        'without-dump-tests.xml': '--dump-tests',
        'index-library.xml': 'a library named Index',
    }
    for name, named in unreadable.items():
        out = root / f'out-{name}'
        result = report(out, ('native', passing), ('wasip2', root / name))
        assert result.returncode == 2, (name, outcome(result))
        assert named in result.stderr, (name, named, outcome(result))
        assert not out.exists(), (name, 'nothing is written', sorted(out.rglob('*')))
    # A lane given without its file, twice, or with a name a file cannot have.
    for lanes in (['native'], [f'native={passing}', f'native={passing}'], [f'a/b={passing}']):
        out = root / 'out-lanes'
        arguments = [sys.executable, str(REPORT)]
        for lane in lanes:
            arguments += ['--lane', lane]
        result = subprocess.run([*arguments, '--out', str(out)], capture_output=True, text=True,
                                check=False)
        assert result.returncode == 2, (lanes, outcome(result))
        assert '--lane' in result.stderr, (lanes, outcome(result))
        assert not out.exists(), lanes
    # A directory the pages cannot be written into: a file is where it would be.
    blocked = root / 'a file'
    blocked.write_text('')
    result = report(blocked, ('native', passing))
    assert result.returncode == 2, outcome(result)
    assert f'cannot write {blocked}' in result.stderr, outcome(result)


def test_a_failure_outside_every_test_fails_the_lane(root: Path) -> None:
    # The handler of tools/throw_exception.cpp, which pass-noexcept links, does not compile: the
    # action is no test's, and pass-noexcept is compiled but never linked nor run.
    out = root / 'report'
    result = report(out, ('native', sample('native-dependency')))
    assert result.returncode == 1, outcome(result)
    lines = result.stderr.splitlines()
    assert 'report: native: demo/pass-noexcept: not run' in lines, outcome(result)
    outside = [line for line in lines if 'throw_exception.o' in line]
    assert len(outside) == 1 and 'compile' in outside[0], outcome(result)
    index = Page(out / 'index.html')
    problem = [href for href in index.links if href.startswith('output/native/')]
    assert len(problem) == 1, index.links
    assert 'planted: the handler does not compile' in linked(out / 'index.html', problem[0]).text
    demo = matrix(out / 'demo.html')
    assert demo.verdict('pass-noexcept', 'native') == 'not run'
    assert demo.verdict('pass', 'native') == 'n/a'
    output = linked(out / 'demo.html', demo.cells[('pass-noexcept', 'native')].href)
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
    assert "('<b>]]>&amp;</b>' == '\ufffd')" in output.text, output.text
    check_pages(out)


def tables(out: Path) -> dict[str, list[list[list[tuple[str, frozenset[str], str | None]]]]]:
    """The tables of the pages directly in out, by page."""
    return {page.name: [[[(cell.text, frozenset(cell.classes), cell.href) for cell in row]
                         for row in table] for table in Page(page).tables]
            for page in sorted(out.glob('*.html'))}


def test_samples_read_as_b2_writes_them_today(root: Path) -> None:
    # A sample is trimmed, and recorded once: a lane recorded now, untrimmed, gives the same
    # matrix, so the trimming changed nothing the report reads, and the b2 installed still
    # writes what the report expects.
    for name in record_samples.SAMPLES_BY_NAME:
        lane = name.split('-')[0]
        scratch = harness.scratch_superproject('demo')
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
    test_two_lanes_merge_into_one_matrix,
    test_unreadable_xml_exits_2,
    test_a_failure_outside_every_test_fails_the_lane,
    test_output_cdata_cannot_hold_is_shown,
    test_samples_read_as_b2_writes_them_today,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('report_test', CASES, sys.argv[1:]))
