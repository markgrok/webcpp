#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""webcpp's release tooling (AGENTS.md chapter 11), which the Jamroot's explicit targets run.

Usage: release.py check --root <superproject> --version <a.b.c>

check names every fault that keeps the tree from being tagged webcpp-<a.b.c>:
- the superproject or a library holds a change its HEAD does not record: a changed, staged,
  deleted or new file that git does not ignore. This is named first, and alone: every other rule
  judges what the tag would carry;
- the version disagrees anywhere: WEBCPP_VERSION and WEBCPP_LIB_VERSION of
  libs/config/include/webcpp/version.hpp, the one place it is written, name different versions,
  or the version the Jamroot read, --version, is not theirs;
- the notes doc/releases/<a.b.c>.adoc do not exist, or they or a library's changelog break the
  form tools/release/changelog.py reads, each fault at its line;
- the section Releases of doc/index.adoc does not include the notes of every version of
  doc/releases, each once, newest first, this version's first;
- notes in preparation include a library's region other than tag=unreleased, or a changelog has
  the version's section already; frozen notes include a region other than tag=<a.b.c>, an
  Unreleased holds lines, Compilers tested is None., or a tag webcpp-<a.b.c> is not at HEAD;
  Compilers tested lists other lanes than the CI's, tools/ci/matrix.py's LANES, as the notes
  write them;
- a library is no git checkout of its own, is no submodule at HEAD, is not checked out, or is
  checked out at another commit than the superproject records;
- New Libraries or Removed Libraries is not exactly the libraries new or gone since the newest
  earlier tag webcpp-<x.y.z> that HEAD holds, every library for the first version; a tag
  webcpp-<x> whose x is no version is no release, and a notes file so named is named;
- a name under Updated Libraries is new, removed or no library, or its region holds no line;
- a library whose changelog has lines for this version is not under Updated Libraries;
- a library changed since that tag, under USER_VISIBLE, and its region has no line; or the
  commit a tag or HEAD records is not in its repository.
Exit 0 when nothing is wrong; 1 with each fault on a line of its own, `<command>: <fault>`; 2 on a
usage error, or when a file it reads is not there, cannot be read or is not UTF-8.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS / 'ci'))
import changelog  # noqa: E402  (beside this file)
import matrix  # noqa: E402  (tools/ci, put on the path above: its LANES are the CI's lanes)

# What a user of a library sees: a change under these paths of its repository needs a line in
# its changelog; its tests, its CI and its AGENTS.md need none. version.hpp, config's alone,
# moves at every release by the procedure, and is no change of config's.
USER_VISIBLE = ('include', 'build.jam', 'wit', 'meta/libraries.json', 'README.md', 'example',
                'doc', 'LICENSE*', ':(exclude)doc/changelog.adoc',
                ':(exclude)include/webcpp/version.hpp')

# A version's name as Version.parse takes it: three decimal numbers, none with a leading zero. A
# tag webcpp-<x> whose x is no such name is no release, and a notes file so named is named.
VERSION_NAME = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
TAG = re.compile(rf'webcpp-({VERSION_NAME})')
RELEASES = re.compile(r'^\[#releases\]\n== Releases\n', re.MULTILINE)
INCLUDED = re.compile(r'^include::releases/(\d+\.\d+\.\d+)\.adoc\[leveloffset=\+2\]$',
                      re.MULTILINE)
NOTES_FILE = re.compile(rf'({VERSION_NAME})\.adoc')

HEADER = 'libs/config/include/webcpp/version.hpp'
# A value runs to the end of its line, so config writes no comment after one: its exemption from
# clang-tidy is a NOLINTNEXTLINE on the line above.
DEFINE = re.compile(r'^#define (WEBCPP_VERSION|WEBCPP_LIB_VERSION) +(.+?)\s*$', re.MULTILINE)
# A number as the Jamroot reads one, and as C++ reads it too: decimal, in ASCII digits, since C++
# reads a leading zero as octal.
NUMBER = re.compile(r'0|[1-9][0-9]*')


class Failure(Exception):
    """Faults of the tree that stop a command, said to the user, one per line; exit 1."""


class Broken(Exception):
    """A usage error, or something the tool reads that is not there; exit 2."""


@dataclass(frozen=True, order=True)
class Version:
    """A version of webcpp, which orders as its numbers do."""

    major: int
    minor: int
    patch: int

    @staticmethod
    def of_number(number: int) -> Version:
        """The version WEBCPP_VERSION's number names: 100 is 0.1.0."""
        return Version(number // 100000, number // 100 % 1000, number % 100)

    @staticmethod
    def parse(name: str) -> Version:
        """The version name writes, <major>.<minor>.<patch>."""
        numbers = name.split('.')
        if len(numbers) != 3 or not all(NUMBER.fullmatch(number) for number in numbers):
            raise Broken(f'{name} is no version <major>.<minor>.<patch>')
        return Version(int(numbers[0]), int(numbers[1]), int(numbers[2]))

    @property
    def name(self) -> str:
        return f'{self.major}.{self.minor}.{self.patch}'

    @property
    def lib(self) -> str:
        """The version as WEBCPP_LIB_VERSION writes it: 0_1, 1_2_3."""
        return f'{self.major}_{self.minor}' + (f'_{self.patch}' if self.patch else '')

    @property
    def anchor(self) -> str:
        return self.name.replace('.', '-')

    @property
    def tag(self) -> str:
        return f'webcpp-{self.name}'

    @property
    def notes(self) -> str:
        """The path of the version's release notes in the superproject."""
        return f'doc/releases/{self.name}.adoc'


def read(root: Path, relative: str) -> str:
    """The text of the file relative in root; one that cannot be read, or is not UTF-8, is Broken,
    named."""
    try:
        return (root / relative).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as error:
        raise Broken(f'{relative} cannot be read: {error}') from error


def read_version(root: Path) -> tuple[Version, str]:
    """The version WEBCPP_VERSION names, and WEBCPP_LIB_VERSION's text without its quotes; each
    defined once, the number in decimal, as the Jamroot's webcpp-version reads it."""
    header = root / HEADER
    if not header.is_file():
        raise Broken(f'{HEADER} does not exist: check out libs/config')
    text = read(root, HEADER)
    found = DEFINE.findall(text)
    for macro in ('WEBCPP_VERSION', 'WEBCPP_LIB_VERSION'):
        if [name for name, _ in found].count(macro) > 1:
            raise Broken(f'{HEADER} defines {macro} twice')
    defined = dict(found)
    number = defined.get('WEBCPP_VERSION', '')
    lib = defined.get('WEBCPP_LIB_VERSION', '')
    if NUMBER.fullmatch(number) is None or len(lib) < 2 or lib[0] != '"' or lib[-1] != '"':
        raise Broken(f'{HEADER} has no lines `#define WEBCPP_VERSION <number>` and '
                     '`#define WEBCPP_LIB_VERSION "<text>"`, the number in decimal, without a '
                     'leading zero')
    return Version.of_number(int(number)), lib[1:-1]


def version_findings(root: Path, version: Version) -> list[str]:
    """What disagrees about the version: version.hpp's two macros, and the Jamroot's reading."""
    written, lib = read_version(root)
    findings = []
    if lib != written.lib:
        findings.append(f'{HEADER}: WEBCPP_VERSION names {written.name}, and WEBCPP_LIB_VERSION '
                        f'"{lib}" is not "{written.lib}"')
    if version != written:
        findings.append(f'the build read the version {version.name}, and {HEADER} names '
                        f'{written.name}')
    return findings


def git(directory: Path, *arguments: str) -> str:
    """What git prints in directory; a git that fails is Broken, naming the command."""
    completed = subprocess.run(['git', '-C', str(directory), *arguments], capture_output=True,
                               text=True, check=False)
    if completed.returncode != 0:
        raise Broken(f'git {" ".join(arguments)} in {directory}: {completed.stderr.strip()}')
    return completed.stdout


def libraries(root: Path) -> list[str]:
    """The libraries the build registers: each directory of libs/ with a build.jam."""
    return sorted(build.parent.name for build in (root / 'libs').glob('*/build.jam'))


def gitlinks(root: Path, revision: str) -> dict[str, str]:
    """The commit the superproject records at revision for each library, libs/<name>."""
    found = {}
    for entry in git(root, 'ls-tree', '-z', revision, 'libs/').split('\0'):
        if not entry:
            continue
        meta, path = entry.split('\t', 1)
        _, kind, commit = meta.split()
        if kind == 'commit':
            found[PurePosixPath(path).name] = commit
    return found


def previous_tag(root: Path, version: Version) -> str | None:
    """The tag of the newest version before version that HEAD holds, or None for a first
    release."""
    earlier = []
    for tag in git(root, 'tag', '--merged', 'HEAD', '--list', 'webcpp-*').split():
        match = TAG.fullmatch(tag)
        if match is not None and Version.parse(match.group(1)) < version:
            earlier.append(Version.parse(match.group(1)))
    return max(earlier).tag if earlier else None


def has_commit(root: Path, library: str, commit: str) -> bool:
    """Whether library's repository holds commit."""
    completed = subprocess.run(['git', '-C', str(root / 'libs' / library), 'cat-file', '-e',
                                f'{commit}^{{commit}}'], capture_output=True, check=False)
    return completed.returncode == 0


def changed(root: Path, library: str, old: str, new: str) -> bool:
    """Whether a user sees a change in library between the commits the superproject records at
    the previous tag, old, and at HEAD, new."""
    completed = subprocess.run(['git', '-C', str(root / 'libs' / library), 'diff', '--quiet',
                                old, new, '--', *USER_VISIBLE], capture_output=True, text=True,
                               check=False)
    if completed.returncode not in (0, 1):
        raise Broken(f'git diff in libs/{library}: {completed.stderr.strip()}')
    return completed.returncode == 1


def located(path: str, faults: list[changelog.Finding]) -> list[str]:
    """Faults of the file path as findings: <path>:<line>: <message>."""
    return [f'{path}:{line}: {message}' for line, message in faults]


def lines_of(regions: list[changelog.Region], tag: str) -> list[changelog.Bullet]:
    """The lines of the region tag, or none when there is no such region."""
    return next((region.bullets for region in regions if region.tag == tag), [])


def region_of(version: Version, notes: changelog.Notes) -> tuple[str, str]:
    """The tag of the region of each library's changelog the notes include, and its section's
    title: Unreleased while the version is in preparation, the version's own once frozen."""
    if notes.preparing:
        return 'unreleased', 'Unreleased'
    return version.name, f'webcpp {version.name}'


def is_checkout(root: Path, library: str) -> bool:
    """Whether libs/<library> is a git checkout of its own, rather than a directory whose git
    commands would reach the superproject's."""
    directory = root / 'libs' / library
    completed = subprocess.run(['git', '-C', str(directory), 'rev-parse', '--show-toplevel'],
                               capture_output=True, text=True, check=False)
    return completed.returncode == 0 and \
        Path(completed.stdout.strip()).resolve() == directory.resolve()


def uncommitted(directory: Path) -> list[str]:
    """The paths of directory's repository that its HEAD does not record as they are: changed,
    staged, deleted, or new and not ignored. A library's own changes are its repository's."""
    entries = git(directory, 'status', '--porcelain=v1', '-z', '--untracked-files=all',
                  '--ignore-submodules=all').split('\0')
    paths = []
    renamed = False
    for entry in entries:
        if renamed or not entry:
            renamed = False
            continue
        paths.append(entry[3:])
        # A rename or a copy is followed by the path it came from.
        renamed = entry[0] in 'RC'
    return paths


def uncommitted_findings(root: Path, current: list[str]) -> list[str]:
    """Each path of the superproject and of each library that HEAD does not record as it is."""
    paths = uncommitted(root)
    for name in current:
        if is_checkout(root, name):
            paths += [f'libs/{name}/{path}' for path in uncommitted(root / 'libs' / name)]
    return [f'{path} is not committed: a tag carries only what HEAD records'
            for path in sorted(paths)]


def index_findings(root: Path, version: Version) -> list[str]:
    """What the index's section Releases gets wrong: it includes every version's notes of
    doc/releases once, newest first, the version's first."""
    if not (root / 'doc/index.adoc').is_file():
        return ['doc/index.adoc does not exist']
    text = read(root, 'doc/index.adoc')
    section = RELEASES.search(text)
    if section is None:
        return ['doc/index.adoc has no section [#releases], == Releases']
    body = text[section.end():]
    following = re.search(r'^== ', body, re.MULTILINE)
    included = INCLUDED.findall(body[:following.start()] if following else body)
    names = [path.name for path in (root / 'doc/releases').iterdir()]
    findings = [f'doc/releases/{name} is no version\'s notes, <a.b.c>.adoc' for name in names
                if name.endswith('.adoc') and NOTES_FILE.fullmatch(name) is None]
    files = sorted((Version.parse(match.group(1)) for match in
                    (NOTES_FILE.fullmatch(name) for name in names) if match is not None),
                   reverse=True)
    if included != [each.name for each in files] or not files or files[0] != version:
        findings.append(f'doc/index.adoc: section Releases includes {", ".join(included)}, and '
                        f'it includes the notes of doc/releases newest first: '
                        f'{", ".join(each.name for each in files)}')
    return findings


def state_findings(root: Path, version: Version, notes: changelog.Notes,
                   logs: dict[str, list[changelog.Region]]) -> list[str]:
    """What breaks the state the notes give the version: in preparation, or frozen for its
    tag."""
    relative = version.notes
    wanted, _ = region_of(version, notes)
    state = 'in preparation' if notes.preparing else 'frozen'
    findings = [f'{relative}: {name} is included with tag={tag}, and the version is {state}: '
                f'tag={wanted}' for name, tag in notes.updated if tag != wanted]
    for name, regions in logs.items():
        if notes.preparing and version.name in {region.tag for region in regions}:
            findings.append(f'libs/{name}/doc/changelog.adoc has webcpp {version.name}, and '
                            f'{relative} says it is in preparation')
        if not notes.preparing and lines_of(regions, 'unreleased'):
            findings.append(f'libs/{name}/doc/changelog.adoc: Unreleased holds lines, and webcpp '
                            f'{version.name} is frozen')
    lanes = [changelog.notes_lane(lane.name) for lane in matrix.LANES]
    if notes.compilers is None:
        if not notes.preparing:
            findings.append(f'{relative}: Compilers tested is None., and the version is frozen')
    elif notes.compilers != lanes:
        findings.append(f'{relative}: Compilers tested lists {", ".join(notes.compilers)}, and '
                        f'the CI\'s lanes are {", ".join(lanes)}')
    if not notes.preparing:
        tagged = subprocess.run(['git', '-C', str(root), 'rev-parse', '-q', '--verify',
                                 f'refs/tags/{version.tag}^{{commit}}'], capture_output=True,
                                text=True, check=False)
        head = git(root, 'rev-parse', 'HEAD').strip()
        if tagged.returncode == 0 and tagged.stdout.strip() != head:
            findings.append(f'the tag {version.tag} is at {tagged.stdout.strip()}, and HEAD is '
                            f'{head}')
    return findings


def library_findings(root: Path, version: Version, notes: changelog.Notes,
                     logs: dict[str, list[changelog.Region]], current: list[str]) -> list[str]:
    """What the libraries get wrong: each recorded at its checked-out commit; New and Removed
    Libraries exactly those new or gone since the previous tag; and every library changed since,
    or with lines for this version, under Updated Libraries with its lines."""
    relative = version.notes
    wanted, region = region_of(version, notes)
    previous = previous_tag(root, version)
    since = previous or 'the first version'
    before = gitlinks(root, previous) if previous else {}
    head = gitlinks(root, 'HEAD')
    findings = []
    # A submodule that is not checked out holds no build.jam, and is not gone: it is named, and
    # counted as present.
    absent = sorted(set(head) - set(current))
    findings += [f'libs/{name} is a submodule of the superproject at HEAD, and is not checked '
                 f'out: git submodule update --init libs/{name}' for name in absent]
    checkouts = [name for name in current if is_checkout(root, name)]
    findings += [f'libs/{name} is no git checkout of its own: a library is a repository, '
                 'recorded by the superproject' for name in current if name not in checkouts]
    for name in checkouts:
        if name not in head:
            findings.append(f'libs/{name} is no submodule of the superproject at HEAD: a release '
                            'ships only what its tag records')
            continue
        checked_out = git(root / 'libs' / name, 'rev-parse', 'HEAD').strip()
        if checked_out != head[name]:
            findings.append(f'libs/{name} is at {checked_out}, and the superproject records '
                            f'{head[name]}')
    present = set(current) | set(absent)
    new = sorted(present - set(before))
    removed = sorted(set(before) - present)
    listed_new = [name for name, _ in notes.new]
    listed_removed = [name for name, _ in notes.removed]
    if listed_new != new:
        findings.append(f'{relative}: New Libraries lists {", ".join(listed_new) or "none"}, and '
                        f'the libraries new since {since} are {", ".join(new) or "none"}')
    if listed_removed != removed:
        findings.append(f'{relative}: Removed Libraries lists '
                        f'{", ".join(listed_removed) or "none"}, and the libraries gone since '
                        f'{since} are {", ".join(removed) or "none"}')
    updated = [name for name, _ in notes.updated]
    for name in updated:
        if name in new or name in removed:
            findings.append(f'{relative}: {name} is under Updated Libraries, and is '
                            f'{"new" if name in new else "removed"} since {since}')
        elif name not in present:
            findings.append(f'{relative}: {name} is under Updated Libraries, and is no library '
                            'of libs/')
        elif not lines_of(logs.get(name, []), wanted):
            findings.append(f'{relative}: {name} is under Updated Libraries, and its region '
                            f'{wanted} holds no line')
    for name in sorted(set(checkouts) & set(before)):
        lines = lines_of(logs.get(name, []), wanted)
        if lines and name not in updated:
            findings.append(f'the release notes miss {name}, whose changelog has lines for this '
                            'version')
        if lines or name not in head:
            continue
        if not has_commit(root, name, before[name]):
            findings.append(f'libs/{name}: the commit {previous} records, {before[name]}, is not '
                            'in its repository; fetch its tags')
        elif not has_commit(root, name, head[name]):
            findings.append(f'libs/{name}: the commit HEAD records, {head[name]}, is not in its '
                            'repository')
        elif changed(root, name, before[name], head[name]):
            findings.append(f'libs/{name} changed since {previous} and its {region} has no line')
    return findings


def check(root: Path, version: Version) -> list[str]:
    """Every fault that keeps the tree from being tagged webcpp-<version>; a change HEAD does
    not record is named first, and alone, since every other rule judges what the tag carries."""
    current = libraries(root)
    findings = uncommitted_findings(root, current)
    if findings:
        return findings
    findings = version_findings(root, version)
    relative = version.notes
    if not (root / relative).is_file():
        return findings + [f'{relative} does not exist: open it from '
                           'tools/release/template.adoc']
    text = read(root, relative)
    notes, faults = changelog.parse_notes(text, version.name)
    findings += located(relative, sorted(faults + [fault for bullet in notes.tools
                                                   for fault in changelog.line_findings(bullet)]))
    findings += index_findings(root, version)
    logs: dict[str, list[changelog.Region]] = {}
    for name in current:
        path = f'libs/{name}/doc/changelog.adoc'
        if not (root / path).is_file():
            findings.append(f'{path} does not exist')
            continue
        log = read(root, path)
        findings += located(path, changelog.changelog_findings(log, name))
        logs[name] = changelog.parse_changelog(log, name)[0]
    findings += state_findings(root, version, notes, logs)
    findings += library_findings(root, version, notes, logs, current)
    return findings


# A command: given the superproject, the version and its arguments, it returns the faults that
# stop it, and prints what it writes.
Command = Callable[[Path, Version, argparse.Namespace], list[str]]

COMMANDS: dict[str, Command] = {
    'check': lambda root, version, _: check(root, version),
}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='release.py', description="webcpp's release tooling")
    commands = parser.add_subparsers(dest='command', required=True)
    for name in COMMANDS:
        command = commands.add_parser(name)
        command.add_argument('--root', type=Path, required=True)
        command.add_argument('--version', required=True)
    arguments = parser.parse_args(argv)
    try:
        version = Version.parse(arguments.version)
        findings = COMMANDS[arguments.command](arguments.root.resolve(), version, arguments)
    except Failure as failure:
        findings = str(failure).split('\n')
    except Broken as broken:
        print(f'{arguments.command}: {broken}', file=sys.stderr)
        return 2
    for finding in findings:
        print(f'{arguments.command}: {finding}')
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
