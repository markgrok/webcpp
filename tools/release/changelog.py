#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""The form of webcpp's changelog files (AGENTS.md chapter 11), which tools/lint/rules.py reads
on every lint run and tools/release/release.py before a release.

A library's changelog, libs/<name>/doc/changelog.adoc, after its notice: [appendix],
[#<name>-changelog] and == Changelog, its paragraphs, then the section Unreleased,
[#<name>-changelog-unreleased] and === Unreleased, its lines between // tag::unreleased[] and
// end::unreleased[], then each released version, newest first, [#<name>-changelog-<a-b-c>],
=== webcpp <a.b.c> and its region <a.b.c>.

A version's release notes, doc/releases/<a.b.c>.adoc: [#webcpp-<a-b-c>] and = webcpp <a.b.c>,
the paragraph IN_PREPARATION while the version is in preparation, then SECTIONS, each
[#webcpp-<a-b-c>-<slug>] and == <title>, each holding its entries in alphabetical order, or the
paragraph None.

A line is a bullet: "* " at the start of a line, then the lines after it up to a blank line,
the next bullet or the region's end, which continue it. It starts with one of VERBS, or with
"*Breaking change:* " and then one of VERBS, whose first letter may be lower case, and holds no
cross-reference, <<...>> or xref:, since the index page shows it too. A library's version holds
at most MOST of them; the sections of release notes have no such limit. Outside its regions, a
library's changelog holds no text after its first section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

VERBS = ('Added', 'Changed', 'Deprecated', 'Fixed', 'Improved', 'Removed', 'Updated')
BREAKING = '*Breaking change:* '
MOST = 10
NONE = 'None.'
IN_PREPARATION = ["In preparation: no tag names this version yet, and its libraries' entries",
                  'are their changelogs\' "Unreleased" sections.']
SECTIONS = (('new-libraries', 'New Libraries'), ('updated-libraries', 'Updated Libraries'),
            ('removed-libraries', 'Removed Libraries'), ('tools-and-build', 'Tools and build'),
            ('compilers-tested', 'Compilers tested'))

ANCHOR = re.compile(r'\[#([\w-]+)\]')
REGION_START = re.compile(r'// tag::([\w.]+)\[\]')
REGION_END = re.compile(r'// end::([\w.]+)\[\]')
RELEASED = re.compile(r'webcpp (\d+\.\d+\.\d+)')
NAME = r'[a-z][a-z0-9_]*'
NEW = re.compile(r'link:\{library-pages\}(?P<name>' + NAME + r')/\{library-page\}\[(?P=name)\]: '
                 r'(?P<what>.+, from .+\.)')
REMOVED = re.compile(r'(?P<name>' + NAME + r'): (?P<what>.+\.)')
UPDATED = re.compile(r'\[#webcpp-(?P<anchor>[\d-]+)-(?P<name>' + NAME + r')\]\n'
                     r'=== link:\{library-pages\}(?P=name)/\{library-page\}\[(?P=name)\]\n\n'
                     r'include::\{webcpp-root\}/libs/(?P=name)/doc/changelog\.adoc'
                     r'\[tag=(?P<tag>[\w.]+)\]')

Finding = tuple[int, str]


@dataclass
class Bullet:
    """A line of a changelog: the line its bullet starts on, and its text without the "* ", its
    lines joined by single spaces."""

    line: int
    text: str


@dataclass
class Region:
    """A section of a library's changelog, Unreleased or a version: its title, its region's tag,
    the line of its title, and its lines."""

    title: str
    tag: str
    line: int
    bullets: list[Bullet]


@dataclass
class Notes:
    """A version's release notes as their sections list them: whether the version is in
    preparation; each new and removed library with its text; each updated library with the tag
    its include names; the lines of Tools and build; the lanes of Compilers tested, None for
    None."""

    preparing: bool = False
    new: list[tuple[str, str]] = field(default_factory=list)
    updated: list[tuple[str, str]] = field(default_factory=list)
    removed: list[tuple[str, str]] = field(default_factory=list)
    tools: list[Bullet] = field(default_factory=list)
    compilers: list[str] | None = None


def bullets(lines: list[str], first: int) -> tuple[list[Bullet], list[Finding]]:
    """The bullets of lines, the first of which is the file's line first, and each line that
    belongs to none."""
    found: list[Bullet] = []
    findings: list[Finding] = []
    open_bullet = False
    for number, line in enumerate(lines, first):
        if line.startswith('* '):
            found.append(Bullet(number, line[2:].strip()))
            open_bullet = True
        elif not line.strip():
            open_bullet = False
        elif open_bullet:
            found[-1].text += ' ' + line.strip()
        else:
            findings.append((number, f'not a line of a changelog, which starts with "* ": {line}'))
    return found, findings


def line_findings(bullet: Bullet) -> list[Finding]:
    """What breaks a line's form."""
    findings: list[Finding] = []
    if bullet.text.startswith(BREAKING):
        verb = bullet.text[len(BREAKING):].split(' ', 1)[0]
        if verb[:1].upper() + verb[1:] not in VERBS:
            findings.append((bullet.line, f'after {BREAKING.strip()}, a line goes on with one of '
                                          f'{", ".join(VERBS)}: {bullet.text}'))
    elif bullet.text.split(' ', 1)[0] not in VERBS:
        findings.append((bullet.line, f'a line starts with {BREAKING.strip()} or one of '
                                      f'{", ".join(VERBS)}: {bullet.text}'))
    if '<<' in bullet.text or 'xref:' in bullet.text:
        findings.append((bullet.line, 'a line holds no cross-reference, <<...>>: the index page '
                                      'shows it too'))
    return findings


def read_region(lines: list[str], index: int) -> tuple[str | None, int, int, list[Finding]]:
    """The region that starts at lines[index], after blank lines: its tag, the index of its
    first line and of its end line, and what is wrong with it."""
    while index < len(lines) and not lines[index].strip():
        index += 1
    start = REGION_START.fullmatch(lines[index]) if index < len(lines) else None
    if start is None:
        return None, index, index, [(index + 1, 'a section holds its lines between '
                                                '// tag::<name>[] and // end::<name>[]')]
    tag = start.group(1)
    for end in range(index + 1, len(lines)):
        if REGION_END.fullmatch(lines[end]) or REGION_START.fullmatch(lines[end]):
            if lines[end] == f'// end::{tag}[]':
                return tag, index + 1, end, []
            break
    return tag, index + 1, index + 1, [(index + 1, f'the region {tag} has no // end::{tag}[]')]


def expected(library: str, title: str) -> tuple[str, str] | None:
    """The anchor and the tag of a library's section titled title, or None for no section's
    title."""
    if title == 'Unreleased':
        return f'{library}-changelog-unreleased', 'unreleased'
    released = RELEASED.fullmatch(title)
    if released is None:
        return None
    return f'{library}-changelog-{released.group(1).replace(".", "-")}', released.group(1)


def parse_changelog(text: str, library: str) -> tuple[list[Region], list[Finding]]:
    """The sections of a library's changelog, and what breaks its form."""
    lines = text.split('\n')
    head = ['[appendix]', f'[#{library}-changelog]', '== Changelog']
    start = next((index for index in range(len(lines)) if lines[index:index + 3] == head), None)
    if start is None:
        return [], [(1, 'a changelog opens, after its notice, with ' + ', '.join(head))]
    found: list[Region] = []
    findings: list[Finding] = []
    index = start + 3
    sections = False
    while index < len(lines):
        anchor = ANCHOR.fullmatch(lines[index])
        if anchor is None or index + 1 == len(lines) or not lines[index + 1].startswith('=== '):
            if lines[index].startswith('='):
                findings.append((index + 1, 'a section of a changelog is [#<anchor>] and '
                                            f'=== <title>: {lines[index]}'))
            elif sections and lines[index].strip():
                findings.append((index + 1, 'a changelog holds its lines inside the regions of '
                                            f'its sections: {lines[index]}'))
            index += 1
            continue
        sections = True
        title = lines[index + 1][4:]
        want = expected(library, title)
        if want is None:
            findings.append((index + 2, f'a section is Unreleased or webcpp <a.b.c>: {title}'))
        elif anchor.group(1) != want[0]:
            findings.append((index + 1, f'the section {title} is [#{want[0]}]'))
        tag, first, end, faults = read_region(lines, index + 2)
        findings += faults
        if tag is None:
            index += 2
            continue
        if want is not None and tag != want[1]:
            findings.append((first, f'the region of {title} is {want[1]}'))
        body, body_faults = bullets(lines[first:end], first + 1)
        findings += body_faults
        found.append(Region(title, tag, index + 2, body))
        index = end + 1
    titles = [region.title for region in found]
    if not titles or titles[0] != 'Unreleased' or titles.count('Unreleased') != 1:
        findings.append((start + 1, 'a changelog has one section "Unreleased", first'))
    versions = [tuple(int(number) for number in region.tag.split('.')) for region in found
                if RELEASED.fullmatch(region.title) and RELEASED.fullmatch(f'webcpp {region.tag}')]
    if versions != sorted(set(versions), reverse=True):
        findings.append((start + 1, 'the versions of a changelog come newest first, each once'))
    return found, findings


def changelog_findings(text: str, library: str) -> list[Finding]:
    """What breaks the form of a library's changelog and of each of its lines, by line."""
    regions, findings = parse_changelog(text, library)
    for region in regions:
        for bullet in region.bullets:
            findings += line_findings(bullet)
        if len(region.bullets) > MOST:
            findings.append((region.line, f'{region.title} holds {len(region.bullets)} lines, '
                                          f'and a library holds at most {MOST} per version'))
    return sorted(findings)


def parse_notes(text: str, version: str) -> tuple[Notes, list[Finding]]:
    """A version's release notes, and what breaks their form."""
    anchor = version.replace('.', '-')
    lines = text.split('\n')
    notes = Notes()
    title = next((index for index, line in enumerate(lines) if line.startswith('= ')), None)
    if title is None or title == 0 or \
            lines[title - 1:title + 1] != [f'[#webcpp-{anchor}]', f'= webcpp {version}']:
        return notes, [(1 if title is None else title + 1,
                        f'release notes open with [#webcpp-{anchor}] and = webcpp {version}')]
    heads: list[tuple[int, str, str]] = []
    for index in range(title + 1, len(lines) - 1):
        match = ANCHOR.fullmatch(lines[index])
        if match is not None and lines[index + 1].startswith('== '):
            heads.append((index, match.group(1), lines[index + 1][3:]))
    want = [(f'webcpp-{anchor}-{slug}', name) for slug, name in SECTIONS]
    if [(found, name) for _, found, name in heads] != want:
        return notes, [(title + 1, 'release notes hold five sections, in order: '
                                   + ', '.join(f'[#{found}] == {name}' for found, name in want))]
    findings: list[Finding] = []
    preamble = [line for line in lines[title + 1:heads[0][0]] if line.strip()]
    notes.preparing = preamble == IN_PREPARATION
    if preamble and not notes.preparing:
        findings.append((title + 2, 'between the title and New Libraries, release notes hold the '
                                    'paragraph "In preparation: ..." or nothing'))
    bodies: dict[str, tuple[int, list[str]]] = {}
    for position, (index, found, _) in enumerate(heads):
        end = heads[position + 1][0] if position + 1 < len(heads) else len(lines)
        bodies[found.removeprefix(f'webcpp-{anchor}-')] = (index + 3, lines[index + 2:end])

    def is_none(slug: str) -> bool:
        return [line for line in bodies[slug][1] if line.strip()] == [NONE]

    def listed(slug: str, pattern: re.Pattern[str]) -> list[tuple[str, str]]:
        if is_none(slug):
            return []
        items, faults = bullets(bodies[slug][1], bodies[slug][0])
        findings.extend(faults)
        entries = []
        for item in items:
            match = pattern.fullmatch(item.text)
            if match is None:
                findings.append((item.line, f'not a line of {slug}: {item.text}'))
            else:
                entries.append((match.group('name'), match.group('what')))
        return entries

    notes.new = listed('new-libraries', NEW)
    notes.removed = listed('removed-libraries', REMOVED)
    first, body = bodies['updated-libraries']
    block = '\n'.join(body).strip()
    if block != NONE:
        position = 0
        for match in UPDATED.finditer(block):
            if block[position:match.start()].strip() or match.group('anchor') != anchor:
                break
            notes.updated.append((match.group('name'), match.group('tag')))
            position = match.end()
        if block[position:].strip() or not notes.updated:
            findings.append((first, f'Updated Libraries holds, for each library, '
                                    f'[#webcpp-{anchor}-<name>], === link:{{library-pages}}'
                                    '<name>/{library-page}[<name>] and the include of its '
                                    'changelog\'s region, or None.'))
    if not is_none('tools-and-build'):
        notes.tools, faults = bullets(bodies['tools-and-build'][1], bodies['tools-and-build'][0])
        findings += faults
    if not is_none('compilers-tested'):
        lanes, faults = bullets(bodies['compilers-tested'][1], bodies['compilers-tested'][0])
        findings += faults
        notes.compilers = [lane.text for lane in lanes]
    for slug, names in (('new-libraries', [name for name, _ in notes.new]),
                        ('updated-libraries', [name for name, _ in notes.updated]),
                        ('removed-libraries', [name for name, _ in notes.removed])):
        if names != sorted(names):
            findings.append((bodies[slug][0], f'{slug} lists its libraries in alphabetical order'))
    return notes, findings


def notes_findings(text: str, version: str) -> list[Finding]:
    """What breaks the form of a version's release notes and of each line of Tools and build,
    by line."""
    notes, findings = parse_notes(text, version)
    for bullet in notes.tools:
        findings += line_findings(bullet)
    return sorted(findings)


def file_findings(path: str, text: str) -> list[Finding]:
    """What breaks the form of a changelog file, by its path in the superproject: a library's
    changelog, libs/<name>/doc/changelog.adoc, or a version's release notes,
    doc/releases/<a.b.c>.adoc; nothing for any other file."""
    parts = PurePosixPath(path).parts
    if len(parts) == 4 and parts[0] == 'libs' and parts[2:] == ('doc', 'changelog.adoc'):
        return changelog_findings(text, parts[1])
    if len(parts) == 3 and parts[:2] == ('doc', 'releases'):
        release = re.fullmatch(r'(\d+\.\d+\.\d+)\.adoc', parts[2])
        if release is not None:
            return notes_findings(text, release.group(1))
    return []
