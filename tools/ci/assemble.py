#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Assembles the site GitHub Pages serves at https://webcpporg.github.io/webcpp/, and checks
that every link in it resolves.

Usage: assemble.py --docs ROOT --report DIR --out DIR

ROOT holds the pages `b2 doc` built, where it builds them: doc/html/ (the index page) and
libs/<name>/doc/html/ (each library's page), a superproject's root or a copy of those
directories. DIR is what tools/report/report.py wrote. The site keeps the tree's layout, since
the index links each page by its path in the tree (../../libs/<name>/doc/html/index.html):

  index.html                  sends a reader to doc/html/index.html, the index page;
  doc/html/                   the index page;
  libs/<name>/doc/html/       each library's page;
  report/                     the test matrix, which the pages link to at /webcpp/report/.

Every href and src of every page that is not a URL (no scheme, not //) must name a file of the
site, a directory standing for its index.html, and its fragment, if any, an id or a name in
that page. Exit 0 with the site written; 1 when a page is missing or a link does not resolve,
each named; 2 on a usage error or when DIR exists and is not empty.
"""

from __future__ import annotations

import argparse
import posixpath
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

# The page at the site's root, which sends a reader to the index page: the index links the
# libraries' pages by their paths in the tree, from doc/html/.
REDIRECT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="0; url=doc/html/index.html">
<link rel="canonical" href="doc/html/index.html">
<title>webcpp</title>
<style>
:root { color-scheme: light dark; }
body {
  margin: 0; padding: 24px 16px;
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial,
    sans-serif;
}
</style>
</head>
<body>
<p>The libraries of webcpp are on <a href="doc/html/index.html">their index page</a>.</p>
</body>
</html>
"""


class Failure(Exception):
    """What keeps the site from being written whole, said to the user."""


class Links(HTMLParser):
    """The links of a page (each href and src) and the fragments it defines (each id and name)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.anchors: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if value is None:
                continue
            if name in ('href', 'src'):
                self.links.append(value)
            elif name == 'id' or (name == 'name' and tag == 'a'):
                self.anchors.add(value)


def read(page: Path) -> Links:
    parser = Links()
    parser.feed(page.read_text(encoding='utf-8', errors='replace'))
    parser.close()
    return parser


def copy(source: Path, destination: Path) -> None:
    """Copies the directory of pages source to destination, which it requires an index.html."""
    if not (source / 'index.html').is_file():
        raise Failure(f'{source / "index.html"} does not exist; build the pages with b2 doc')
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('.*'))


def assemble(docs: Path, report: Path, out: Path) -> None:
    """Writes the site into out, which is empty or does not exist."""
    copy(docs / 'doc/html', out / 'doc/html')
    for library in sorted((docs / 'libs').glob('*/doc/html')):
        name = library.parent.parent.name
        copy(library, out / 'libs' / name / 'doc/html')
    copy(report, out / 'report')
    (out / 'index.html').write_text(REDIRECT, encoding='utf-8')


def broken_links(site: Path) -> list[str]:
    """Each link of a page of site that resolves to no file, or to no fragment of its page."""
    pages = {page.relative_to(site).as_posix(): read(page) for page in sorted(site.rglob('*.html'))}
    broken = []
    for name, page in pages.items():
        for link in page.links:
            parts = urlsplit(link)
            if parts.scheme or parts.netloc:
                continue
            path = unquote(parts.path)
            if path.startswith('/'):
                broken.append(f'{name}: {link}: a path from the server\'s root, which the site '
                              'at /webcpp/ does not have')
                continue
            target = name
            if path:
                target = posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
                if target == '..' or target.startswith('../'):
                    broken.append(f'{name}: {link}: outside the site')
                    continue
                if (site / target).is_dir():
                    target = posixpath.join(target, 'index.html') if target != '.' else (
                        'index.html')
                if not (site / target).is_file():
                    broken.append(f'{name}: {link}: {target} does not exist')
                    continue
            fragment = unquote(parts.fragment)
            if fragment and target in pages and fragment not in pages[target].anchors:
                broken.append(f'{name}: {link}: {target} has no id {fragment!r}')
    return broken


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='assemble.py',
                                     description=(__doc__ or '').split('\n', 1)[0])
    parser.add_argument('--docs', required=True, type=Path, metavar='ROOT')
    parser.add_argument('--report', required=True, type=Path, metavar='DIR')
    parser.add_argument('--out', required=True, type=Path, metavar='DIR')
    options = parser.parse_args(arguments)
    out: Path = options.out
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        parser.error(f'--out {out} exists and is not an empty directory')
    try:
        assemble(options.docs, options.report, out)
    except Failure as failure:
        print(f'assemble.py: {failure}', file=sys.stderr)
        return 1
    broken = broken_links(out)
    if broken:
        print('\n'.join(f'assemble.py: {text}' for text in broken), file=sys.stderr)
        print(f'assemble.py: {len(broken)} link{"s" if len(broken) != 1 else ""} of {out} do not '
              'resolve', file=sys.stderr)
        return 1
    pages = sum(1 for _ in out.rglob('*.html'))
    print(f'assemble.py: wrote {out}, {pages} pages, every link resolving')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
