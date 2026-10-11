#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Writes libraries.json, the site's catalogue, from every library's meta/libraries.json and the
targets the build declares.

Usage: catalogue.py --libs <libs-dir> --declared <file> --out <libraries.json>

A library is a directory of <libs-dir> with a meta/libraries.json, Boost's file, read as
tools/doc/libraries.py reads it, through its meta_entries and text_field: one object (a list of
more than one is an error; webcpp holds one library per directory), with "key", "name",
"description", "category" (a list of at least one), and "port-of", null for a library of
webcpp's own and otherwise the original it ports, {"name", "language", "version", "url",
"licence"}. "key" must be the directory's name, so that a catalogue entry and its directory
agree; the catalogue writes it as "port_of".

<file> holds the lines `b2 -d0 declared-targets` prints, "<library> <target>", one line per
target a library's build declares; a library's "targets" are those lines' targets for it,
sorted, without duplicates, and an empty list when the file names none of its targets.

Writes a JSON array of the site's Library objects (site/src/context.ts), sorted by "key", with
indent=4, sort_keys=True, ensure_ascii=False, and a final newline; exit 0. On an error it writes
nothing, prints `catalogue.py: <file>: <what>` and exits 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

# The metas are read as tools/doc/libraries.py reads them, through the function it factors out
# for this: both this file and libraries.py's own rows() call meta_entries.
sys.path.insert(0, str(ROOT / 'tools/doc'))
from libraries import Invalid, PORT_FIELDS, URL, meta_entries, text_field  # noqa: E402


def category_of(entry: dict[str, Any], origin: Path) -> list[str]:
    """The "category" field: a list of at least one string that each say something."""
    value = entry.get('category')
    if (not isinstance(value, list) or not value
            or not all(isinstance(item, str) and item.strip() for item in value)):
        raise Invalid(f'{origin}: "category" is not a list of at least one string that says '
                      'something')
    return [item.strip() for item in value]


def port_of_of(entry: dict[str, Any], origin: Path) -> dict[str, str] | None:
    """The "port_of" the catalogue writes: null for a library of webcpp's own, else the
    original's name, language, version, url and licence, as "port-of" names them."""
    if 'port-of' not in entry:
        raise Invalid(f'{origin}: there is no "port-of", which is null for a library of '
                      'webcpp\'s own and otherwise names the original it ports')
    original = entry['port-of']
    if original is None:
        return None
    if not isinstance(original, dict):
        raise Invalid(f'{origin}: "port-of" is neither null nor an object')
    fields = {name: text_field(original, name, origin) for name in PORT_FIELDS}
    if not URL.fullmatch(fields['url']):
        raise Invalid(f'{origin}: the "url" of "port-of" is not an https URL: {fields["url"]}')
    return fields


def library_entry(directory: Path, targets: dict[str, list[str]]) -> dict[str, Any]:
    """The catalogue's entry for directory: its one meta, its targets (empty when targets names
    none of it), its page and its repository."""
    origin = directory / 'meta/libraries.json'
    entries = meta_entries(origin)
    if len(entries) != 1:
        raise Invalid(f'{origin}: holds {len(entries)} libraries; the catalogue wants one '
                      'library, with one key, per directory')
    entry = entries[0]
    key = text_field(entry, 'key', origin)
    if key != directory.name:
        raise Invalid(f'{origin}: "key" is {key!r}, not {directory.name!r}, the name of the '
                      'directory that holds it')
    return {
        'key': key,
        'name': text_field(entry, 'name', origin),
        'description': text_field(entry, 'description', origin),
        'category': category_of(entry, origin),
        'targets': sorted(set(targets.get(key, ()))),
        'port_of': port_of_of(entry, origin),
        'page': f'libs/{key}/',
        'repository': f'https://github.com/webcpporg/{key}',
    }


def library_directories(libs: Path) -> list[Path]:
    """Every directory of libs with a meta/libraries.json, sorted by name."""
    if not libs.is_dir():
        raise Invalid(f'{libs}: not a directory')
    return sorted((directory for directory in libs.iterdir()
                   if directory.is_dir() and (directory / 'meta/libraries.json').is_file()),
                  key=lambda directory: directory.name)


def declared_targets(path: Path) -> dict[str, list[str]]:
    """Every library's targets, from the lines `b2 -d0 declared-targets` prints, "<library>
    <target>"; a library absent from path has none."""
    try:
        text = path.read_text(encoding='utf-8')
    except OSError as error:
        raise Invalid(f'{path}: {error.strerror}') from error
    found: dict[str, list[str]] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        words = line.split()
        if len(words) != 2:
            raise Invalid(f'{path}:{number}: not "<library> <target>": {line}')
        library, target = words
        found.setdefault(library, []).append(target)
    return found


def catalogue(libs: Path, declared: Path) -> list[dict[str, Any]]:
    """The catalogue's entries, one per directory of libs, sorted by key."""
    targets = declared_targets(declared)
    found = [library_entry(directory, targets) for directory in library_directories(libs)]
    found.sort(key=lambda entry: entry['key'])
    return found


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Writes libraries.json, the site's catalogue, from every library's meta and "
                    'the targets the build declares.')
    parser.add_argument('--libs', required=True, type=Path)
    parser.add_argument('--declared', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    options = parser.parse_args(argv)
    try:
        found = catalogue(options.libs, options.declared)
    except Invalid as invalid:
        print(f'catalogue.py: {invalid}')
        return 1
    text = json.dumps(found, indent=4, sort_keys=True, ensure_ascii=False) + '\n'
    options.out.parent.mkdir(parents=True, exist_ok=True)
    options.out.write_text(text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
