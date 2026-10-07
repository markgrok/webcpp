#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/ci/assemble.py: the site keeps the tree's layout, so the index page's links to the
libraries' pages resolve, with the report beside them and a root page that sends a reader to the
index; a link to no file, to no fragment, from the server's root or out of the site is named and
fails; a missing page fails; an output directory that holds something is refused. Run with the
names of some cases to run only those."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

SITE = Path(__file__).resolve().parent / 'assemble.py'


def page(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'<!DOCTYPE html>\n<html><body>{body}</body></html>\n')


def built(scratch: Path, index_body: str = '') -> tuple[Path, Path]:
    """Pages where b2 doc and report.py write them, and their two directories."""
    docs = scratch / 'tree'
    page(docs / 'doc/html/index.html',
         '<a href="../../libs/alpha/doc/html/index.html">alpha</a>'
         '<a href="../../libs/beta/doc/html/">beta</a>'
         '<a href="https://webcpporg.github.io/webcpp/report/">matrix</a>'
         f'<a href="#top" id="top">top</a>{index_body}')
    page(docs / 'libs/alpha/doc/html/index.html',
         '<h2 id="usage">Usage</h2><a href="#usage">usage</a>'
         '<a href="https://github.com/webcpporg/alpha">source</a>')
    page(docs / 'libs/beta/doc/html/index.html', '<a name="old">old</a><a href="#old">old</a>')
    (docs / 'libs/beta/doc/html/.DS_Store').write_bytes(b'Finder')
    report = scratch / 'report'
    page(report / 'index.html', '<a href="alpha.html#row">alpha</a>')
    page(report / 'alpha.html', '<tr id="row"><td><a href="output/gcc-14/x.txt">x</a></td></tr>')
    (report / 'output/gcc-14').mkdir(parents=True)
    (report / 'output/gcc-14/x.txt').write_text('output\n')
    return docs, report


def run(docs: Path, report: Path, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SITE), '--docs', str(docs), '--report',
                           str(report), '--out', str(out)], capture_output=True, text=True,
                          check=False)


def test_the_site_keeps_the_tree_layout(scratch: Path) -> None:
    docs, report = built(scratch)
    out = scratch / 'site'
    result = run(docs, report, out)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert 'every link resolving' in result.stdout, result.stdout
    for name in ('index.html', 'doc/html/index.html', 'libs/alpha/doc/html/index.html',
                 'libs/beta/doc/html/index.html', 'report/index.html', 'report/alpha.html',
                 'report/output/gcc-14/x.txt'):
        assert (out / name).is_file(), name
    assert not (out / 'libs/beta/doc/html/.DS_Store').exists()
    root = (out / 'index.html').read_text()
    assert 'url=doc/html/index.html' in root and 'href="doc/html/index.html"' in root, root


def test_a_link_that_does_not_resolve_is_named(scratch: Path) -> None:
    docs, report = built(scratch, '<a href="../../libs/gamma/doc/html/index.html">gamma</a>'
                                  '<a href="../../libs/alpha/doc/html/index.html#nowhere">a</a>'
                                  '<img src="/logo.png">'
                                  '<a href="../../../elsewhere.html">out</a>')
    result = run(docs, report, scratch / 'site')
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    for text in ('doc/html/index.html: ../../libs/gamma/doc/html/index.html: '
                 'libs/gamma/doc/html/index.html does not exist',
                 "libs/alpha/doc/html/index.html has no id 'nowhere'",
                 "/logo.png: a path from the server's root",
                 '../../../elsewhere.html: outside the site',
                 '4 links of'):
        assert text in result.stderr, (text, result.stderr)


def test_a_missing_page_fails(scratch: Path) -> None:
    docs, report = built(scratch)
    (report / 'index.html').unlink()
    result = run(docs, report, scratch / 'site')
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert f'{report / "index.html"} does not exist' in result.stderr, result.stderr


def test_an_output_that_holds_something_is_refused(scratch: Path) -> None:
    docs, report = built(scratch)
    out = scratch / 'site'
    out.mkdir()
    (out / 'left.html').write_text('left over\n')
    result = run(docs, report, out)
    assert result.returncode == 2, (result.returncode, result.stderr)
    assert 'is not an empty directory' in result.stderr, result.stderr


CASES: list[Callable[[Path], None]] = [
    test_the_site_keeps_the_tree_layout,
    test_a_link_that_does_not_resolve_is_named,
    test_a_missing_page_fails,
    test_an_output_that_holds_something_is_refused,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'assemble_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='webcpp site ') as scratch:
            case(Path(scratch))
        print(f'{case.__name__}: ok')
    print('assemble_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
