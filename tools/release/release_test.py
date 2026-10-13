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
import gzip
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import types
import zlib
from collections.abc import Callable, Iterator
from pathlib import Path

import changelog
import release
import matrix  # tools/ci, which release puts on the path
import scratch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'test'))
import harness  # noqa: E402  (tools/test, put on the path above)

V010 = release.Version.parse('0.1.0')
V020 = release.Version.parse('0.2.0')

# version.hpp's path in config's repository.
HEADER_PATH = 'include/webcpp/version.hpp'

LIB_LINE = '#define WEBCPP_LIB_VERSION "0_1"\n'

# Each form a WEBCPP_VERSION line of version.hpp may take, and the version both readers, release.py
# and the Jamroot, take it for: None when both refuse it. They agree with C++ or refuse: C++ reads
# 0144 as octal, 100, and 100u, 0x64 and a tab before the value as 100, which no reader takes.
FORMS: list[tuple[str, str | None]] = [
    ('#define WEBCPP_VERSION 100\n', '0.1.0'),
    ('// NOLINTNEXTLINE(modernize-macro-to-enum)\n#define WEBCPP_VERSION 100\n', '0.1.0'),
    ('#define WEBCPP_VERSION 100\r\n', '0.1.0'),
    ('#define WEBCPP_VERSION  100\n', '0.1.0'),
    ('#define WEBCPP_VERSION 100  \n', '0.1.0'),
    ('#define WEBCPP_VERSION 100\t\n', '0.1.0'),
    ('#define WEBCPP_VERSION 0\n', '0.0.0'),
    ('#define WEBCPP_VERSION\t100\n', None),
    ('#define WEBCPP_VERSION 0x64\n', None),
    ('#define WEBCPP_VERSION 0144\n', None),
    ('#define WEBCPP_VERSION 00\n', None),
    ('#define WEBCPP_VERSION 100u\n', None),
    ('#define WEBCPP_VERSION 100  // 0.1.0\n', None),
    ('#define WEBCPP_VERSION \u0661\u0660\u0660\n', None),
    ('#define WEBCPP_VERSION 1\u00b2\n', None),
    ('#  define WEBCPP_VERSION 100\n', None),
    ('', None),
]

# A header that defines WEBCPP_VERSION twice, which both readers refuse, naming the macro.
TWICE = '#if A\n#define WEBCPP_VERSION 100\n#else\n#define WEBCPP_VERSION 200\n#endif\n'


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


def run_whats_new(root: Path, version: release.Version) -> list[str]:
    """release.whats_new, which prints the file it writes, run without printing it."""
    with contextlib.redirect_stdout(io.StringIO()):
        return release.whats_new(root, version)


def commit_bytes(tree: scratch.Tree, library: str | None, path: str, data: bytes) -> None:
    """Commits data at path of library, recorded by the superproject, or of the superproject for
    None: check judges what HEAD records, so a case commits what it plants."""
    directory = tree.root if library is None else tree.library(library)
    (directory / path).parent.mkdir(parents=True, exist_ok=True)
    (directory / path).write_bytes(data)
    scratch.git(directory, 'add', path)
    scratch.git(directory, 'commit', '-q', '--allow-empty', '-m', path)
    if library is not None:
        tree.record(library)


def test_versions_are_named(directory: Path) -> None:
    assert release.Version.of_number(100) == V010
    assert (V010.lib, V010.anchor, V010.tag) == ('0_1', '0-1-0', 'webcpp-0.1.0')
    other = release.Version.of_number(100203)
    assert (other.name, other.lib) == ('1.2.3', '1_2_3')
    assert release.Version.of_number(99999) == release.Version(0, 999, 99)
    assert release.Version.parse('0.10.0') > release.Version.parse('0.9.0')
    for name in ('0.1', '01.1.0', '0.01.0', '\u0661.0.0', '1.2.3 ', '1.2.3.4'):
        try:
            release.Version.parse(name)
        except release.Broken as broken:
            assert str(broken) == f'{name} is no version <major>.<minor>.<patch>', broken
        else:
            raise AssertionError(f'{name!r} parsed')


def test_version_forms(directory: Path) -> None:
    # release.py's half of FORMS; test_jamroot_reads_the_version is the Jamroot's.
    tree = scratch.make_tree(directory)
    header = tree.library('config') / 'include/webcpp/version.hpp'
    for form, name in FORMS:
        commit_bytes(tree, 'config', HEADER_PATH, (form + LIB_LINE).encode('utf-8'))
        status, output, error = run_main('check', '--root', str(tree.root), '--version', '0.1.0')
        if name is None:
            assert (status, output) == (2, ''), (form, status, output)
            assert error == (f'check: {release.HEADER} has no lines `#define WEBCPP_VERSION '
                             '<number>` and `#define WEBCPP_LIB_VERSION "<text>"`, the number in '
                             'decimal, without a leading zero\n'), (form, error)
        else:
            assert release.read_version(tree.root)[0] == release.Version.parse(name), form
    for text, macro in ((TWICE + LIB_LINE, 'WEBCPP_VERSION'),
                        ('#define WEBCPP_VERSION 100\n' + LIB_LINE + LIB_LINE,
                         'WEBCPP_LIB_VERSION')):
        commit_bytes(tree, 'config', HEADER_PATH, text.encode('utf-8'))
        assert run_main('check', '--root', str(tree.root), '--version', '0.1.0') == (
            2, '', f'check: {release.HEADER} defines {macro} twice\n'), text
    commit_bytes(tree, 'config', HEADER_PATH, ('#define WEBCPP_VERSION 100\n' + LIB_LINE).encode())
    # A header that cannot be read: the reader names it; check names it first as a file git
    # cannot find equal to HEAD's, since git reads it as changed.
    header.chmod(0)
    try:
        try:
            release.read_version(tree.root)
        except release.Broken as broken:
            assert str(broken).startswith(f'{release.HEADER} cannot be read: '), broken
        else:
            raise AssertionError('an unreadable header was read')
        found = run_main('check', '--root', str(tree.root), '--version', '0.1.0')
    finally:
        header.chmod(0o644)
    assert found == (1, f'check: {release.HEADER} is not committed: a tag carries only what HEAD '
                        'records\n', ''), found


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
                      f'{release.HEADER} names 0.1.0\n'
                      'check: doc/releases/0.2.0.adoc does not exist: open it from '
                      'tools/release/template.adoc\n'), output
    for text in ('#define WEBCPP_VERSION 100  // 0.1.0\n#define WEBCPP_LIB_VERSION "0_1"\n',
                 '#define WEBCPP_VERSION 100\n#define WEBCPP_LIB_VERSION 0_1\n',
                 '#define WEBCPP_VERSION 100\n'):
        commit_bytes(tree, 'config', HEADER_PATH, text.encode('utf-8'))
        assert run_main('check', '--root', root, '--version', '0.1.0') == (
            2, '', f'check: {release.HEADER} has no lines `#define WEBCPP_VERSION <number>` and '
                   '`#define WEBCPP_LIB_VERSION "<text>"`, the number in decimal, without a '
                   'leading zero\n'), text
    commit_bytes(tree, 'config', HEADER_PATH,
                 b'#define WEBCPP_VERSION 100\n#define WEBCPP_LIB_VERSION "\xff"\n')
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


def released(tree: scratch.Tree) -> None:
    """Tags 0.1.0, then opens 0.2.0 as the release procedure does: config's version moves, and
    the notes of 0.2.0 come first in the index."""
    scratch.git(tree.root, 'tag', 'webcpp-0.1.0')
    tree.change('config', 'include/webcpp/version.hpp',
                scratch.VERSION_HPP.format(number=200, lib='0_2'))
    tree.commit_file('doc/releases/0.2.0.adoc', scratch.notes_text('0.2.0'))
    tree.commit_file('doc/index.adoc', scratch.index_text(('0.2.0', '0.1.0')))


def test_first_release_lists_every_library_as_new(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    assert release.check(tree.root, V010) == []
    tree.commit_file('doc/releases/0.1.0.adoc',
                     scratch.notes_text('0.1.0', new=('alpha', 'config')))
    expect(release.check(tree.root, V010),
           'New Libraries lists alpha, config, and the libraries new since the first version are '
           'alpha, beta, config')


def test_changed_library_needs_a_line_and_a_listing(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    released(tree)
    assert release.check(tree.root, V020) == []
    tree.change('alpha', 'include/webcpp/alpha.hpp', '// alpha, changed\n')
    expect(release.check(tree.root, V020),
           'libs/alpha changed since webcpp-0.1.0 and its Unreleased has no line')
    tree.change('alpha', 'doc/changelog.adoc',
                scratch.changelog_text('alpha', unreleased=('* Changed alpha.',)))
    expect(release.check(tree.root, V020),
           'the release notes miss alpha, whose changelog has lines for this version')
    tree.commit_file('doc/releases/0.2.0.adoc',
                     scratch.notes_text('0.2.0', updated=(('alpha', 'unreleased'),)))
    assert release.check(tree.root, V020) == []


def test_a_change_no_user_sees_needs_no_line(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    released(tree)
    tree.change('alpha', 'test/alpha_test.cpp', 'int main() { return 0; }\n')
    tree.change('alpha', 'AGENTS.md', '# alpha, for agents\n')
    assert release.check(tree.root, V020) == []
    # A changelog's own change, such as a line of a released version reworded, is no change.
    tree.change('alpha', 'doc/changelog.adoc', scratch.changelog_text(
        'alpha', released=(('0.1.0', ('* Added alpha, reworded.',)),)))
    assert release.check(tree.root, V020) == []
    tree.change('alpha', 'LICENSE_1_0.txt', 'Boost Software License, again\n')
    expect(release.check(tree.root, V020), 'libs/alpha changed since webcpp-0.1.0')


def test_a_listed_library_without_a_line_fails(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    released(tree)
    tree.commit_file('doc/releases/0.2.0.adoc',
                     scratch.notes_text('0.2.0', updated=(('beta', 'unreleased'),)))
    expect(release.check(tree.root, V020),
           'beta is under Updated Libraries, and its region unreleased holds no line')


def test_added_and_removed_libraries(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    released(tree)
    tree.add_library('gamma')
    expect(release.check(tree.root, V020),
           'New Libraries lists none, and the libraries new since webcpp-0.1.0 are gamma')
    scratch.git(tree.root, 'rm', '-q', '--cached', 'libs/beta')
    shutil.rmtree(tree.library('beta'))
    scratch.git(tree.root, 'commit', '-q', '-m', 'libs/beta: removed')
    tree.commit_file('doc/releases/0.2.0.adoc',
                     scratch.notes_text('0.2.0', new=('gamma',), removed=('beta',)))
    assert release.check(tree.root, V020) == []
    tree.commit_file('doc/releases/0.2.0.adoc', scratch.notes_text(
        '0.2.0', new=('gamma',), updated=(('beta', 'unreleased'),), removed=('beta',)))
    expect(release.check(tree.root, V020),
           'beta is under Updated Libraries, and is removed since webcpp-0.1.0')


def test_a_missing_commit_and_a_stale_pointer(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    released(tree)
    alpha = tree.library('alpha')
    scratch.git(alpha, 'checkout', '-q', '--orphan', 'rewritten')
    scratch.git(alpha, 'commit', '-q', '-m', 'alpha: rewritten')
    scratch.git(alpha, 'branch', '-q', '-D', 'main')
    scratch.git(alpha, 'reflog', 'expire', '--expire=now', '--all')
    scratch.git(alpha, 'gc', '-q', '--prune=now')
    tree.record('alpha')
    expect(release.check(tree.root, V020), 'is not in its repository; fetch its tags')
    scratch.git(tree.library('beta'), 'commit', '-q', '--allow-empty', '-m', 'beta: unrecorded')
    expect(release.check(tree.root, V020), 'libs/beta is at ', ', and the superproject records ')


def test_a_library_not_checked_out_is_named(directory: Path) -> None:
    # A clone whose submodule is not checked out holds its directory empty: the library is not
    # removed, and the check says what is missing rather than ask for a line of Removed Libraries.
    tree = scratch.make_tree(directory)
    released(tree)
    shutil.rmtree(tree.library('beta'))
    tree.library('beta').mkdir()
    found = release.check(tree.root, V020)
    expect(found, 'libs/beta is a submodule of the superproject at HEAD, and is not checked out: '
           'git submodule update --init libs/beta')
    assert not any('Removed Libraries' in finding for finding in found), found


def test_the_previous_tag_is_the_newest_before_the_version(directory: Path) -> None:
    # Three versions: 0.2.0 adds gamma and changes alpha, and is tagged; 0.3.0 compares with
    # webcpp-0.2.0, never with webcpp-0.1.0, and 0.2.0 checked again still with webcpp-0.1.0.
    lanes = tuple(lane.name for lane in matrix.LANES)
    tree = scratch.make_tree(directory)
    released(tree)
    tree.add_library('gamma')
    tree.change('alpha', 'include/webcpp/alpha.hpp', '// alpha, changed\n')
    tree.change('alpha', 'doc/changelog.adoc', scratch.changelog_text(
        'alpha', released=(('0.2.0', ('* Changed alpha.',)),)))
    tree.commit_file('doc/releases/0.2.0.adoc', scratch.notes_text(
        '0.2.0', preparing=False, new=('gamma',), updated=(('alpha', '0.2.0'),),
        compilers=lanes))
    scratch.git(tree.root, 'tag', 'webcpp-0.2.0')
    assert release.check(tree.root, V020) == []
    tree.change('config', 'include/webcpp/version.hpp',
                scratch.VERSION_HPP.format(number=300, lib='0_3'))
    tree.commit_file('doc/releases/0.3.0.adoc', scratch.notes_text('0.3.0'))
    tree.commit_file('doc/index.adoc', scratch.index_text(('0.3.0', '0.2.0', '0.1.0')))
    assert release.check(tree.root, release.Version.parse('0.3.0')) == []


def test_unreadable_files_are_named(directory: Path) -> None:
    # The notes, a changelog and the index, each with a byte that is not UTF-8: check stops,
    # naming the file, as it does for version.hpp, and never with a traceback.
    for library, path, relative in ((None, 'doc/releases/0.1.0.adoc', 'doc/releases/0.1.0.adoc'),
                                    ('alpha', 'doc/changelog.adoc',
                                     'libs/alpha/doc/changelog.adoc'),
                                    (None, 'doc/index.adoc', 'doc/index.adoc')):
        (directory / relative.replace('/', '-')).mkdir()
        tree = scratch.make_tree(directory / relative.replace('/', '-'))
        commit_bytes(tree, library, path, b'\xff\n')
        status, output, error = run_main('check', '--root', str(tree.root), '--version', '0.1.0')
        assert (status, output) == (2, ''), (relative, status, output)
        assert error.startswith(f'check: {relative} cannot be read: '), (relative, error)


def test_uncommitted_changes_are_refused_first(directory: Path) -> None:
    # check judges what the tag would carry, so a change that HEAD does not record, in the
    # superproject or in a library, is named before anything else; ignored build output is not.
    tree = scratch.make_tree(directory)
    released(tree)
    tree.change('alpha', 'include/webcpp/alpha.hpp', '// alpha, changed\n')
    tree.commit_file('doc/releases/0.2.0.adoc',
                     scratch.notes_text('0.2.0', updated=(('alpha', 'unreleased'),)))
    log = tree.library('alpha') / 'doc/changelog.adoc'
    scratch.write(log, scratch.changelog_text('alpha', unreleased=('* Changed alpha.',)))
    assert release.check(tree.root, V020) == [
        'libs/alpha/doc/changelog.adoc is not committed: a tag carries only what HEAD records']
    scratch.git(tree.library('alpha'), 'add', 'doc/changelog.adoc')
    expect(release.check(tree.root, V020), 'libs/alpha/doc/changelog.adoc is not committed')
    scratch.git(tree.library('alpha'), 'commit', '-q', '-m', 'alpha: its line')
    tree.record('alpha')
    assert release.check(tree.root, V020) == []
    scratch.write(tree.root / 'doc/releases/0.3.0.adoc', scratch.notes_text('0.3.0'))
    scratch.write(tree.root / 'doc/index.adoc', 'Changed.\n')
    assert release.check(tree.root, V020) == [
        f'{path} is not committed: a tag carries only what HEAD records'
        for path in ('doc/index.adoc', 'doc/releases/0.3.0.adoc')]
    scratch.git(tree.root, 'checkout', '-q', '--', 'doc/index.adoc')
    (tree.root / 'doc/releases/0.3.0.adoc').unlink()
    # A rename staged is named once, by the path it has now.
    scratch.git(tree.library('beta'), 'mv', 'AGENTS.md', 'AGENTS.txt')
    assert release.check(tree.root, V020) == [
        'libs/beta/AGENTS.txt is not committed: a tag carries only what HEAD records']
    scratch.git(tree.library('beta'), 'mv', 'AGENTS.txt', 'AGENTS.md')
    for ignored in (tree.root / 'bin/x.o', tree.root / 'doc/html/more.html',
                    tree.library('beta') / 'doc/html/more.html'):
        scratch.write(ignored, 'built\n')
    assert release.check(tree.root, V020) == []


def test_a_library_without_its_own_git_is_named(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    released(tree)
    shutil.rmtree(tree.library('alpha') / '.git')
    found = release.check(tree.root, V020)
    assert found == ['libs/alpha is no git checkout of its own: a library is a repository, '
                     'recorded by the superproject'], found


def test_names_that_are_no_version_are_named(directory: Path) -> None:
    # A tag webcpp-<x> whose x is no version is no release, and a notes file whose name is no
    # version is named; neither stops the check.
    tree = scratch.make_tree(directory)
    released(tree)
    scratch.git(tree.root, 'tag', 'webcpp-0.01.0')
    scratch.git(tree.root, 'tag', 'webcpp-0.2')
    assert release.check(tree.root, V020) == []
    tree.commit_file('doc/releases/0.01.0.adoc', scratch.notes_text('0.1.0'))
    expect(release.check(tree.root, V020),
           "doc/releases/0.01.0.adoc is no version's notes, <a.b.c>.adoc")


def test_an_updated_name_that_is_no_library(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    released(tree)
    tree.commit_file('doc/releases/0.2.0.adoc',
                     scratch.notes_text('0.2.0', updated=(('alhpa', 'unreleased'),)))
    assert release.check(tree.root, V020) == [
        'doc/releases/0.2.0.adoc: alhpa is under Updated Libraries, and is no library of libs/'
    ], release.check(tree.root, V020)


def test_lines_out_of_form_are_named(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    tree.change('alpha', 'doc/changelog.adoc',
                scratch.changelog_text('alpha', unreleased=('* Made a mistake.',)))
    tree.commit_file('doc/releases/0.1.0.adoc', scratch.notes_text(
        '0.1.0', new=('alpha', 'beta', 'config'), tools=('* Built a thing.',)))
    expect(release.check(tree.root, V010), 'libs/alpha/doc/changelog.adoc:',
           'doc/releases/0.1.0.adoc:')


def test_compilers_tested_are_the_ci_lanes(directory: Path) -> None:
    lanes = tuple(lane.name for lane in matrix.LANES)
    tree = scratch.make_tree(directory)
    tree.commit_file('doc/releases/0.1.0.adoc', scratch.notes_text(
        '0.1.0', new=('alpha', 'beta', 'config'), compilers=lanes))
    assert release.check(tree.root, V010) == []
    tree.commit_file('doc/releases/0.1.0.adoc', scratch.notes_text(
        '0.1.0', new=('alpha', 'beta', 'config'), compilers=lanes[1:]))
    expect(release.check(tree.root, V010), 'Compilers tested lists')
    # The notes write a lane as changelog.notes_lane does, and the check compares through it: the
    # CI's own spelling, libstdc++, is no lane of the notes, which doc-check refuses in prose.
    tree.commit_file('doc/releases/0.1.0.adoc', scratch.notes_text(
        '0.1.0', new=('alpha', 'beta', 'config'), compilers=lanes).replace('{plus}', '+'))
    expect(release.check(tree.root, V010), 'Compilers tested lists GCC 14 (container, no '
           'network), GCC 15, Clang 18 (libstdc++, container, no network), ', "and the CI's "
           'lanes are GCC 14 (container, no network), GCC 15, Clang 18 (libstdc{plus}{plus}, '
           'container, no network), ')


def frozen(tree: scratch.Tree, lanes: tuple[str, ...]) -> None:
    """Freezes 0.2.0 as the release procedure does: alpha's Unreleased becomes webcpp 0.2.0 under
    a new, empty Unreleased, and the notes include tag=0.2.0, without their paragraph."""
    tree.change('alpha', 'doc/changelog.adoc', scratch.changelog_text(
        'alpha', released=(('0.2.0', ('* Changed alpha.',)),)))
    tree.commit_file('doc/releases/0.2.0.adoc', scratch.notes_text(
        '0.2.0', preparing=False, updated=(('alpha', '0.2.0'),), compilers=lanes))


def test_frozen_state(directory: Path) -> None:
    lanes = tuple(lane.name for lane in matrix.LANES)
    tree = scratch.make_tree(directory)
    released(tree)
    tree.change('alpha', 'include/webcpp/alpha.hpp', '// alpha, changed\n')
    frozen(tree, lanes)
    assert release.check(tree.root, V020) == []
    tree.commit_file('doc/releases/0.2.0.adoc', scratch.notes_text(
        '0.2.0', updated=(('alpha', '0.2.0'),), compilers=lanes))
    expect(release.check(tree.root, V020),
           'alpha is included with tag=0.2.0, and the version is in preparation: '
           'tag=unreleased', 'libs/alpha/doc/changelog.adoc has webcpp 0.2.0')
    frozen(tree, lanes)
    tree.change('alpha', 'doc/changelog.adoc', scratch.changelog_text(
        'alpha', unreleased=('* Fixed alpha.',), released=(('0.2.0', ('* Changed alpha.',)),)))
    expect(release.check(tree.root, V020),
           'libs/alpha/doc/changelog.adoc: Unreleased holds lines, and webcpp 0.2.0 is frozen')
    frozen(tree, lanes)
    scratch.git(tree.root, 'tag', 'webcpp-0.2.0', 'HEAD~1')
    expect(release.check(tree.root, V020), 'the tag webcpp-0.2.0 is at ')
    scratch.git(tree.root, 'tag', '-f', 'webcpp-0.2.0', 'HEAD')
    assert release.check(tree.root, V020) == []


def test_index_includes_every_version_newest_first(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    released(tree)
    tree.commit_file('doc/index.adoc', scratch.index_text(('0.1.0', '0.2.0')))
    expect(release.check(tree.root, V020),
           'doc/index.adoc: section Releases includes 0.1.0, 0.2.0, and it includes the notes of '
           'doc/releases newest first: 0.2.0, 0.1.0')
    tree.commit_file('doc/index.adoc', scratch.index_text(('0.1.0',)))
    expect(release.check(tree.root, V020), 'section Releases includes 0.1.0, and')


def test_template_opens_a_version_that_checks(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    released(tree)
    template = (Path(release.__file__).parent / 'template.adoc').read_text(encoding='utf-8')
    tree.commit_file('doc/releases/0.2.0.adoc',
                     template.replace('@VERSION@', '0.2.0').replace('@ANCHOR@', '0-2-0'))
    assert release.check(tree.root, V020) == []


def test_the_tree_s_notes_name_the_ci_lanes(directory: Path) -> None:
    # This checkout's newest notes, read and never checked against its tags: the lanes they list,
    # when they list any, are the CI's, as the notes write them.
    files = sorted((release.Version.parse(path.stem), path)
                   for path in (harness.ROOT / 'doc/releases').glob('*.adoc'))
    assert files, 'doc/releases holds no notes'
    version, path = files[-1]
    notes, faults = changelog.parse_notes(path.read_text(encoding='utf-8'), version.name)
    assert faults == [], faults
    if notes.compilers is not None:
        assert notes.compilers == [changelog.notes_lane(lane.name) for lane in matrix.LANES], (
            notes.compilers)


def test_whats_new_skeleton(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    tree.commit_file('doc/releases/0.1.0.adoc', scratch.notes_text(
        '0.1.0', new=('alpha', 'beta', 'config'),
        tools=('* Added `b2 dist`, which packages a release, for {cpp}20.',)))
    assert run_whats_new(tree.root, V010) == []
    written = tree.root / 'doc/releases/0.1.0.whats-new.md'
    text = written.read_text(encoding='utf-8')
    assert text.startswith('# webcpp 0.1.0\n\nwebcpp 0.1.0 is out.\n\n## New libraries\n'), text
    assert '- **alpha**: alpha, a library, from R.\n' in text, text
    assert '- Added `b2 dist`, which packages a release, for C++20.\n' in text, text
    assert '<!-- At most five highlights' in text and '{' not in text and 'link:' not in text
    assert 'https://webcpporg.github.io/webcpp/#webcpp-0-1-0' in text
    try:
        run_whats_new(tree.root, V010)
    except release.Failure as failure:
        assert 'doc/releases/0.1.0.whats-new.md exists, and is never written over' in str(failure)
    else:
        raise AssertionError('whats-new wrote over a What\'s new')
    assert written.read_text(encoding='utf-8') == text


def test_whats_new_lists_updated_libraries(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    released(tree)
    tree.change('alpha', 'doc/changelog.adoc', scratch.changelog_text('alpha', unreleased=(
        '* *Breaking change:* removed `x`; use `y`.',
        '* Fixed a crash (https://github.com/webcpporg/alpha/issues/3[#3]).',
        '* Added `z`.', '* Updated the page.')))
    tree.commit_file('doc/releases/0.2.0.adoc',
                     scratch.notes_text('0.2.0', updated=(('alpha', 'unreleased'),)))
    run_whats_new(tree.root, V020)
    text = (tree.root / 'doc/releases/0.2.0.whats-new.md').read_text(encoding='utf-8')
    assert ('- **alpha**: **Breaking change:** removed `x`; use `y`. Fixed a crash '
            '([#3](https://github.com/webcpporg/alpha/issues/3)). Added `z`.\n') in text, text
    assert 'Updated the page' not in text


def test_whats_new_highlights_are_checked(directory: Path) -> None:
    # check names an uncommitted path first, alone (uncommitted_findings): a written
    # What's new is committed here before each check, as the release procedure commits it once
    # its highlights are filled.
    tree = scratch.make_tree(directory)
    run_whats_new(tree.root, V010)
    written = tree.root / 'doc/releases/0.1.0.whats-new.md'
    skeleton = written.read_text(encoding='utf-8')
    tree.commit_file('doc/releases/0.1.0.whats-new.md', skeleton)
    assert release.check(tree.root, V010) == []

    def highlights(*lines: str) -> None:
        tree.commit_file('doc/releases/0.1.0.whats-new.md',
                         re.sub(r'<!--.*?-->', '\n'.join(lines), skeleton, flags=re.DOTALL))

    highlights('- **New libraries**: five header-only libraries arrive.',
               '- **Developer experience**: every changelog line is checked.')
    assert release.check(tree.root, V010) == []
    highlights(*(['- **Dependencies**: one.'] * 6))
    expect(release.check(tree.root, V010), '6 highlights, and there are at most 5')
    highlights('- **Dependencies**: ' + ' '.join(['word'] * 21) + '.')
    expect(release.check(tree.root, V010), 'the highlight Dependencies has more than 20 words')
    highlights('- **Speed**: faster.')
    expect(release.check(tree.root, V010),
           'is not a highlight: its category is not one of New libraries')
    highlights('- **Dependencies**: one.', '- **New libraries**: two.')
    expect(release.check(tree.root, V010), 'the highlights come in the order')
    # A duplicated category, with no reordering and no smuggling, is "each once"'s own case.
    highlights('- **Dependencies**: one.', '- **Dependencies**: two.')
    expect(release.check(tree.root, V010), 'the highlights come in the order')
    # The grammar (fix round 3) counts a highlight by its own line, one at most per line: a
    # second "- **...**: " packed after a real highlight's text is just more of its sentence,
    # the way a reader's rendered Markdown would show it (one bullet, two bold spans), never a
    # highlight of its own - which is also why packing extra markers onto one line can never
    # inflate the count past five: four lines make at most four highlights, however many
    # markers are packed onto any one of them.
    highlights('- **New libraries**: five. - **Dependencies**: one.')
    assert release.check(tree.root, V010) == []
    highlights('- **Dependencies**: one. - **Dependencies**: two. - **Dependencies**: three.',
               '- **Dependencies**: four.', '- **Dependencies**: five.',
               '- **Dependencies**: six.')
    found = release.check(tree.root, V010)
    expect(found, 'the highlights come in the order')
    assert not any('there are at most 5' in finding for finding in found), found
    highlights('- **New libraries**: one. - **New libraries**: two.')
    assert release.check(tree.root, V010) == []


def test_whats_new_names_unreadable_files(directory: Path) -> None:
    # A missing, unreadable or non-UTF-8 file whats-new reads is a named Failure or Broken,
    # never a traceback: the version's own release notes, an updated library's changelog, and,
    # through whats_new_findings read directly (an uncommitted whats-new.md would be named by
    # check's own uncommitted_findings before whats_new_findings ever runs), the What's new
    # itself.
    tree = scratch.make_tree(directory)
    (tree.root / 'doc/releases/0.1.0.adoc').unlink()
    try:
        run_whats_new(tree.root, V010)
    except release.Failure as failure:
        assert str(failure) == ('doc/releases/0.1.0.adoc does not exist: open it from '
                                'tools/release/template.adoc'), failure
    else:
        raise AssertionError('whats-new read release notes that do not exist')
    (tree.root / 'doc/releases/0.1.0.adoc').write_bytes(b'\xff\n')
    try:
        run_whats_new(tree.root, V010)
    except release.Broken as broken:
        assert str(broken).startswith('doc/releases/0.1.0.adoc cannot be read: '), broken
    else:
        raise AssertionError('whats-new read release notes that are not UTF-8')
    tree.commit_file('doc/releases/0.1.0.adoc',
                     scratch.notes_text('0.1.0', new=('alpha', 'beta', 'config')))
    released(tree)
    tree.commit_file('doc/releases/0.2.0.adoc',
                     scratch.notes_text('0.2.0', updated=(('alpha', 'unreleased'),)))
    log = tree.library('alpha') / 'doc/changelog.adoc'
    log.unlink()
    try:
        run_whats_new(tree.root, V020)
    except release.Broken as broken:
        assert str(broken).startswith('libs/alpha/doc/changelog.adoc cannot be read: '), broken
    else:
        raise AssertionError('whats-new read a changelog that does not exist')
    log.write_bytes(b'\xff\n')
    try:
        run_whats_new(tree.root, V020)
    except release.Broken as broken:
        assert str(broken).startswith('libs/alpha/doc/changelog.adoc cannot be read: '), broken
    else:
        raise AssertionError('whats-new read a changelog that is not UTF-8')
    written = tree.root / 'doc/releases/0.2.0.whats-new.md'
    written.write_bytes(b'\xff\n')
    try:
        release.whats_new_findings(tree.root, V020)
    except release.Broken as broken:
        assert str(broken).startswith('doc/releases/0.2.0.whats-new.md cannot be read: '), broken
    else:
        raise AssertionError("whats_new_findings read a What's new that is not UTF-8")


def test_whats_new_highlight_markers_must_start_a_line(directory: Path) -> None:
    # A highlight is exactly a line of the form "- **<Category>**: <text>" (HIGHLIGHT, fix
    # round 3's whitelist grammar): a marker wrapped in a code span or a link's text never
    # starts its own line this way, so the whole line is refused, "not a highlight", as a
    # reader's rendered Markdown would never read it as one either (a code span or a link
    # caption, not a bold bullet).
    tree = scratch.make_tree(directory)
    run_whats_new(tree.root, V010)
    written = tree.root / 'doc/releases/0.1.0.whats-new.md'
    skeleton = written.read_text(encoding='utf-8')

    def highlights(body: str) -> None:
        tree.commit_file('doc/releases/0.1.0.whats-new.md',
                         re.sub(r'<!--.*?-->', body, skeleton, flags=re.DOTALL))

    # A marker inside a code span is never a real highlight.
    highlights('- **New libraries**: one.\n\n'
              '`- **Developer experience**: fake extra credit.`')
    found = release.check(tree.root, V010)
    expect(found, 'is not a highlight')
    assert not any('come in the order' in finding for finding in found), found
    # Nor is one inside a link's text.
    highlights('- **New libraries**: one.\n\n'
              '[- **Developer experience**: fake extra credit.](https://example.com/x)')
    found = release.check(tree.root, V010)
    expect(found, 'is not a highlight')
    assert not any('come in the order' in finding for finding in found), found
    # A marker indented by even one space does not start the line either.
    highlights(' - **New libraries**: one.')
    expect(release.check(tree.root, V010), 'is not a highlight: an indented marker')
    # A marker at the very end of the section, its sentence empty, is still read, named there.
    highlights('- **New libraries**: one.\n- **Dependencies**: ')
    expect(release.check(tree.root, V010), 'is not a highlight')
    # CRLF line endings: read_text's universal-newline translation normalizes them before any
    # regex runs, so a clean body still checks clean, and an indented one is still refused.
    clean_crlf = ('- **New libraries**: five header-only libraries arrive.\r\n'
                 '- **Developer experience**: every changelog line is checked.\r\n')
    commit_bytes(tree, None, 'doc/releases/0.1.0.whats-new.md',
                re.sub(r'<!--.*?-->', clean_crlf, skeleton, flags=re.DOTALL)
                .replace('\n', '\r\n').encode('utf-8'))
    assert release.check(tree.root, V010) == []
    indented_crlf = ' - **New libraries**: one.\r\n'
    commit_bytes(tree, None, 'doc/releases/0.1.0.whats-new.md',
                re.sub(r'<!--.*?-->', indented_crlf, skeleton, flags=re.DOTALL)
                .replace('\n', '\r\n').encode('utf-8'))
    expect(release.check(tree.root, V010), 'is not a highlight: an indented marker')


def test_whats_new_leading_text_is_named_by_its_own_line(directory: Path) -> None:
    # The "text before the first highlight" finding cites the line where the stray text
    # itself begins, not the Highlights section's own first line (or any line of its
    # placeholder comment).
    tree = scratch.make_tree(directory)
    run_whats_new(tree.root, V010)
    written = tree.root / 'doc/releases/0.1.0.whats-new.md'
    text = written.read_text(encoding='utf-8')
    marker = 'the owner approves them before the tag. -->\n\n'
    stray = 'Summary of this release:\n\n- **New libraries**: config lands.\n\n'
    assert marker in text, text
    new_text = text.replace(marker, marker + stray)
    tree.commit_file('doc/releases/0.1.0.whats-new.md', new_text)
    stray_line = next(number for number, line in enumerate(new_text.split('\n'), 1)
                      if line.strip() == 'Summary of this release:')
    found = release.check(tree.root, V010)
    expect(found, f'doc/releases/0.1.0.whats-new.md:{stray_line}: line {stray_line} is not '
           'a highlight')
    assert not any(f':{stray_line - 1}:' in finding or f':{stray_line - 2}:' in finding
                  for finding in found), found


def test_whats_new_highlights_grammar_is_a_whitelist(directory: Path) -> None:
    # Fix round 3: chasing one marker-shaped bypass after another never converges, so the
    # section Highlights is read as a whitelist grammar instead - every non-blank line is a
    # highlight, a continuation, or refused, naming the file and the line - rather than by
    # hunting for the marker pattern wherever it might appear.
    tree = scratch.make_tree(directory)
    run_whats_new(tree.root, V010)
    written = tree.root / 'doc/releases/0.1.0.whats-new.md'
    skeleton = written.read_text(encoding='utf-8')

    def highlights(body: str) -> None:
        tree.commit_file('doc/releases/0.1.0.whats-new.md',
                         re.sub(r'<!--.*?-->', body, skeleton, flags=re.DOTALL))

    # A fenced code block is test_whats_new_a_fence_refuses_the_rest_of_highlights' own case.
    # A marker whose colon is followed by a tab, not a space, is refused outright - it used to
    # be silently merged into the previous highlight's sentence.
    highlights('- **Dependencies**: real one.\n\n'
              '- **New libraries**:\tfake marker using a tab.')
    found = release.check(tree.root, V010)
    expect(found, 'is not a highlight: a tab')
    assert not any('come in the order' in finding for finding in found), found
    # A tab anywhere in a line's own indentation is refused the same way.
    highlights('\t- **New libraries**: tabbed indent.')
    expect(release.check(tree.root, V010), 'is not a highlight: a tab')
    # A marker whose category holds a literal "*" matches no shape at all - also refused,
    # where it used to be silently merged too.
    highlights('- **Dependencies**: real one.\n\n'
              '- **New*libraries**: fake marker, category has a star.')
    found = release.check(tree.root, V010)
    expect(found, 'is not a highlight')
    assert not any('come in the order' in finding for finding in found), found
    # A second ## Highlights heading is named by its own line, not silently hidden along with
    # everything after it (over five, packed, duplicated, all at once, had it been read).
    text = written.read_text(encoding='utf-8')
    start = text.index('## Highlights')
    end = text.index('Release notes:')
    new_text = (text[:start] + '## Highlights\n\n- **New libraries**: one.\n\n## Highlights\n\n'
               '- **Dependencies**: two. - **Dependencies**: three. - **Dependencies**: four. '
               '- **Dependencies**: five. - **Dependencies**: six. - **Dependencies**: seven.'
               '\n\n' + text[end:])
    tree.commit_file('doc/releases/0.1.0.whats-new.md', new_text)
    expect(release.check(tree.root, V010), 'a second ## Highlights heading')
    # A continuation (exactly two spaces, non-space text) with no highlight before it is
    # refused, not silently dropped; one right after a highlight extends its sentence.
    highlights('  orphan continuation.')
    expect(release.check(tree.root, V010), 'a continuation with no highlight before it')
    highlights('- **New libraries**: one.\n  continued here.')
    assert release.check(tree.root, V010) == []
    # A BOM at the very start of the file is harmless: section and line detection are
    # unaffected.
    clean = '- **New libraries**: five header-only libraries arrive.'
    bom_text = '﻿' + re.sub(r'<!--.*?-->', clean, skeleton, flags=re.DOTALL)
    tree.commit_file('doc/releases/0.1.0.whats-new.md', bom_text)
    assert release.check(tree.root, V010) == []
    # A category outside ASCII is still read and still named invalid, in full.
    highlights('- **Café**: a category outside ASCII.')
    expect(release.check(tree.root, V010), 'its category is not one of New libraries')


WHATS_NEW = 'doc/releases/0.1.0.whats-new.md'


class Highlights:
    """A scratch tree preparing 0.1.0 with its What's new written by whats-new, whose section
    Highlights a case rewrites, commits and checks, naming each finding exactly by its line."""

    def __init__(self, directory: Path) -> None:
        self.tree = scratch.make_tree(directory)
        run_whats_new(self.tree.root, V010)
        self.skeleton = (self.tree.root / WHATS_NEW).read_text(encoding='utf-8')
        # The line of the placeholder comment, which a body replaces: its first line's number.
        self.first = self.skeleton[:self.skeleton.index('<!--')].count('\n') + 1

    def text(self, *lines: str) -> str:
        """The skeleton with lines in place of the placeholder comment."""
        return re.sub(r'<!--.*?-->', lambda _: '\n'.join(lines), self.skeleton, count=1,
                      flags=re.DOTALL)

    def check(self, text: str) -> list[str]:
        """check's findings once text is the What's new, committed byte for byte."""
        commit_bytes(self.tree, None, WHATS_NEW, text.encode('utf-8'))
        return release.check(self.tree.root, V010)

    def at(self, index: int, fault: str = '') -> str:
        """The finding that line index of a body is not a highlight, for fault, if any."""
        number = self.first + index
        return f'{WHATS_NEW}:{number}: line {number} is not a highlight' + (
            f': {fault}' if fault else '')

    def block(self, index: int) -> str:
        """The finding that line index of a body is a continuation starting a Markdown block."""
        number = self.first + index
        return f'{WHATS_NEW}:{number}: line {number}: a continuation may not start a Markdown block'

    def html(self, index: int) -> str:
        """The finding that line index of a body holds HTML."""
        return html(self.first + index)

    def opens(self, index: int) -> str:
        number = self.first + index
        return (f'{WHATS_NEW}:{number}: line {number} opens a fenced code block in Highlights, '
                "which refuses every line to the section's end")

    def inside(self, index: int, opener: int) -> str:
        """The finding that line index of a body is inside the fence line opener of the file
        opens: opener is a line of the file, not of the body."""
        number = self.first + index
        return (f'{WHATS_NEW}:{number}: line {number} is inside the fenced code block of line '
                f'{opener}')


def html(number: int) -> str:
    """The finding that line number of the What's new holds HTML."""
    return f"{WHATS_NEW}:{number}: line {number} holds HTML, which a What's new may not"


ORDER = f'{WHATS_NEW}: the highlights come in the order {", ".join(release.CATEGORIES)}, each once'
CATEGORY = f'its category is not one of {", ".join(release.CATEGORIES)}'


def test_whats_new_a_fence_refuses_the_rest_of_highlights(directory: Path) -> None:
    # Fix round 4: a line that opens a fence by CommonMark's rule (at most three spaces, then
    # three backticks or three tildes, then anything) refuses every line from it to the end of
    # the section, each named by its own line, whether or not the fence is ever closed: nothing
    # inside a fence ever counts as a highlight, so no count, order or category finding comes
    # from its lines either.
    case = Highlights(directory)
    real, fake = '- **New libraries**: real one.', '- **Dependencies**: fake, inside a fence.'
    after = '- **Developer experience**: real two, refused all the same.'
    opener = case.first + 2
    for fence, closer in (('```', '```'), ('~~~', '~~~'), ('```python', '```'),
                          ('~~~ text', '~~~'), (' ```', ' ```'), ('  ~~~', '  ~~~'),
                          ('   ```c++', '   ```'), ('````', '````'), ('```\tpython', '```')):
        found = case.check(case.text(real, '', fence, fake, closer, '', after))
        assert found == [case.opens(2), case.inside(3, opener), case.inside(4, opener),
                         case.inside(6, opener)], (fence, found)
    # An opener in a continuation's place, two spaces after a highlight, is a fence first.
    found = case.check(case.text(real, '  ```', '  ' + fake, '  ```', after))
    assert found == [case.opens(1), case.inside(2, case.first + 1),
                     case.inside(3, case.first + 1), case.inside(4, case.first + 1)], found
    # A fence never closed refuses the rest just the same; its blank lines are not named.
    found = case.check(case.text(real, '```', fake, '', '', after))
    assert found == [case.opens(1), case.inside(2, case.first + 1),
                     case.inside(5, case.first + 1)], found
    # A comment around a fence hides neither the fence nor a line inside it, and each line of
    # the comment holds HTML, which no What's new may (fix round 5).
    found = case.check(case.text(real + ' <!--', '```', fake, '-->', '<!-- a comment -->'))
    assert found == [case.html(0), case.html(3), case.html(4), case.opens(1),
                     case.inside(2, case.first + 1), case.inside(3, case.first + 1),
                     case.inside(4, case.first + 1)], found
    # A fence opened above the section, in the New libraries, refuses every line of it: the
    # section could sit inside that fence, closed or not.
    library = '- **config**: config, a library, from R.\n'
    above = case.text(real, after).replace(library, library + '\n```\nan example\n```\n')
    fenced = above.split('\n').index('```') + 1
    first = above.split('\n').index(real) + 1
    found = case.check(above)
    assert found == [
        f'{WHATS_NEW}:{fenced}: line {fenced} opens a fenced code block above ## Highlights, '
        'which refuses every line of the section',
        f'{WHATS_NEW}:{first}: line {first} is inside the fenced code block of line {fenced}',
        f'{WHATS_NEW}:{first + 1}: line {first + 1} is inside the fenced code block of line '
        f'{fenced}'], found
    # Not a fence: four spaces of indentation, a tab's, two backticks or two tildes. Each such
    # line is refused on its own, and the highlights after it are still read: the second
    # highlight here is counted, out of order.
    for line, fault in (('    ```', ''), ('\t```', 'a tab'), ('``', ''), ('~~', ''),
                        ('    - **Dependencies**: indented.', 'an indented marker')):
        found = case.check(case.text('- **Developer experience**: one.', line,
                                     '- **New libraries**: two.'))
        assert found == [case.at(1, fault), ORDER], (line, found)
    # Backticks in a highlight's own sentence open nothing: only a line's start does.
    assert case.check(case.text('- **Developer experience**: a fence is ```, then ~~~.')) == []


def test_whats_new_every_adversarial_input(directory: Path) -> None:
    # Every adversarial input the Highlights grammar was tried against, each named by its exact
    # findings, which check finds on a committed tree: the ones that once defeated it, and the
    # ones found correct, so that none of them is reopened.
    case = Highlights(directory)
    real = '- **New libraries**: real one.'
    clean = ('- **New libraries**: five header-only libraries arrive.',
             '- **Developer experience**: every changelog line is checked.')
    heading = '## Highlights\n'
    start, end = case.skeleton.index(heading), case.skeleton.index('Release notes:')
    second = heading + '\n' + real + '\n\n' + heading
    second_line = case.skeleton[:start].count('\n') + 5
    dependencies = ' '.join(f'- **Dependencies**: {word}.' for word in
                            ('two', 'three', 'four', 'five', 'six', 'seven'))
    unwrapped = release.HIGHLIGHTS.removeprefix('<!-- ').removesuffix(' -->').split('\n')
    opener = case.first + 2
    fenced = (case.opens(2), case.inside(3, opener), case.inside(4, opener),
              case.inside(6, opener))
    cases: list[tuple[str, str, list[str]]] = [
        # Two markers on a line, and a category twice.
        ('two markers on one line, one highlight', case.text(
            '- **New libraries**: five. - **Dependencies**: one.'), []),
        ('a duplicated category', case.text(
            '- **Dependencies**: one.', '- **Dependencies**: two.'), [ORDER]),
        # A marker hidden in a code span, a link or a split line, and line endings.
        ('a marker in a code span', case.text(
            real, '', '`- **Developer experience**: fake extra credit.`'), [case.at(2)]),
        ('a marker in a link', case.text(
            real, '', '[- **Developer experience**: fake.](https://example.com/x)'),
         [case.at(2)]),
        ('text before the first highlight, named on its line', case.text(
            release.HIGHLIGHTS, '', 'Summary of this release:', '', real), [case.at(4)]),
        ('a marker split across lines', case.text('- **New', 'libraries**: text here.'),
         [case.at(0), case.at(1)]),
        ('an empty sentence at the end', case.text(real, '- **Dependencies**: '),
         [case.at(1)]),
        ('the placeholder without its comment', case.text(*unwrapped),
         [case.html(0), case.at(0), case.at(1), case.at(2)]),
        ('CRLF line endings', case.text(*clean).replace('\n', '\r\n'), []),
        ('six highlights on six lines', case.text(*(['- **Dependencies**: one.'] * 6)),
         [f'{WHATS_NEW}: 6 highlights, and there are at most 5', ORDER]),
        # Fences, tabs, stars, a second heading and comments.
        ('a backtick fence', case.text(
            real, '', '```', '- **Dependencies**: fake.', '```', '', clean[1]), list(fenced)),
        ('a tab after the colon', case.text(
            '- **Dependencies**: real one.', '', '- **New libraries**:\tfake.'),
         [case.at(2, 'a tab')]),
        ('a star in the category', case.text(
            '- **Dependencies**: real one.', '', '- **New*libraries**: fake.'), [case.at(2)]),
        ('a second heading', case.skeleton[:start] + second + '\n' + dependencies + '\n\n'
         + case.skeleton[end:],
         [f'{WHATS_NEW}:{second_line}: a second ## Highlights heading']),
        ('another comment wrapping a marker', case.text(
            real, '<!-- - **Dependencies**: fake. -->'), [case.html(1), case.at(1)]),
        ('a comment never closed', case.text(real, '<!--', '- **Dependencies**: fake.'),
         [case.html(1), case.at(1)]),
        ('a tab after the colon, first', case.text('- **New libraries**:\tfake.'),
         [case.at(0, 'a tab')]),
        ('a star in the category, first', case.text('- **New*libraries**: fake.'),
         [case.at(0)]),
        # A nested list item starts a Markdown block, which no continuation may.
        ('a nested list item', case.text(real, '  - a nested item.'), [case.block(1)]),
        ('no highlights at all', case.text(), []),
        ('a category outside ASCII', case.text('- **Café**: one.'), [case.at(0, CATEGORY)]),
        ('a byte order mark', '﻿' + case.text(*clean), []),
        ('a link holding bold text', case.text(
            '- **New libraries**: see [**bold link**](https://example.com).'), []),
        ('five highlights in order', case.text(
            '- **New libraries**: one.', '- **Performance improvements**: two.',
            '- **Dependencies**: three.', '- **Security & reliability**: four.',
            '- **Developer experience**: five.'), []),
        # Fences of every form, comments over several lines and bare line endings.
        ('a tilde fence', case.text(
            real, '', '~~~', '- **Dependencies**: fake.', '~~~', '', clean[1]), list(fenced)),
        ('a fence with an info string', case.text(
            real, '', '```python', '- **Dependencies**: fake.', '```', '', clean[1]),
         list(fenced)),
        ('a comment over several lines', case.text(
            real, '<!--', '- **Dependencies**: fake.', '-->'),
         [case.html(1), case.html(3), case.at(1), case.at(3)]),
        ('a fence never closed', case.text(real, '', '```', '- **Dependencies**: fake.'),
         [case.opens(2), case.inside(3, opener)]),
        ('trailing spaces', case.text(real + '   '), []),
        ('bare CR line endings', case.text(*clean).replace('\n', '\r'), []),
        ('two spaces in the heading', case.text(*clean).replace(heading, '##  Highlights\n'),
         [f'{WHATS_NEW} has no section ## Highlights']),
        ('a space after the heading', case.text(*clean).replace(heading, '## Highlights \n'),
         [f'{WHATS_NEW} has no section ## Highlights']),
        ('a third-level heading', case.text(*clean).replace(heading, '### Highlights\n'),
         [f'{WHATS_NEW} has no section ## Highlights']),
        ('markers under another heading', case.text(
            real, '', '## Other', '', '- **Dependencies**: one.', '- **Dependencies**: two.'),
         []),
        ('a continuation after a blank line', case.text(real, '', '  continued.'),
         [case.at(2, 'a continuation with no highlight before it')]),
        ('a no-break space after the colon', case.text('- **New libraries**: one.'),
         [case.at(0)]),
        ('a zero-width space in the category', case.text('- **New​ libraries**: one.'),
         [case.at(0, CATEGORY)]),
        ('a zero-width joiner before the marker', case.text('‍' + real), [case.at(0)]),
        ('a fence indented by three spaces', case.text(
            real, '', '   ```', '- **Dependencies**: fake.', '   ```', '', clean[1]),
         list(fenced)),
        ('four spaces are no fence', case.text('    ```', real, '    ```'),
         [case.at(0), case.at(2)]),
    ]
    wrong = []
    for label, text, expected in cases:
        found = case.check(text)
        if found != expected:
            wrong.append(f'{label}: expected {expected}, found {found}')
    assert not wrong, '\n'.join(wrong)


def test_whats_new_holds_no_html_but_its_placeholder(directory: Path) -> None:
    # Fix round 5: the What's new holds no HTML but the placeholder comment whats-new writes,
    # byte for byte, right below ## Highlights. Any other "<" followed by a letter, "/", "!" or
    # "?" (a tag, a comment, a declaration, a processing instruction), and any "-->", is named
    # on its line, anywhere in the file, inside a code span too: which backticks pair into a
    # code span depends on the blocks, links and tables around them, so no reading short of a
    # Markdown parser could tell a code span's "<" from a tag's.
    case = Highlights(directory)
    real = '- **New libraries**: real one.'
    found = case.check(case.text(real, '<div>', '- **Dependencies**: inside a div.', '</div>'))
    assert found == [case.html(1), case.html(3), case.at(1), case.at(3)], found
    # A comment opened above the section and closed on a heading below it hides the section
    # from a reader: both of its lines are named.
    hidden = case.text(real).replace('## Highlights\n', '<!--\n## Highlights\n').replace(
        'Release notes:', '## Updated libraries -->\n\nRelease notes:')
    lines = hidden.split('\n')
    found = case.check(hidden)
    assert found == [html(lines.index('<!--') + 1),
                     html(lines.index('## Updated libraries -->') + 1)], found
    # The placeholder edited by one character is a comment like any other, and its lines are
    # no highlights.
    edited = release.HIGHLIGHTS.replace('At most five', 'At most six')
    found = case.check(case.text(edited, '', real))
    assert found == [case.html(0), case.html(2), case.at(0), case.at(1), case.at(2)], found
    # The placeholder twice: the second is HTML. The placeholder moved below a highlight, out
    # of its place right below the heading, is HTML too.
    found = case.check(case.text(release.HIGHLIGHTS, '', real, '', release.HIGHLIGHTS))
    assert found == [case.html(6), case.html(8), case.at(6), case.at(7), case.at(8)], found
    found = case.check(case.text(real, '', release.HIGHLIGHTS))
    assert found == [case.html(2), case.html(4), case.at(2), case.at(3), case.at(4)], found
    # A tag inside a code span is refused all the same.
    found = case.check(case.text('- **Developer experience**: `std::vector<int>` works.'))
    assert found == [case.html(0)], found
    # Anywhere in the file: in the New libraries, a closing tag, a processing instruction, a
    # declaration, an autolink, and "-->" in prose.
    library = '- **config**: config, a library, from R.'
    for tag in ('<b>bold</b>', '</p>', '<?php ?>', '<![CDATA[x]]>', '<!DOCTYPE html>',
                '<https://example.com>', 'then --> now'):
        text = case.text(real).replace(library, f'{library} {tag}')
        found = case.check(text)
        assert found == [html(text.split('\n').index(f'{library} {tag}') + 1)], (tag, found)
    # Not HTML: an entity, and "<" before a space, a digit or "=".
    assert case.check(case.text(
        '- **Performance improvements**: &lt;div&gt; is text; a < b, <3 s and a <= b.')) == []


def test_whats_new_section_ends_at_a_heading(directory: Path) -> None:
    # Fix round 5: the section Highlights ends at the next ## heading, or at the closing
    # paragraph whats-new writes, as it writes it, at the end of the file: a reader sees no end
    # at a line that merely starts "Release notes: ", so the highlights after one are still
    # read, counted, and the line itself is no highlight.
    case = Highlights(directory)
    real = '- **New libraries**: real one.'
    found = case.check(case.text(real, 'Release notes: none.',
                                 *(['- **Dependencies**: more.'] * 8)))
    assert found == [case.at(1), f'{WHATS_NEW}: 9 highlights, and there are at most 5', ORDER], (
        found)
    # A line after the closing paragraph, which then no longer ends the file: the closing's
    # own two lines are read as lines of the section, and refused.
    text = case.text(real) + '- **Dependencies**: after the end.\n'
    lines = text.split('\n')
    closing = next(index for index, line in enumerate(lines) if line.startswith('Release notes:'))
    found = case.check(text)
    assert found == [case.at(closing + 1 - case.first), case.at(closing + 2 - case.first)], found
    # The closing paragraph without the file's last newline still ends the section.
    assert case.check(case.text(real).removesuffix('\n')) == []


def test_whats_new_a_continuation_starts_no_markdown_block(directory: Path) -> None:
    # A continuation's text, after its two spaces, is more of the highlight's sentence
    # only when Markdown reads it so: one that starts a block (a list item, a heading, a quote,
    # a table row, a thematic break or a setext underline) shows the reader that block inside
    # the bullet instead, and is named on its line.
    case = Highlights(directory)
    real = '- **New libraries**: real one.'
    for first, continuation in ((real, '  - **Dependencies**: a nested bullet.'),
                                (real, '  ---'),
                                ('- **New libraries**: a | b', '  | --- | --- |'),
                                (real, '  # a heading'),
                                (real, '  > a quote')):
        found = case.check(case.text(first, continuation))
        assert found == [case.block(1)], (continuation, found)
    # Every marker: a bullet before a space, an ordered item's number before "." or ")" and a
    # space, "#", ">", "|", and a line of only "-", "=", "*" or "_" and spaces, a thematic break
    # or a setext underline, one character long too, since "=" or "-" alone underlines a
    # paragraph.
    for continuation in ('  - x', '  * x', '  + x', '  1. x', '  12) x', '  #x', '  ## x',
                         '  >x', '  |x', '  ***', '  ___', '  ===', '  - - -', '  * * *',
                         '  _ _ _', '  --- ', '  = = =', '  =', '  -'):
        found = case.check(case.text(real, continuation))
        assert found == [case.block(1)], (continuation, found)
    # A fence opener in a continuation's place stays a fence's own finding.
    found = case.check(case.text(real, '  ```'))
    assert found == [case.opens(1)], found
    # Text, a code span, a link, emphasis, and a marker's character not followed by a space
    # stay a continuation, in LF and in CRLF.
    for continuation in ('  and more words.', '  `code` in a span.',
                         '  [a link](https://example.com).', '  -x without a space.',
                         '  +x too.', '  *emphasis* and _more_.', '  1.5 times faster.'):
        assert case.check(case.text(real, continuation)) == [], continuation
        assert case.check(case.text(real, continuation).replace('\n', '\r\n')) == [], (
            continuation)


def test_whats_new_five_highlights_with_continuations_check_clean(directory: Path) -> None:
    # The legitimate path: five highlights, one per category in CATEGORIES' order, three of
    # them continued on lines of their own, a blank line between two, and backticks inside a
    # sentence, check clean; with the placeholder comment kept above them too, in LF and CRLF.
    case = Highlights(directory)
    five = ('- **New libraries**: config, the version every library reads, arrives.',
            '  It is header-only.',
            '- **Performance improvements**: nothing builds slower than in the previous version.',
            '- **Dependencies**: Boost 1.90 and nothing else,',
            '  each pinned by its SHA-256.',
            '',
            '- **Security & reliability**: every release is signed by its builder.',
            '- **Developer experience**: `b2 whats-new` writes this page,',
            '  and the owner approves it.')
    assert case.check(case.text(*five)) == []
    assert case.check(case.text(*five).replace('\n', '\r\n')) == []
    assert case.check(case.text(release.HIGHLIGHTS, '', *five)) == []
    assert case.check(case.text(release.HIGHLIGHTS, '', *five).replace('\n', '\r\n')) == []


def run_dist(root: Path, version: release.Version, out: Path) -> None:
    """Runs dist, which prints the two files it writes, and nothing else."""
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        release.dist(root, version, out)
    archive = out / f'webcpp-{version.name}.tar.gz'
    assert printed.getvalue() == f'{archive}\n{archive}.txt\n', printed.getvalue()


def test_dist_is_reproducible(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    run_dist(tree.root, V010, directory / 'out one')
    first = (directory / 'out one/webcpp-0.1.0.tar.gz').read_bytes()
    time.sleep(1.1)
    run_dist(tree.root, V010, directory / 'out two')
    assert (directory / 'out two/webcpp-0.1.0.tar.gz').read_bytes() == first
    # The same commits and pages at another path, every page's time changed.
    other = directory / 'another place'
    shutil.copytree(tree.root, other, symlinks=True)
    for page in other.rglob('index.html'):
        os.utime(page, (0, 0))
    run_dist(other, V010, directory / 'out three')
    assert (directory / 'out three/webcpp-0.1.0.tar.gz').read_bytes() == first
    digest, name = (directory / 'out one/webcpp-0.1.0.tar.gz.txt').read_text().split()
    assert (digest, name) == (hashlib.sha256(first).hexdigest(), 'webcpp-0.1.0.tar.gz')
    with tarfile.open(directory / 'out one/webcpp-0.1.0.tar.gz') as archive:
        assert all(member.startswith('webcpp-0.1.0/') for member in archive.getnames())


def test_dist_leaves_out_dot_files_and_what_git_does_not_track(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    scratch.write(tree.root / 'bin/dist/old.tar.gz', 'ignored\n')
    run_dist(tree.root, V010, directory / 'out')
    with tarfile.open(directory / 'out/webcpp-0.1.0.tar.gz') as archive:
        members = {member.name.removeprefix('webcpp-0.1.0/'): member
                   for member in archive.getmembers()}
    for absent in ('.gitignore', '.clang-format', '.github/workflows/ci.yml',
                   'libs/alpha/.gitattributes', 'libs/alpha/.gitignore', 'bin/dist/old.tar.gz'):
        assert absent not in members, absent
    for present in ('README.md', 'doc/index.adoc', 'doc/html/index.html',
                    'libs/alpha/doc/html/index.html', 'libs/alpha/include/webcpp/alpha.hpp',
                    'libs/config/include/webcpp/version.hpp'):
        assert present in members, present
    assert members['tools/run.sh'].mode == 0o755 and members['README.md'].mode == 0o644
    assert {(member.uid, member.gid, member.uname, member.gname)
            for member in members.values()} == {(0, 0, '', '')}


def test_dist_refuses_a_dirty_tree_and_missing_pages(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    out = directory / 'out'
    scratch.write(tree.library('alpha') / 'notes.txt', 'untracked\n')
    try:
        release.dist(tree.root, V010, out)
    except release.Failure as failure:
        assert 'libs/alpha/notes.txt is not committed' in str(failure), failure
    else:
        raise AssertionError('dist archived a dirty tree')
    (tree.library('alpha') / 'notes.txt').unlink()
    (tree.library('beta') / 'doc/html/index.html').unlink()
    try:
        release.dist(tree.root, V010, out)
    except release.Failure as failure:
        assert 'libs/beta/doc/html/index.html is not built' in str(failure), failure
    else:
        raise AssertionError('dist archived without a page')
    assert not out.exists()


# The ten bytes every archive's gzip header is: no file name, no time, the best compression,
# and the operating system unknown.
GZIP_HEADER = b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff'


def dist_refusal(root: Path, version: release.Version, out: Path) -> str:
    """What dist refuses to archive root for, which it must; it writes nothing."""
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            release.dist(root, version, out)
    except release.Failure as failure:
        assert not out.exists(), out
        return str(failure)
    raise AssertionError(f'dist archived {root}')


def member_bytes(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    """The bytes the archive holds for a file member."""
    file = archive.extractfile(member)
    assert file is not None, member.name
    return file.read()


def test_dist_fixes_every_field(directory: Path) -> None:
    # A name whose UTF-8 is not ASCII; names a collating locale orders otherwise than their code
    # points; a link; pages with modes of their own.
    tree = scratch.make_tree(directory)
    commit_bytes(tree, None, 'doc/caf\u00e9.txt', 'caf\u00e9\n'.encode())
    commit_bytes(tree, None, 'Zeta.txt', b'zeta\n')
    commit_bytes(tree, None, 'alpha_b.txt', b'underscore\n')
    commit_bytes(tree, None, 'alpha-b.txt', b'dash\n')
    (tree.root / 'link').symlink_to('README.md')
    scratch.git(tree.root, 'add', 'link')
    # HEAD committed long before dist runs: every member carries its time, never the clock's.
    os.environ['GIT_COMMITTER_DATE'] = '2001-02-03T04:05:06+0000'
    try:
        scratch.git(tree.root, 'commit', '-q', '-m', 'link')
    finally:
        del os.environ['GIT_COMMITTER_DATE']
    (tree.root / 'doc/html/index.html').chmod(0o755)
    (tree.library('alpha') / 'doc/html/index.html').chmod(0o600)
    run_dist(tree.root, V010, directory / 'out')
    data = (directory / 'out/webcpp-0.1.0.tar.gz').read_bytes()
    assert data[:10] == GZIP_HEADER, data[:10]
    # One gzip member, whole: its CRC and its size are checked.
    assert gzip.decompress(data)
    committed = int(scratch.git(tree.root, 'log', '-1', '--format=%ct', 'HEAD'))
    assert committed == 981173106, committed
    with tarfile.open(directory / 'out/webcpp-0.1.0.tar.gz') as archive:
        listed = archive.getmembers()
        names = [member.name for member in listed]
        assert names == sorted(names) and len(set(names)) == len(names), names
        assert names.index('webcpp-0.1.0/Zeta.txt') < names.index('webcpp-0.1.0/alpha-b.txt') \
            < names.index('webcpp-0.1.0/alpha_b.txt'), names
        for member in listed:
            assert member.mtime == committed, (member.name, member.mtime)
            assert member.type in (tarfile.REGTYPE, tarfile.SYMTYPE), member.name
            assert (member.uid, member.gid, member.uname, member.gname) == (0, 0, '', '')
            assert (member.devmajor, member.devminor) == (0, 0), member.name
            # No time beside mtime, as an atime or a ctime would be, and no other record.
            assert set(member.pax_headers) <= {'path'}, (member.name, member.pax_headers)
        members = {member.name.removeprefix('webcpp-0.1.0/'): member for member in listed}
        cafe = members['doc/caf\u00e9.txt']
        assert cafe.pax_headers == {'path': 'webcpp-0.1.0/doc/caf\u00e9.txt'}, cafe.pax_headers
        assert member_bytes(archive, cafe) == 'caf\u00e9\n'.encode()
        link = members['link']
        assert (link.issym(), link.linkname, link.mode) == (True, 'README.md', 0o777)
        assert member_bytes(archive, members['README.md']) == b'# webcpp\n'
    assert members['doc/html/index.html'].mode == 0o644
    assert members['libs/alpha/doc/html/index.html'].mode == 0o644


def test_dist_ignores_the_environment(directory: Path) -> None:
    # The archive dist writes here, and the one release.py writes from another process: another
    # time zone, locale and umask, every working file's mode cut as a umask of 077 would, a tar
    # and a gzip that fail on the path, and git configured to change line ends.
    tree = scratch.make_tree(directory)
    commit_bytes(tree, None, 'doc/caf\u00e9.txt', 'caf\u00e9\n'.encode())
    run_dist(tree.root, V010, directory / 'here')
    expected = (directory / 'here/webcpp-0.1.0.tar.gz').read_bytes()
    # A checkout that writes CRLF line ends, which git, so configured, finds equal to HEAD's.
    (tree.root / 'README.md').unlink()
    scratch.git(tree.root, '-c', 'core.autocrlf=true', 'checkout', '--', 'README.md')
    assert (tree.root / 'README.md').read_bytes() == b'# webcpp\r\n'
    for path in tree.root.rglob('*'):
        if path.is_file() and not path.is_symlink() and '.git' not in path.parts:
            path.chmod(path.stat().st_mode & 0o700)
    shims = directory / 'shims'
    for tool in ('tar', 'gzip', 'gtar', 'bsdtar', 'pigz'):
        scratch.write(shims / tool, '#!/bin/sh\nexit 1\n')
        (shims / tool).chmod(0o755)
    config = directory / 'gitconfig'
    scratch.write(config, '[core]\n\tautocrlf = true\n\tquotePath = true\n')
    environment = {name: value for name, value in os.environ.items()
                   if name not in ('PYTHONUTF8', 'PYTHONIOENCODING', 'LANG', 'LC_CTYPE')}
    environment.update({'TZ': 'Pacific/Kiritimati', 'LC_ALL': 'en_US.ISO8859-1',
                        'PATH': f'{shims}{os.pathsep}{os.environ["PATH"]}',
                        'SOURCE_DATE_EPOCH': '1', 'GZIP': '-1', 'GIT_CONFIG_GLOBAL': str(config)})
    completed = subprocess.run(['sh', '-c', 'umask 077 && exec "$@"', 'sh', sys.executable,
                                str(Path(release.__file__)), 'dist', '--root', str(tree.root),
                                '--version', '0.1.0', '--out', str(directory / 'there')],
                               env=environment, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert (directory / 'there/webcpp-0.1.0.tar.gz').read_bytes() == expected


def test_dist_refuses_libraries_not_as_recorded(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    out = directory / 'out'
    assert 'the build read the version 0.2.0' in dist_refusal(tree.root, V020, out)
    scratch.git(tree.library('beta'), 'commit', '-q', '--allow-empty', '-m', 'beta: unrecorded')
    refused = dist_refusal(tree.root, V010, out)
    assert 'libs/beta is at ' in refused and ', and the superproject records ' in refused, refused
    tree.record('beta')
    shutil.rmtree(tree.library('beta'))
    tree.library('beta').mkdir()
    assert 'libs/beta is a submodule of the superproject at HEAD, and is not checked out' in \
        dist_refusal(tree.root, V010, out)
    (directory / 'second').mkdir()
    tree = scratch.make_tree(directory / 'second')
    shutil.rmtree(tree.library('alpha') / '.git')
    assert 'libs/alpha is no git checkout of its own' in dist_refusal(tree.root, V010, out)


def test_dist_names_what_it_cannot_read_or_write(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    root = str(tree.root)
    status, output, error = run_main('dist', '--root', root, '--version', '0.1.0', '--out',
                                     str(directory / 'out'))
    assert (status, error) == (0, ''), (status, error)
    # The directory as main resolves it: a temporary directory's path may run through a link.
    out = (directory / 'out').resolve()
    assert output == f'{out / "webcpp-0.1.0.tar.gz"}\n{out / "webcpp-0.1.0.tar.gz.txt"}\n', output
    page = tree.library('alpha') / 'doc/html/index.html'
    page.chmod(0)
    try:
        status, output, error = run_main('dist', '--root', root, '--version', '0.1.0', '--out',
                                         str(directory / 'unread'))
    finally:
        page.chmod(0o644)
    assert (status, output) == (2, ''), (status, output)
    assert error.startswith('dist: libs/alpha/doc/html/index.html cannot be read: '), error
    assert not (directory / 'unread').exists()
    scratch.write(directory / 'a file', 'no directory\n')
    status, output, error = run_main('dist', '--root', root, '--version', '0.1.0', '--out',
                                     str(directory / 'a file'))
    assert (status, output) == (2, ''), (status, output)
    assert error.startswith(f'dist: {(directory / "a file").resolve()} cannot be written: '), error
    scratch.write(tree.root / 'README.md', '# changed\n')
    status, output, error = run_main('dist', '--root', root, '--version', '0.1.0', '--out',
                                     str(directory / 'dirty'))
    assert (status, error) == (1, ''), (status, error)
    assert output.startswith('dist: README.md is not committed'), output
    assert not (directory / 'dirty').exists()


def test_dist_names_what_is_not_utf8(directory: Path) -> None:
    # A path, and a link's target, that are not UTF-8, committed through git's plumbing, which
    # no file system needs to hold: dist names each rather than archive it.
    for entry, fault in ((b'100644,%s,caf\xe9.txt', "the path b'caf\\xe9.txt' is not UTF-8"),
                         (b'120000,%s,link', 'link is a link whose target is not UTF-8')):
        (directory / fault[:4]).mkdir()
        tree = scratch.make_tree(directory / fault[:4])
        blob = subprocess.run([*scratch.GIT, '-C', str(tree.root), 'hash-object', '-w', '--stdin'],
                              input=b'caf\xe9', capture_output=True, check=True).stdout.strip()
        subprocess.run([*scratch.GIT, '-C', str(tree.root), 'update-index', '--add',
                        '--cacheinfo', entry % blob], capture_output=True, check=True)
        scratch.git(tree.root, 'commit', '-q', '-m', 'not UTF-8')
        try:
            refused = '\n'.join(release.repository_refusals(tree.root, ['alpha', 'beta', 'config']))
        except release.Broken as broken:
            refused = str(broken)
        assert fault in refused, (fault, refused)


# The SHA-256 of the tar, and of the .tar.gz, dist writes for test_dist_bytes_are_pinned's tree:
# a change of the tar's layout, of the deflate, its level or window, of the gzip header, or of
# the files scratch.py writes, changes them. Measured with CPython 3.14.7 and zlib 1.2.12.
PINNED_TAR = 'c00990248d40f23cf48ce1b9d2b7403d3e7727b312dbc8573de18ef5e9635ad4'
PINNED_TAR_GZ = 'bb9c4f2f5601b81367497fd44f91554330996d3d477143e76aa2f76f8c31e551'


def test_dist_bytes_are_pinned(directory: Path) -> None:
    # The scratch tree, every commit at one time, with a path of over 255 bytes, a name that is
    # not ASCII, a link whose target is 121 bytes and 100 KiB that do not repeat.
    os.environ['GIT_COMMITTER_DATE'] = '2001-02-03T04:05:06+0000'
    try:
        tree = scratch.make_tree(directory)
        long_directory = '/'.join(['d' * 60] * 3)
        commit_bytes(tree, None, f'{long_directory}/{"f" * 90}.txt', b'long\n')
        commit_bytes(tree, None, 'doc/caf\u00e9.txt', 'caf\u00e9\n'.encode())
        commit_bytes(tree, None, 'data.bin', b''.join(hashlib.sha256(i.to_bytes(4, 'big')).digest()
                                                    for i in range(3200)))
        (tree.root / 'long-link').symlink_to('/'.join(['d' * 60] * 2))
        scratch.git(tree.root, 'add', 'long-link')
        scratch.git(tree.root, 'commit', '-q', '-m', 'long-link')
    finally:
        del os.environ['GIT_COMMITTER_DATE']
    run_dist(tree.root, V010, directory / 'out')
    data = (directory / 'out/webcpp-0.1.0.tar.gz').read_bytes()
    found = hashlib.sha256(gzip.decompress(data)).hexdigest(), hashlib.sha256(data).hexdigest()
    assert found == (PINNED_TAR, PINNED_TAR_GZ), found


@contextlib.contextmanager
def zlib_as(**changes: object) -> Iterator[None]:
    """release's zlib with changes: another version, zlib-ng's own attribute, another deflate."""
    fake = types.SimpleNamespace(**{name: getattr(zlib, name) for name in dir(zlib)
                                    if not name.startswith('_')})
    for name, value in changes.items():
        setattr(fake, name, value)
    setattr(release, 'zlib', fake)
    try:
        yield
    finally:
        setattr(release, 'zlib', zlib)


def test_dist_refuses_a_deflate_other_than_zlib(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    out = directory / 'out'

    def fast(level: int, method: int, wbits: int) -> object:
        return zlib.compressobj(level - 8, method, wbits)

    for changes, version in (({'ZLIB_RUNTIME_VERSION': '1.3.1.zlib-ng'}, '1.3.1.zlib-ng'),
                             ({'ZLIBNG_VERSION': '2.2.5'}, zlib.ZLIB_RUNTIME_VERSION),
                             ({'compressobj': fast}, zlib.ZLIB_RUNTIME_VERSION)):
        with zlib_as(**changes):
            status, output, error = run_main('dist', '--root', str(tree.root), '--version',
                                             '0.1.0', '--out', str(out))
        assert (status, output) == (2, ''), (changes, status, output)
        assert error == (f"dist: this Python's zlib, {version}, deflates otherwise than zlib, "
                         "whose output webcpp's archives are: run dist with a Python linked to "
                         'zlib\n'), (changes, error)
        assert not out.exists()
    # The probe's input, which zlib-ng 2.2.5 deflates otherwise than zlib (18478 bytes against
    # 18411), where an input of a tenth its size deflates the same: it may not shrink.
    assert hashlib.sha256(release.probe_input()).hexdigest() == \
        '1c4f36a1df3f199b7c519344261379f6f7525b40e27ec1973ed0045ed5f1f52f'


def test_dist_refuses_files_the_doc_build_does_not_write(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    strays = ('doc/html/index.html~', 'doc/html/.buildinfo',
              'libs/alpha/doc/html/old/removed-section.html', 'libs/beta/doc/html/images/logo.svg')
    for stray in strays:
        scratch.write(tree.root / stray, 'stray\n')
    refused = dist_refusal(tree.root, V010, directory / 'out')
    for stray in strays:
        assert f'{stray} is no page the doc build writes: remove it' in refused, refused


def test_dist_refuses_submodules_it_does_not_archive(directory: Path) -> None:
    # A library's own submodule, and one of the superproject outside libs/: a gitlink, its
    # directory empty, as a submodule not checked out leaves it.
    tree = scratch.make_tree(directory)
    alpha = tree.library('alpha')
    commit = scratch.git(alpha, 'rev-parse', 'HEAD').strip()
    for directory_, path in ((alpha, 'third_party/nested'), (tree.root, 'tools/sub')):
        (directory_ / path).mkdir(parents=True)
        scratch.git(directory_, 'update-index', '--add', '--cacheinfo', f'160000,{commit},{path}')
        scratch.git(directory_, 'commit', '-q', '-m', f'{path}: a submodule')
        if directory_ == alpha:
            tree.record('alpha')
    refused = dist_refusal(tree.root, V010, directory / 'out')
    assert refused.split('\n') == [
        'tools/sub is a submodule of the superproject outside libs/, which dist does not archive',
        'libs/alpha/third_party/nested is a submodule of libs/alpha, which dist does not archive',
    ], refused


def test_dist_refuses_links_out_of_the_archive(directory: Path) -> None:
    tree = scratch.make_tree(directory)
    alpha = tree.library('alpha')
    links = (('escape', '../../../../etc/passwd'), ('absolute', '/etc/passwd'),
             ('toignore', '.gitignore'), ('doc/hidden', '../.github/workflows/ci.yml'),
             ('doc/readme', '../README.md'), ('libs/alpha/up', '../../README.md'),
             ('libs/alpha/doc/header', '../include/webcpp/alpha.hpp'))
    for path, target in links:
        (tree.root / path).symlink_to(target)
        repository = alpha if path.startswith('libs/alpha/') else tree.root
        scratch.git(repository, 'add', str((tree.root / path).relative_to(repository)))
    scratch.git(alpha, 'commit', '-q', '-m', 'alpha: links')
    # Recording alpha commits the superproject's links too.
    tree.record('alpha')
    refused = dist_refusal(tree.root, V010, directory / 'out')
    assert refused.split('\n') == [
        'absolute is a link to the absolute path /etc/passwd',
        'doc/hidden is a link to ../.github/workflows/ci.yml, a dot file the archive leaves out',
        'escape is a link to ../../../../etc/passwd, outside its repository',
        'toignore is a link to .gitignore, a dot file the archive leaves out',
        'libs/alpha/up is a link to ../../README.md, outside its repository',
    ], refused


def test_dist_leaves_no_new_file_when_a_write_fails(directory: Path) -> None:
    # The checksum's temporary cannot be written: the archive and the checksum dist wrote before
    # stay as they were, and no temporary of its own stays.
    tree = scratch.make_tree(directory)
    out = directory / 'out'
    run_dist(tree.root, V010, out)
    archive, checksum = out / 'webcpp-0.1.0.tar.gz', out / 'webcpp-0.1.0.tar.gz.txt'
    before = archive.read_bytes(), checksum.read_bytes()
    commit_bytes(tree, None, 'README.md', b'# changed\n')
    (out / 'webcpp-0.1.0.tar.gz.txt.partial').mkdir()
    try:
        run_dist(tree.root, V010, out)
    except release.Broken as broken:
        assert str(broken).startswith(f'{checksum} cannot be written: '), broken
    else:
        raise AssertionError('dist wrote through a directory')
    assert (archive.read_bytes(), checksum.read_bytes()) == before
    assert sorted(path.name for path in out.iterdir()) == [
        'webcpp-0.1.0.tar.gz', 'webcpp-0.1.0.tar.gz.txt', 'webcpp-0.1.0.tar.gz.txt.partial']


@contextlib.contextmanager
def replace_fails_at(call: int) -> Iterator[None]:
    """Path.replace, which fails with an OSError at its call-th call and works at the others."""
    original = Path.replace
    calls = [0]

    def replace(self: Path, target: Path) -> Path:
        calls[0] += 1
        if calls[0] == call:
            raise OSError(5, 'planted failure', str(target))
        return original(self, target)

    setattr(Path, 'replace', replace)
    try:
        yield
    finally:
        setattr(Path, 'replace', original)


def test_dist_replaces_the_pair_one_rename_at_a_time(directory: Path) -> None:
    # An old pair in out, then a new commit: the archive's rename fails, and the old pair stays
    # whole; the checksum's fails, and the archive is new beside the old checksum, which dist
    # says by name. Neither leaves a temporary.
    tree = scratch.make_tree(directory)
    out = directory / 'out'
    run_dist(tree.root, V010, out)
    archive, checksum = out / 'webcpp-0.1.0.tar.gz', out / 'webcpp-0.1.0.tar.gz.txt'
    old = archive.read_bytes(), checksum.read_bytes()
    commit_bytes(tree, None, 'README.md', b'# changed\n')
    run_dist(tree.root, V010, directory / 'clean')
    new = (directory / 'clean/webcpp-0.1.0.tar.gz').read_bytes()
    assert new != old[0]
    for call, files, said in (
            (1, old, f'{archive} cannot be written: [Errno 5] planted failure: '
                     f"'{archive}'; it and webcpp-0.1.0.tar.gz.txt are as they were"),
            (2, (new, old[1]), f'{checksum} cannot be written: [Errno 5] planted failure: '
                               f"'{checksum}'; webcpp-0.1.0.tar.gz is the new archive, and "
                               'webcpp-0.1.0.tar.gz.txt is as it was, which does not check it: '
                               'run dist again')):
        archive.write_bytes(old[0])
        checksum.write_bytes(old[1])
        try:
            with replace_fails_at(call):
                run_dist(tree.root, V010, out)
        except release.Broken as broken:
            assert str(broken) == said, (call, str(broken))
        else:
            raise AssertionError(f'call {call}: no rename failed')
        assert (archive.read_bytes(), checksum.read_bytes()) == files, call
        assert sorted(path.name for path in out.iterdir()) == [archive.name, checksum.name]
    # Run again, the pair is new and whole.
    run_dist(tree.root, V010, out)
    assert archive.read_bytes() == new
    assert checksum.read_text().split()[0] == hashlib.sha256(new).hexdigest()


def git_checkout(root: Path) -> None:
    """Makes the harness's scratch superproject root a git checkout whose libraries, config and
    demo, are gitlinks, config holding the version.hpp of 0.1.0, with an index and notes of its
    own that name config and demo: the copy's are this superproject's, which name others."""
    scratch.write(root / 'libs/config/build.jam', 'project /webcpp/config ;\n\nalias config ;\n')
    scratch.write(root / 'libs/config/include/webcpp/version.hpp',
                  scratch.VERSION_HPP.format(number=100, lib='0_1'))
    # A project in config's doc, which the aggregate doc names, and which builds no page.
    scratch.write(root / 'libs/config/doc/Jamfile', '# config\'s changelog, and no page.\n')
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
    # b2 dist builds every page, then packs: the index's conversion comes before the archive.
    # The doc build needs Boost, which the configuration below takes away.
    (root / '.local/mrdocs').symlink_to(harness.mrdocs_root())
    dry = harness.run_b2(root, '-n', 'dist')
    harness.expect(dry, True)
    converted = dry.stdout.find('index.adoc')
    packed = dry.stdout.find('release.py" dist')
    assert 0 <= converted < packed, dry.stdout[-4000:]
    # And every page's copy into its doc/html, the index's and demo's, which dist archives.
    copies = [match.start() for match in re.finditer(r'^common\.copy \S*doc/html/index\.html$',
                                                      dry.stdout, re.MULTILINE)]
    assert len(copies) == 2 and max(copies) < packed, dry.stdout[-4000:]
    # check-release compiles nothing, so it needs no Boost, as declared-targets needs none.
    harness.configure(root, harness.without_boost() + 'using boost : 1.92 ;\n')
    harness.expect(harness.run_b2(root, '-d0', 'check-release', env_extra={'BOOST_ROOT': None}),
                   True)
    # A fault fails the target, which prints it: committed, and recorded, since a tree with
    # uncommitted changes is refused first.
    scratch.write(root / 'libs/config/include/webcpp/version.hpp',
                  scratch.VERSION_HPP.format(number=100, lib='0_2'))
    scratch.git(root / 'libs/config', 'commit', '-q', '-a', '-m', 'config: 0_2')
    scratch.git(root, 'add', 'libs/config')
    scratch.git(root, 'commit', '-q', '-m', 'libs/config: recorded')
    harness.expect(harness.run_b2(root, 'check-release', env_extra={'BOOST_ROOT': None}), False,
                   'check: libs/config/include/webcpp/version.hpp: WEBCPP_VERSION names 0.1.0, '
                   'and WEBCPP_LIB_VERSION "0_2" is not "0_1"')
    harness.expect(harness.run_b2(root, 'whats-new'), True)
    assert (root / 'doc/releases/0.1.0.whats-new.md').is_file()


def test_jamroot_reads_the_version(root: Path) -> None:
    # The version check-release hands release.py, read from version.hpp's WEBCPP_VERSION: b2 -n
    # prints the command and runs nothing. The Jamroot's half of FORMS, then its reading of names
    # of every width, a header that defines the macro twice, and one it cannot read.
    header = root / 'libs/config/include/webcpp/version.hpp'
    for form, name in FORMS:
        header.parent.mkdir(parents=True, exist_ok=True)
        header.write_bytes((form + LIB_LINE).encode('utf-8'))
        if name is None:
            harness.expect(harness.run_b2(root, '-n', 'check-release'), False,
                           'libs/config/include/webcpp/version.hpp has no line '
                           '`#define WEBCPP_VERSION <number>`, the number in decimal, without a '
                           'leading zero')
        else:
            harness.expect(harness.run_b2(root, '-n', 'check-release'), True,
                           f'--version "{name}"')
    for number, name in ((100203, '1.2.3'), (1000000, '10.0.0'), (9999, '0.99.99'),
                         (2001000, '20.10.0')):
        scratch.write(header, scratch.VERSION_HPP.format(number=number, lib='0_1'))
        harness.expect(harness.run_b2(root, '-n', 'check-release'), True,
                       f'--version "{name}"')
    scratch.write(header, TWICE)
    harness.expect(harness.run_b2(root, '-n', 'check-release'), False,
                   'libs/config/include/webcpp/version.hpp defines WEBCPP_VERSION twice')
    scratch.write(header, scratch.VERSION_HPP.format(number=100, lib='0_1'))
    header.chmod(0)
    try:
        result = harness.run_b2(root, '-n', 'check-release')
    finally:
        header.chmod(0o644)
    harness.expect(result, False, 'libs/config/include/webcpp/version.hpp cannot be read')


def test_the_tree_s_version(root: Path) -> None:
    # This checkout's own version.hpp, which config writes: release.py reads a coherent version
    # from it, and the Jamroot hands release.py the same name.
    tree_header = harness.ROOT / release.HEADER
    assert tree_header.is_file(), f'{tree_header} does not exist: check out libs/config'
    version, lib = release.read_version(harness.ROOT)
    assert lib == version.lib, (version, lib)
    scratch.write(root / release.HEADER, tree_header.read_text(encoding='utf-8'))
    harness.expect(harness.run_b2(root, '-n', 'check-release'), True,
                   f'--version "{version.name}"')


def test_jamroot_without_config(root: Path) -> None:
    # The copy holds no libs/config: everything but the release targets builds, the doc included,
    # and those stop, naming the header, dist before it builds a page. The doc build reads the
    # files demo's git lists, as tools/test/doc_test.py's prepare gives them.
    (root / '.local/mrdocs').symlink_to(harness.mrdocs_root())
    scratch.git(root / 'libs/demo', 'init', '-q')
    harness.expect(harness.run_b2(root, '-d0', 'declared-targets'), True)
    harness.expect(harness.run_b2(root, '-n', '-d0'), True)
    harness.expect(harness.run_b2(root, 'libs/demo/test'), True)
    harness.expect(harness.run_b2(root, '-d0', 'doc'), True)
    harness.expect(harness.run_b2(root, '-d0', 'check-release'), False,
                   'libs/config/include/webcpp/version.hpp', 'check out libs/config')
    harness.expect(harness.run_b2(root, '-d0', 'whats-new'), False,
                   'libs/config/include/webcpp/version.hpp', 'check out libs/config')
    harness.expect(harness.run_b2(root, '-d0', 'dist'), False,
                   'libs/config/include/webcpp/version.hpp', 'check out libs/config')


CASES: list[Callable[[Path], None]] = [
    test_versions_are_named,
    test_version_must_agree,
    test_check_fails_by_name,
    test_version_forms,
    test_scratch_files_keep_their_form,
    test_first_release_lists_every_library_as_new,
    test_changed_library_needs_a_line_and_a_listing,
    test_a_change_no_user_sees_needs_no_line,
    test_a_listed_library_without_a_line_fails,
    test_added_and_removed_libraries,
    test_a_missing_commit_and_a_stale_pointer,
    test_a_library_not_checked_out_is_named,
    test_the_previous_tag_is_the_newest_before_the_version,
    test_unreadable_files_are_named,
    test_uncommitted_changes_are_refused_first,
    test_a_library_without_its_own_git_is_named,
    test_names_that_are_no_version_are_named,
    test_an_updated_name_that_is_no_library,
    test_lines_out_of_form_are_named,
    test_compilers_tested_are_the_ci_lanes,
    test_frozen_state,
    test_index_includes_every_version_newest_first,
    test_template_opens_a_version_that_checks,
    test_the_tree_s_notes_name_the_ci_lanes,
    test_whats_new_skeleton,
    test_whats_new_lists_updated_libraries,
    test_whats_new_highlights_are_checked,
    test_whats_new_names_unreadable_files,
    test_whats_new_highlight_markers_must_start_a_line,
    test_whats_new_leading_text_is_named_by_its_own_line,
    test_whats_new_highlights_grammar_is_a_whitelist,
    test_whats_new_a_fence_refuses_the_rest_of_highlights,
    test_whats_new_every_adversarial_input,
    test_whats_new_holds_no_html_but_its_placeholder,
    test_whats_new_section_ends_at_a_heading,
    test_whats_new_a_continuation_starts_no_markdown_block,
    test_whats_new_five_highlights_with_continuations_check_clean,
    test_dist_is_reproducible,
    test_dist_leaves_out_dot_files_and_what_git_does_not_track,
    test_dist_refuses_a_dirty_tree_and_missing_pages,
    test_dist_fixes_every_field,
    test_dist_ignores_the_environment,
    test_dist_refuses_libraries_not_as_recorded,
    test_dist_names_what_it_cannot_read_or_write,
    test_dist_names_what_is_not_utf8,
    test_dist_bytes_are_pinned,
    test_dist_refuses_a_deflate_other_than_zlib,
    test_dist_refuses_files_the_doc_build_does_not_write,
    test_dist_refuses_submodules_it_does_not_archive,
    test_dist_refuses_links_out_of_the_archive,
    test_dist_leaves_no_new_file_when_a_write_fails,
    test_dist_replaces_the_pair_one_rename_at_a_time,
]

B2_CASES: list[Callable[[Path], None]] = [
    test_jamroot_targets,
    test_jamroot_reads_the_version,
    test_the_tree_s_version,
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
