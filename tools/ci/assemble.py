#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Assembles the site GitHub Pages serves at https://webcpporg.github.io/webcpp/, and checks
that every link in it resolves.

Usage: assemble.py --docs ROOT --report DIR --out DIR

ROOT holds the pages `b2 doc -sWEBCPP_INDEX=site` built, where it builds them: doc/html/ (the
index page, whose links that option points at libs/<name>/) and libs/<name>/doc/html/ (each
library's page), a superproject's root or a copy of those directories. DIR is what
tools/report/report.py wrote. The site is:

  index.html          the index page, with what doc/html/ holds beside it;
  libs/<name>/        each library's page, with what its doc/html/ holds;
  report/             the test matrix, which the pages link to at /webcpp/report/.

Every library of ROOT/libs has its page, and the index page links to each. Every href and src of
every page that is not a URL (no scheme, not //) names a file of the site, a directory standing
for its index.html, and its fragment, if any, an id or a name in that page: an index built
without -sWEBCPP_INDEX=site links out of the site, and fails. Exit 0 with the site written; 1
when a page is missing, unlinked, or a link does not resolve, each named; 2 on a usage error or
when DIR exists and is not empty.
"""

from __future__ import annotations

import argparse
import posixpath
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


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
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('.*'), dirs_exist_ok=True)


def assemble(docs: Path, report: Path, out: Path) -> list[str]:
    """Writes the site into out, which is empty or does not exist, and returns the libraries."""
    libraries = sorted(library.name for library in (docs / 'libs').glob('*') if library.is_dir())
    if not libraries:
        raise Failure(f'{docs / "libs"} holds no library')
    copy(docs / 'doc/html', out)
    for name in libraries:
        copy(docs / 'libs' / name / 'doc/html', out / 'libs' / name)
    copy(report, out / 'report')
    return libraries


def unlinked(site: Path, libraries: list[str]) -> list[str]:
    """Each library whose page the index page does not link to."""
    linked = set()
    for link in read(site / 'index.html').links:
        parts = urlsplit(link)
        if not (parts.scheme or parts.netloc):
            linked.add(posixpath.normpath(unquote(parts.path)).removesuffix('/index.html'))
    return [f'index.html: no link to libs/{name}/, the page of the library {name}'
            for name in libraries if f'libs/{name}' not in linked]


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
        libraries = assemble(options.docs, options.report, out)
    except Failure as failure:
        print(f'assemble.py: {failure}', file=sys.stderr)
        return 1
    broken = unlinked(out, libraries) + broken_links(out)
    if broken:
        print('\n'.join(f'assemble.py: {text}' for text in broken), file=sys.stderr)
        print(f'assemble.py: {len(broken)} fault{"s" if len(broken) != 1 else ""} in the links '
              f'of {out}', file=sys.stderr)
        return 1
    pages = sum(1 for _ in out.rglob('*.html'))
    print(f'assemble.py: wrote {out}, {pages} pages, {len(libraries)} '
          f'librar{"ies" if len(libraries) != 1 else "y"}, every link resolving')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
