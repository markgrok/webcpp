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
import shutil
import sys
import tempfile
from collections.abc import Callable
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
    # and those stop, naming the header. The doc build reads the files demo's git lists, as
    # tools/test/doc_test.py's prepare gives them.
    (root / '.local/mrdocs').symlink_to(harness.mrdocs_root())
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
