#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Writes the table of webcpp's libraries that the index page includes, as AsciiDoc.

Usage: libraries.py --root <superproject> --pages <dir> --output <libraries.adoc>

A library is a directory of <root>/libs with a build.jam, as the Jamroot registers it, and
describes itself in meta/libraries.json, Boost's file: an object, or a list of them, with
Boost's fields and webcpp's "port-of", which is null for a library of webcpp's own and otherwise
names the original it ports: {"name", "language", "version", "url", "licence"}. A row of the
table is an object: the library's name, linked to its page, libs/<library>/doc/html/index.html,
as a path relative to the directory --pages names, where the index page is; its description;
and what it ports, linked to the original, or "original".

The text of a cell is written with the character references MrDocs uses in place of each
character AsciiDoc could read as markup, which postprocess.mjs decodes in the converted page:
a description may say C++, or hold a |.

Exit 0 with the table written; 1 when a library has no meta/libraries.json, no page, or a field
that is missing or not what it should be, each named; 2 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import os
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

PORT_FIELDS = ('name', 'language', 'version', 'url', 'licence')


class Invalid(Exception):
    """What makes a library's description unusable, said to the user."""


def escaped(text: str) -> str:
    """The text with each character AsciiDoc could read as markup written as MrDocs writes it."""
    return ''.join(ESCAPES.get(character, character) for character in text)


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


def rows(root: Path, pages: Path) -> list[str]:
    """The rows of the table, one per entry of each library, by the library's directory."""
    found = []
    for build in sorted((root / 'libs').glob('*/build.jam')):
        library = build.parent
        origin = library / 'meta/libraries.json'
        if not origin.is_file():
            raise Invalid(f'{origin}: there is no such file; every library of libs/ describes '
                          'itself in meta/libraries.json')
        if not (library / 'doc/Jamfile').is_file():
            raise Invalid(f'{library / "doc/Jamfile"}: there is no such file; every library of '
                          'libs/ has a page, which the index links to')
        try:
            described = json.loads(origin.read_text(encoding='utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise Invalid(f'{origin}: not JSON: {error}') from error
        entries = described if isinstance(described, list) else [described]
        if not entries or not all(isinstance(entry, dict) for entry in entries):
            raise Invalid(f'{origin}: neither an object nor a list of objects')
        page = Path(os.path.relpath(library / 'doc/html/index.html', pages)).as_posix()
        for entry in entries:
            found.append(f'| link:{page}[{escaped(text_field(entry, "name", origin))}]\n'
                         f'| {escaped(text_field(entry, "description", origin))}\n'
                         f'| {ports(entry, origin)}')
    return found


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description='Writes the index page\'s table of libraries.')
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--pages', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    options = parser.parse_args(argv)
    try:
        found = rows(options.root.resolve(), options.pages.resolve())
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
