#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/site/catalogue.py: a port and a library of webcpp's own give two entries, the
port's port_of holding the original and the other's null; a library's targets come from
--declared, sorted and without duplicates, empty when it declares none; a meta without a
"description" fails, naming the file and the field; a meta whose "key" differs from its
directory's name fails, naming both; and the catalogue, run twice on the same input, writes the
same file byte for byte. Each case builds a fake libs/ directory in a scratch directory. Run with
the names of some cases to run only those."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CATALOGUE = HERE / 'catalogue.py'


def write_library(libs: Path, directory: str, fields: dict[str, Any] | None = None) -> Path:
    """A library directory under libs, named directory, with a meta/libraries.json whose "key"
    is directory by default, overridden by fields."""
    meta = {
        'key': directory,
        'name': directory,
        'description': f'The {directory} library.',
        'category': ['Testing'],
        'port-of': None,
    }
    meta.update(fields or {})
    path = libs / directory
    (path / 'meta').mkdir(parents=True)
    (path / 'meta/libraries.json').write_text(json.dumps(meta))
    return path


def write_declared(root: Path, *pairs: str) -> Path:
    """The file --declared reads, one "<library> <target>" line per pair, as `b2 -d0
    declared-targets` prints them."""
    path = root / 'declared.txt'
    path.write_text(''.join(f'{pair}\n' for pair in pairs))
    return path


def run(libs: Path, declared: Path, out: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CATALOGUE), '--libs', str(libs),
                           '--declared', str(declared), '--out', str(out)],
                          capture_output=True, text=True, check=False, timeout=60)


def test_a_port_and_an_own_library_give_two_entries(root: Path) -> None:
    libs = root / 'libs'
    write_library(libs, 'alpha', {'description': 'A library of webcpp\'s own.'})
    write_library(libs, 'beta', {'description': 'A port.', 'port-of': {
        'name': 'Beta.js', 'language': 'JavaScript', 'version': '1.2.3',
        'url': 'https://example.org/beta', 'licence': 'MIT'}})
    declared = write_declared(root, 'alpha native', 'beta native')
    out = root / 'libraries.json'
    result = run(libs, declared, out)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    written = json.loads(out.read_text())
    assert [entry['key'] for entry in written] == ['alpha', 'beta'], written
    assert written[0]['port_of'] is None, written[0]
    assert written[1]['port_of'] == {
        'name': 'Beta.js', 'language': 'JavaScript', 'version': '1.2.3',
        'url': 'https://example.org/beta', 'licence': 'MIT'}, written[1]


def test_targets_come_from_declared_sorted_without_duplicates(root: Path) -> None:
    libs = root / 'libs'
    write_library(libs, 'alpha')
    declared = write_declared(root, 'alpha wasip3', 'alpha native', 'alpha wasip3',
                              'alpha wasip2')
    out = root / 'libraries.json'
    result = run(libs, declared, out)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    written = json.loads(out.read_text())
    assert written[0]['targets'] == ['native', 'wasip2', 'wasip3'], written


def test_a_library_with_no_declared_target_has_an_empty_list(root: Path) -> None:
    libs = root / 'libs'
    write_library(libs, 'alpha')
    write_library(libs, 'beta')
    declared = write_declared(root, 'beta native')
    out = root / 'libraries.json'
    result = run(libs, declared, out)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    written = {entry['key']: entry['targets'] for entry in json.loads(out.read_text())}
    assert written == {'alpha': [], 'beta': ['native']}, written


def test_a_meta_without_description_fails(root: Path) -> None:
    libs = root / 'libs'
    directory = libs / 'alpha'
    (directory / 'meta').mkdir(parents=True)
    origin = directory / 'meta/libraries.json'
    origin.write_text(json.dumps({'key': 'alpha', 'name': 'alpha', 'category': ['Testing'],
                                  'port-of': None}))
    declared = write_declared(root, 'alpha native')
    out = root / 'libraries.json'
    result = run(libs, declared, out)
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert result.stdout == f'catalogue.py: {origin}: "description" is not a string that says ' \
                            'something\n', result.stdout
    assert not out.exists()


def test_a_meta_whose_key_differs_from_its_directory_fails(root: Path) -> None:
    libs = root / 'libs'
    write_library(libs, 'alpha', {'key': 'not-alpha'})
    declared = write_declared(root, 'alpha native')
    out = root / 'libraries.json'
    result = run(libs, declared, out)
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert "'not-alpha'" in result.stdout and "'alpha'" in result.stdout, result.stdout
    assert not out.exists()


def test_output_is_byte_for_byte_stable(root: Path) -> None:
    libs = root / 'libs'
    write_library(libs, 'alpha', {'port-of': {
        'name': 'Alpha.js', 'language': 'JavaScript', 'version': '2.0.0',
        'url': 'https://example.org/alpha', 'licence': 'MIT'}})
    write_library(libs, 'beta')
    declared = write_declared(root, 'beta wasip2', 'alpha native', 'beta native')
    out = root / 'libraries.json'
    first = run(libs, declared, out)
    assert first.returncode == 0, (first.returncode, first.stdout, first.stderr)
    written = out.read_bytes()
    second = run(libs, declared, out)
    assert second.returncode == 0, (second.returncode, second.stdout, second.stderr)
    assert out.read_bytes() == written


CASES = [
    test_a_port_and_an_own_library_give_two_entries,
    test_targets_come_from_declared_sorted_without_duplicates,
    test_a_library_with_no_declared_target_has_an_empty_list,
    test_a_meta_without_description_fails,
    test_a_meta_whose_key_differs_from_its_directory_fails,
    test_output_is_byte_for_byte_stable,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'catalogue_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='webcpp catalogue ') as scratch:
            case(Path(scratch))
        print(f'{case.__name__}: ok')
    print('catalogue_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
