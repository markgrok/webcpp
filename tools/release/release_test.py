#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/release/release.py on scratch git superprojects (tools/release/scratch.py), and
the Jamroot's targets on scratch copies of this superproject (tools/test/harness.py). Run with
the names of some cases to run only those."""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import changelog
import release
import scratch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'test'))
import harness  # noqa: E402  (tools/test, put on the path above)

V010 = release.Version.parse('0.1.0')
V020 = release.Version.parse('0.2.0')


def expect(found: list[str], *texts: str) -> None:
    """Asserts that some finding holds each of texts."""
    for text in texts:
        assert any(text in finding for finding in found), (text, found)


def run_main(*arguments: str) -> tuple[int, str, str]:
    """release.main run on arguments: its exit status, and what it printed on its standard
    output and on its standard error."""
    output, error = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
        status = release.main(list(arguments))
    return status, output.getvalue(), error.getvalue()


def test_versions_are_named(directory: Path) -> None:
    assert release.Version.of_number(100) == V010
    assert (V010.lib, V010.anchor, V010.tag) == ('0_1', '0-1-0', 'webcpp-0.1.0')
    other = release.Version.of_number(100203)
    assert (other.name, other.lib) == ('1.2.3', '1_2_3')
    assert release.Version.of_number(99999) == release.Version(0, 999, 99)
    assert release.Version.parse('0.10.0') > release.Version.parse('0.9.0')


def test_version_must_agree(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    assert release.version_findings(tree.root, V010) == []
    tree.change('config', 'include/webcpp/version.hpp',
                scratch.VERSION_HPP.format(number=101, lib='0_1'))
    expect(release.version_findings(tree.root, release.Version.parse('0.1.1')),
           'WEBCPP_VERSION names 0.1.1, and WEBCPP_LIB_VERSION "0_1" is not "0_1_1"')
    expect(release.version_findings(tree.root, V010),
           'the build read the version 0.1.0, and libs/config/include/webcpp/version.hpp names '
           '0.1.1')


def test_check_fails_by_name(directory: Path) -> None:
    # What the command prints and its exit status: 0 when the version agrees, 1 with each fault
    # on a line of its own, and 2, naming what is wrong and with no traceback, for a tree
    # without libs/config, a header that does not define the version as config does, and a
    # version that is no <major>.<minor>.<patch>.
    tree = scratch.make_tree(directory)
    root = str(tree.root)
    assert run_main('check', '--root', root, '--version', '0.1.0') == (0, '', '')
    status, output, error = run_main('check', '--root', root, '--version', '0.2.0')
    assert (status, error) == (1, ''), (status, error)
    assert output == ('check: the build read the version 0.2.0, and '
                      f'{release.HEADER} names 0.1.0\n'), output
    header = tree.library('config') / 'include/webcpp/version.hpp'
    for text in ('#define WEBCPP_VERSION 100  // 0.1.0\n#define WEBCPP_LIB_VERSION "0_1"\n',
                 '#define WEBCPP_VERSION 100\n#define WEBCPP_LIB_VERSION 0_1\n',
                 '#define WEBCPP_VERSION 100\n'):
        scratch.write(header, text)
        assert run_main('check', '--root', root, '--version', '0.1.0') == (
            2, '', f'check: {release.HEADER} has no lines `#define WEBCPP_VERSION <number>` and '
                   '`#define WEBCPP_LIB_VERSION "<text>"`\n'), text
    header.write_bytes(b'#define WEBCPP_VERSION 100\n#define WEBCPP_LIB_VERSION "\xff"\n')
    status, output, error = run_main('check', '--root', root, '--version', '0.1.0')
    assert (status, output) == (2, ''), (status, output)
    assert error.startswith(f'check: {release.HEADER} cannot be read: '), error
    shutil.rmtree(tree.library('config'))
    assert run_main('check', '--root', root, '--version', '0.1.0') == (
        2, '', f'check: {release.HEADER} does not exist: check out libs/config\n')
    assert run_main('check', '--root', root, '--version', '0.1') == (
        2, '', 'check: 0.1 is no version <major>.<minor>.<patch>\n')


def test_scratch_files_keep_their_form(directory: Path) -> None:
    # The scratch trees' changelogs and notes are read by tools/release/changelog.py, the one
    # reader of both forms, as the real ones are: a form it refuses would fail a check for a
    # reason no case meant.
    lines = ('* Added a thing.', '* Fixed another thing.')
    for path, text in (
            ('libs/alpha/doc/changelog.adoc', scratch.changelog_text('alpha')),
            ('libs/alpha/doc/changelog.adoc',
             scratch.changelog_text('alpha', lines, (('0.2.0', lines), ('0.1.0', lines)))),
            ('doc/releases/0.1.0.adoc', scratch.notes_text('0.1.0', new=('alpha', 'config'))),
            ('doc/releases/0.2.0.adoc',
             scratch.notes_text('0.2.0', preparing=False, new=('gamma',),
                                updated=(('alpha', '0.2.0'), ('beta', '0.2.0')),
                                removed=('delta',), tools=lines, compilers=('gcc-15',)))):
        assert changelog.file_findings(path, text) == [], (path, text)
    notes, _ = changelog.parse_notes(
        scratch.notes_text('0.2.0', new=('gamma',), updated=(('alpha', '0.2.0'),),
                           removed=('delta',), compilers=('gcc-15', 'wasip2')), '0.2.0')
    assert notes.preparing
    assert [name for name, _ in notes.new] == ['gamma']
    assert notes.updated == [('alpha', '0.2.0')]
    assert [name for name, _ in notes.removed] == ['delta']
    assert notes.compilers == ['gcc-15', 'wasip2']
    tree = scratch.make_tree(directory)
    for path in ('doc/releases/0.1.0.adoc', 'libs/alpha/doc/changelog.adoc',
                 'libs/beta/doc/changelog.adoc', 'libs/config/doc/changelog.adoc'):
        assert changelog.file_findings(path, (tree.root / path).read_text()) == [], path


def mrdocs_root() -> Path:
    """The MrDocs of this checkout, as tools/test/doc_test.py links it: $MRDOCS_ROOT, else
    .local/mrdocs."""
    configured = os.environ.get('MRDOCS_ROOT')
    return Path(configured) if configured else harness.ROOT / '.local/mrdocs'


def git_checkout(root: Path) -> None:
    """Makes the harness's scratch superproject root a git checkout whose libraries, config and
    demo, are gitlinks, config holding the version.hpp of 0.1.0, with an index and notes of its
    own that name config and demo: the copy's are this superproject's, which name others."""
    scratch.write(root / 'libs/config/build.jam', 'project /webcpp/config ;\n\nalias config ;\n')
    scratch.write(root / 'libs/config/include/webcpp/version.hpp',
                  scratch.VERSION_HPP.format(number=100, lib='0_1'))
    for name in ('config', 'demo'):
        scratch.write(root / 'libs' / name / 'doc/changelog.adoc', scratch.changelog_text(name))
        scratch.git(root / 'libs' / name, 'init', '-q')
        scratch.git(root / 'libs' / name, 'add', '.')
        scratch.git(root / 'libs' / name, 'commit', '-q', '-m', name)
    scratch.write(root / 'doc/index.adoc', scratch.index_text(('0.1.0',)))
    scratch.write(root / 'doc/releases/0.1.0.adoc',
                  scratch.notes_text('0.1.0', new=('config', 'demo')))
    scratch.git(root, 'init', '-q')
    scratch.git(root, 'add', '.')
    scratch.git(root, 'commit', '-q', '-m', 'The scratch superproject')


def test_jamroot_targets(root: Path) -> None:
    git_checkout(root)
    harness.expect(harness.run_b2(root, '-d0', 'check-release'), True)
    # check-release compiles nothing, so it needs no Boost, as declared-targets needs none.
    harness.configure(root, harness.without_boost() + 'using boost : 1.92 ;\n')
    harness.expect(harness.run_b2(root, '-d0', 'check-release', env_extra={'BOOST_ROOT': None}),
                   True)
    # A fault fails the target, which prints it.
    scratch.write(root / 'libs/config/include/webcpp/version.hpp',
                  scratch.VERSION_HPP.format(number=100, lib='0_2'))
    harness.expect(harness.run_b2(root, 'check-release', env_extra={'BOOST_ROOT': None}), False,
                   'check: libs/config/include/webcpp/version.hpp: WEBCPP_VERSION names 0.1.0, '
                   'and WEBCPP_LIB_VERSION "0_2" is not "0_1"')


def test_jamroot_reads_the_version(root: Path) -> None:
    # The version check-release hands release.py, read from version.hpp's WEBCPP_VERSION: b2 -n
    # prints the command and runs nothing.
    header = root / 'libs/config/include/webcpp/version.hpp'
    for number, name in ((100, '0.1.0'), (100203, '1.2.3'), (1000000, '10.0.0'),
                         (9999, '0.99.99'), (2001000, '20.10.0')):
        scratch.write(header, scratch.VERSION_HPP.format(number=number, lib='0_1'))
        harness.expect(harness.run_b2(root, '-n', 'check-release'), True,
                       f'--version "{name}"')
    scratch.write(header, '#define WEBCPP_VERSION 0x64\n')
    harness.expect(harness.run_b2(root, '-n', 'check-release'), False,
                   'libs/config/include/webcpp/version.hpp has no line '
                   '`#define WEBCPP_VERSION <number>`')


def test_jamroot_without_config(root: Path) -> None:
    # The copy holds no libs/config: everything but the release targets builds, the doc included,
    # and those stop, naming the header. The doc build reads the files demo's git lists, as
    # tools/test/doc_test.py's prepare gives them.
    (root / '.local/mrdocs').symlink_to(mrdocs_root())
    scratch.git(root / 'libs/demo', 'init', '-q')
    harness.expect(harness.run_b2(root, '-d0', 'declared-targets'), True)
    harness.expect(harness.run_b2(root, '-n', '-d0'), True)
    harness.expect(harness.run_b2(root, 'libs/demo/test'), True)
    harness.expect(harness.run_b2(root, '-d0', 'doc'), True)
    harness.expect(harness.run_b2(root, '-d0', 'check-release'), False,
                   'libs/config/include/webcpp/version.hpp', 'check out libs/config')


CASES: list[Callable[[Path], None]] = [
    test_versions_are_named,
    test_version_must_agree,
    test_check_fails_by_name,
    test_scratch_files_keep_their_form,
]

B2_CASES: list[Callable[[Path], None]] = [
    test_jamroot_targets,
    test_jamroot_reads_the_version,
    test_jamroot_without_config,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in (*CASES, *B2_CASES)}
    if unknown:
        print(f'release_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='webcpp release ') as directory:
            case(Path(directory))
        print(f'{case.__name__}: ok')
    for case in B2_CASES:
        if argv and case.__name__ not in argv:
            continue
        root = harness.scratch_superproject('demo')
        try:
            case(root)
        finally:
            shutil.rmtree(root)
        print(f'{case.__name__}: ok')
    print('release_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
