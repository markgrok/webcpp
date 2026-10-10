#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Writes the table of webcpp's libraries that the index page includes, as AsciiDoc.

Usage: libraries.py --root <superproject> --output <libraries.adoc> [--page <library>=<page> ...]
                    [--left-out <library>=<reason> ...]

A library is a directory of <root>/libs with a build.jam, as the Jamroot registers it. It has a
page, which its doc/Jamfile declares, `webcpp.doc <library> : <page>.adoc ;`, and which is there:
a doc Jamfile that declares the reference alone, or nothing, would have the index link a page
that the build never makes. The pages are what the build declares, each given as --page by
tools/doc/doc.jam, which loads every library's doc Jamfile; no Jamfile is read here. And a
library describes itself in meta/libraries.json, Boost's file: an object, or a list of them,
with Boost's fields and webcpp's "port-of", which is null for a library of webcpp's own and
otherwise names the original it ports: {"name", "language", "version", "url", "licence"}. A row
of the table is an object: the library's name, linked to its page,
{library-pages}<library>/{library-page}, two attributes the index page is converted with, so
that one table links the pages where b2 builds them and where the site publishes them
(tools/doc/doc.jam); its description; and what it ports, linked to the original, or
"original". A library --left-out names, whose page this build does not make because a library
webcpp does not build was not found (webcpp.left-out), is named with the reason and no link, so
that the index never links a page that is not there.

The text of a cell is written with the character references MrDocs uses in place of each
character AsciiDoc could read as markup, which postprocess.mjs decodes in the converted page:
a description may say C++, or hold a |. An apostrophe in a word of prose is the one exception:
it is written as it is, so that Asciidoctor makes it curly, as it does every other apostrophe of
the page's prose. One in what reads as code, between backticks, or in a URL stays straight.

Exit 0 with the table written; 1 when a library has no meta/libraries.json, no page, or a field
that is missing or not what it should be, each named; 2 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# MrDocs's table: each character its AsciiDoc generator escapes, and the reference it writes.
ESCAPES = {'^': '&circ;', '_': '&lowbar;', '*': '&ast;', '`': '&grave;', '#': '&num;',
           '[': '&lsqb;', ']': '&rsqb;', '{': '&lcub;', '}': '&rcub;', '<': '&lt;', '>': '&gt;',
           '\\': '&bsol;', '|': '&verbar;', '-': '&hyphen;', '=': '&equals;', '&': '&amp;',
           ';': '&semi;', '+': '&plus;', ':': '&colon;', '.': '&period;', '"': '&quot;',
           "'": '&apos;', '/': '&sol;'}

URL = re.compile(r'https://[^\s\[\]]+')

# An apostrophe in a word, between a letter or a digit and a letter: the one Asciidoctor's
# replacements make curly in the page's prose, ([[:alnum:]])'(?=[[:alpha:]]).
APOSTROPHE = re.compile(r"(?<=[^\W_])'(?=[^\W\d_])")

# What of a text is no prose, whose apostrophes stay straight: code between backticks, and a URL.
UNREAD = re.compile(r'`[^`]*`|\b[a-z][a-z0-9+.-]*://\S*')

PORT_FIELDS = ('name', 'language', 'version', 'url', 'licence')


class Invalid(Exception):
    """What makes a library's description unusable, said to the user."""


def escaped(text: str) -> str:
    """The text with each character AsciiDoc could read as markup written as MrDocs writes it,
    except an apostrophe in a word of its prose, which Asciidoctor then makes curly."""
    prose = [True] * len(text)
    for unread in UNREAD.finditer(text):
        prose[unread.start():unread.end()] = [False] * (unread.end() - unread.start())
    curled = {match.start() for match in APOSTROPHE.finditer(text) if prose[match.start()]}
    return ''.join(character if index in curled else ESCAPES.get(character, character)
                   for index, character in enumerate(text))


def text_field(entry: dict[str, Any], name: str, origin: Path) -> str:
    """The field of an entry, which must be a string that is not empty."""
    value = entry.get(name)
    if not isinstance(value, str) or not value.strip():
        raise Invalid(f'{origin}: "{name}" is not a string that says something')
    return value.strip()


def ports(entry: dict[str, Any], origin: Path) -> str:
    """The cell that says what the library ports."""
    if 'port-of' not in entry:
        raise Invalid(f'{origin}: there is no "port-of", which is null for a library of '
                      'webcpp\'s own and otherwise names the original it ports')
    original = entry['port-of']
    if original is None:
        return 'original'
    if not isinstance(original, dict):
        raise Invalid(f'{origin}: "port-of" is neither null nor an object')
    fields = {name: text_field(original, name, origin) for name in PORT_FIELDS}
    if not URL.fullmatch(fields['url']):
        raise Invalid(f'{origin}: the "url" of "port-of" is not an https URL: {fields["url"]}')
    return (f'link:{fields["url"]}[{escaped(fields["name"])} {escaped(fields["version"])}], in '
            f'{escaped(fields["language"])} ({escaped(fields["licence"])})')


def page_of(library: Path, pages: dict[str, Path]) -> Path:
    """The page library's doc/Jamfile declares, as the build gives it in pages, which must be
    there."""
    jamfile = library / 'doc/Jamfile'
    if not jamfile.is_file():
        raise Invalid(f'{jamfile}: there is no such file; every library of libs/ has a page, '
                      'which the index links to')
    page = pages.get(library.name)
    if page is None:
        raise Invalid(f'{jamfile}: declares no page, webcpp.doc {library.name} : <page>.adoc ;, '
                      'and every library of libs/ has a page, which the index links to')
    if not page.is_file():
        raise Invalid(f'{page}: there is no such file; libs/{library.name}/doc/Jamfile declares it '
                      f'the page of {library.name}, which the index links to')
    return page


def rows(root: Path, pages: dict[str, Path], left_out: dict[str, str] | None = None) -> list[str]:
    """The rows of the table, one per entry of each library, by the library's directory; a
    library of left_out without a link, with its reason."""
    left_out = left_out or {}
    found = []
    for build in sorted((root / 'libs').glob('*/build.jam')):
        library = build.parent
        origin = library / 'meta/libraries.json'
        if not origin.is_file():
            raise Invalid(f'{origin}: there is no such file; every library of libs/ describes '
                          'itself in meta/libraries.json')
        page_of(library, pages)
        try:
            described = json.loads(origin.read_text(encoding='utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise Invalid(f'{origin}: not JSON: {error}') from error
        entries = described if isinstance(described, list) else [described]
        if not entries or not all(isinstance(entry, dict) for entry in entries):
            raise Invalid(f'{origin}: neither an object nor a list of objects')
        page = f'{{library-pages}}{library.name}/{{library-page}}'
        for entry in entries:
            name = escaped(text_field(entry, 'name', origin))
            if library.name in left_out:
                named = f'{name} (left out of this build: {escaped(left_out[library.name])})'
            else:
                named = f'link:{page}[{name}]'
            found.append(f'| {named}\n'
                         f'| {escaped(text_field(entry, "description", origin))}\n'
                         f'| {ports(entry, origin)}')
    return found


def page_argument(text: str) -> tuple[str, Path]:
    library, separator, page = text.partition('=')
    if not separator or not library or not page:
        raise argparse.ArgumentTypeError(f'{text!r} is not <library>=<page>')
    return library, Path(page)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description='Writes the index page\'s table of libraries.')
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--page', action='append', default=[], type=page_argument,
                        metavar='LIBRARY=PAGE', help='the page a library\'s doc Jamfile declares')
    parser.add_argument('--left-out', action='append', default=[], type=page_argument,
                        metavar='LIBRARY=REASON',
                        help='a library whose page this build does not make, and why')
    options = parser.parse_args(argv)
    try:
        left_out = {library: str(reason) for library, reason in options.left_out}
        found = rows(options.root.resolve(), dict(options.page), left_out)
    except Invalid as invalid:
        print(f'libraries.py: {invalid}')
        return 1
    table = '[cols="1,3,2",options="header"]\n|===\n| Library | Description | Ports\n'
    table += ''.join(f'\n{row}\n' for row in found) + '|===\n'
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(table)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
