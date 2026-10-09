#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/release/changelog.py: a library's changelog and a version's release notes in
AGENTS.md chapter 11's form pass, wrapped lines included; a line with no verb of the list, a
cross-reference, an eleventh line, text outside a bullet, a section out of order or without its
region, and notes out of form each fail, at their line. The reader reads a list as the doc
build's Asciidoctor.js renders it, which tools/node/install.py installs when it is not there.
Run with the names of some cases to run only those."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path

import changelog

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'tools/doc'
sys.path.insert(0, str(ROOT / 'tools/ci'))
import matrix  # noqa: E402  (tools/ci, put on the path above: its LANES are the CI's lanes)

VERB_LIST = 'Added, Changed, Deprecated, Fixed, Improved, Removed, Updated'
CROSS_REFERENCE = ('a line holds no cross-reference, <<...>>, xref: or link:#: the index page '
                   'shows it too')
NESTED = ('a line of a changelog is a bullet at the margin, "* ", with no nested list, block, '
          'attribute or directive: ')


def log(name: str, *sections: tuple[str, list[str]]) -> str:
    """A library's changelog: each section a title, Unreleased or webcpp <a.b.c>, and its lines,
    each line of the file as written."""
    text = f'// The notice.\n\n[appendix]\n[#{name}-changelog]\n== Changelog\n\nWhat changed.\n'
    for title, lines in sections:
        tag = 'unreleased' if title == 'Unreleased' else title.removeprefix('webcpp ')
        body = ''.join(f'{line}\n' for line in lines)
        text += (f'\n[#{name}-changelog-{tag.replace(".", "-")}]\n=== {title}\n\n'
                 f'// tag::{tag}[]\n{body}// end::{tag}[]\n')
    return text


def line_of(text: str, line: str) -> int:
    """The number of the line of text that is line, which must be there once."""
    numbers = [number for number, held in enumerate(text.split('\n'), 1) if held == line]
    assert len(numbers) == 1, (line, numbers)
    return numbers[0]


def test_a_changelog_in_form_passes() -> None:
    text = log('alpha', ('Unreleased', ['* Added a line that wraps', 'onto the next one.',
                                        '* *Breaking change:* removed `x`; use `y`.']),
               ('webcpp 0.1.0', ['* Fixed a crash.']))
    assert changelog.changelog_findings(text, 'alpha') == []
    regions, _ = changelog.parse_changelog(text, 'alpha')
    assert [(region.title, region.tag) for region in regions] == [
        ('Unreleased', 'unreleased'), ('webcpp 0.1.0', '0.1.0')]
    assert regions[0].bullets[0].text == 'Added a line that wraps onto the next one.'


def test_wrapped_lines_are_one_bullet() -> None:
    # A continuation that starts with a verb of the list is no bullet of its own; a bullet that
    # starts with none fails once, at the line it starts on.
    text = log('alpha', ('Unreleased', ['* Added a line whose next line', 'Added nothing.',
                                        '* Made a mistake that wraps', 'onto the next one.']))
    assert changelog.changelog_findings(text, 'alpha') == [
        (line_of(text, '* Made a mistake that wraps'),
         'a line starts with *Breaking change:* or one of Added, Changed, Deprecated, Fixed, '
         'Improved, Removed, Updated: Made a mistake that wraps onto the next one.')]


def test_a_list_inside_a_bullet_fails() -> None:
    # Asciidoctor renders an indented "* " as a bullet of its own, which is then checked; a
    # nested list, a block, an attribute line or a directive is no part of a changelog's form.
    # A comment is dropped, and the bullet goes on after it.
    sibling = ['* Added a line.', '  * Made an indented line.']
    found, faults = changelog.bullets(sibling, 1)
    assert faults == [] and [bullet.text for bullet in found] == ['Added a line.',
                                                                  'Made an indented line.']
    found, faults = changelog.bullets(['* Added a line.', '// A comment.', 'Added more.'], 1)
    assert faults == [] and [bullet.text for bullet in found] == ['Added a line. Added more.']
    for nested in ('** Made a nested line.', '- Made a dash line.', '. Made an ordered line.',
                   '1. Made a numbered line.', 'term:: Made a description.', '+', '----',
                   '[source]', 'include::other.adoc[]'):
        found, faults = changelog.bullets(['* Added a line.', nested, 'Added more.'], 1)
        assert faults == [(2, NESTED + nested)], (nested, faults)
        assert [bullet.text for bullet in found] == ['Added a line.'], (nested, found)
    text = log('alpha', ('Unreleased', ['* Added a line.', '** Made a nested line.']))
    assert changelog.changelog_findings(text, 'alpha') == [
        (line_of(text, '** Made a nested line.'), NESTED + '** Made a nested line.')]


# Each case is the lines after "* Added x." and before "Added the end.", in a region. Where a
# case holds markup, a code span's backticks, its two texts differ by that markup alone.
LIST_CASES = [
    ['* Added y.'], ['', '* Added y.'], ['  * Made an indented item.'], ['\t* Made a tabbed one.'],
    ['*  Added two spaces.'], ['Added nothing.'], ['  indented text.'], ['.Title'],
    [':attr: value'], ['use `std::` here.'], ['a::b in text.'], ['[x] box'], ['// a comment'],
    ['// a comment', '* Added y.'], ['** Made a nested item.'], ['  ** Made an indented one.'],
    ['- Made a dash item.'], ['. Made an ordered item.'], ['1. Made a numbered item.'],
    ['a. Made a lettered item.'], ['i) Made a roman item.'], ['<1> Made a callout.'],
    ['term:: Made a description.'], ['use std:: here.'], ['x;; y'], ['ends with ::'],
    ['+', 'Made an attached paragraph.'], ['////', 'c', '////'], ['----', 'code', '----'],
    ['....', 'literal', '....'], ['====', 'example', '===='], ['****', 'sidebar', '****'],
    ['____', 'quote', '____'], ['++++', 'pass', '++++'], ['|===', '|a', '|==='],
    ['--', 'open', '--'],
    ['[source]'], ["'''"], ['<<<'], ['```', 'fenced', '```'],
    ['', 'A paragraph.'], ['', '  A literal.'],
]


class Node:
    """An element of rendered HTML: its tag, its attributes, and its children, elements and
    text."""

    def __init__(self, tag: str, attributes: dict[str, str | None]) -> None:
        self.tag = tag
        self.attributes = attributes
        self.kind = attributes.get('class') or ''
        self.children: list[Node | str] = []

    def elements(self) -> list[Node]:
        return [child for child in self.children if isinstance(child, Node)]

    def text(self) -> str:
        return ''.join(child if isinstance(child, str) else child.text()
                       for child in self.children)

    def links_into_the_page(self) -> list[str]:
        """The targets of the links this element holds, at any depth, into its own page."""
        own = [self.attributes.get('href') or ''] if self.tag == 'a' else []
        return [target for target in own if target.startswith('#')] + [
            target for child in self.elements() for target in child.links_into_the_page()]


class Tree(HTMLParser):
    """The tree of elements of an HTML text."""

    VOID = {'br', 'col', 'hr', 'img', 'input', 'link', 'meta'}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node('root', {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        while len(self.stack) > 1 and self.stack.pop().tag != tag:
            pass

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def asciidoctor(text: str) -> Node:
    """The tree of what the doc build's Asciidoctor.js renders of text, embedded."""
    program = DOC / 'node_modules/asciidoctor/bin/asciidoctor'
    if not program.exists():
        subprocess.run([sys.executable, str(ROOT / 'tools/node/install.py'), str(DOC)],
                       check=True)
    html = subprocess.run([str(program), '-s', '-o', '-', '-'], input=text, capture_output=True,
                          text=True, check=True).stdout
    tree = Tree()
    tree.feed(html)
    return tree.root


def flat_items(body: Node) -> list[str] | None:
    """The texts of the items of body when it holds one bulleted list, each of whose items is
    one paragraph, its words single-spaced; None for anything else."""
    blocks = body.elements()
    if len(blocks) != 1 or blocks[0].kind != 'ulist':
        return None
    texts = []
    for item in blocks[0].elements()[0].elements():
        parts = item.elements()
        if len(parts) != 1 or parts[0].tag != 'p':
            return None
        texts.append(' '.join(parts[0].text().split()))
    return texts


def test_the_reader_reads_a_list_as_asciidoctor_does() -> None:
    # Where Asciidoctor renders one flat list, the reader reads its items, with the same texts;
    # where it renders anything else, the reader fails.
    cases = [['* Added x.', *case, 'Added the end.'] for case in LIST_CASES]
    document = ''.join(f'== Case {number}\n\n' + '\n'.join(lines) + '\n\n'
                       for number, lines in enumerate(cases))
    sections = [section for section in asciidoctor(document).elements() if section.kind == 'sect1']
    assert len(sections) == len(cases), len(sections)
    for lines, section in zip(cases, sections):
        rendered = flat_items(section.elements()[1])
        found, faults = changelog.bullets(lines, 1)
        if rendered is None:
            assert faults, (lines, 'Asciidoctor renders more than a flat list')
        else:
            read = [' '.join(bullet.text.replace('`', '').split()) for bullet in found]
            assert faults == [] and read == rendered, (lines, read, rendered, faults)


def test_eleven_wrapped_lines_fail() -> None:
    lines = [part for number in range(11) for part in (f'* Added line {number}', 'wrapped.')]
    text = log('alpha', ('Unreleased', lines))
    found = changelog.changelog_findings(text, 'alpha')
    assert found == [(line_of(text, '=== Unreleased'),
                      'Unreleased holds 11 lines, and a library holds at most 10 per version')]
    assert changelog.changelog_findings(log('alpha', ('Unreleased', lines[:20])), 'alpha') == []


def test_a_line_holds_at_most_thirty_words() -> None:
    thirty = '* Added ' + ' '.join(['word'] * 28) + '\nend.'
    assert changelog.changelog_findings(log('alpha', ('Unreleased', [thirty])), 'alpha') == []
    text = log('alpha', ('Unreleased', [thirty.replace('end.', 'one more.')]))
    assert changelog.changelog_findings(text, 'alpha') == [
        (line_of(text, '* Added ' + ' '.join(['word'] * 28)),
         'a line holds at most 30 words, and this one holds 31: Added '
         + ' '.join(['word'] * 28) + ' one more.')]


def test_text_outside_a_bullet_and_a_cross_reference_fail() -> None:
    text = log('alpha', ('Unreleased', ['* Added <<alpha-intro>>.', '', 'A paragraph.']))
    assert changelog.changelog_findings(text, 'alpha') == [
        (line_of(text, '* Added <<alpha-intro>>.'), CROSS_REFERENCE),
        (line_of(text, 'A paragraph.'), 'not a line of a changelog, which starts with "* ": '
                                        'A paragraph.')]


def test_a_breaking_change_goes_on_with_a_verb() -> None:
    # *Breaking change:* comes first and before the verb, whose first letter may then be lower
    # case.
    text = log('alpha', ('Unreleased', ['* *Breaking change:* Removed `x`.',
                                        '* *Breaking change:* `x` is gone.',
                                        '* Changed `y`; *Breaking change:* removed `x`.']))
    assert changelog.changelog_findings(text, 'alpha') == [
        (line_of(text, '* *Breaking change:* `x` is gone.'),
         f'after *Breaking change:*, a line goes on with one of {VERB_LIST}: '
         '*Breaking change:* `x` is gone.'),
        (line_of(text, '* Changed `y`; *Breaking change:* removed `x`.'),
         '*Breaking change:* comes first in a line: Changed `y`; *Breaking change:* removed '
         '`x`.')]


def test_cross_references_as_asciidoctor_reads_them() -> None:
    # A cross-reference is one where Asciidoctor renders a link into the page, in a code span
    # too; operator<< and a passthrough, +...+, are code.
    linked = ['* Added xref:alpha-intro[the introduction].', '* Added `<<alpha-intro>>`.',
              '* Added <<#alpha-intro,the introduction>>.', '* Added link:#alpha-intro[it].',
              '* Added `xref:alpha-intro[it]` in code.']
    plain = ['* Added `operator<<` and `operator>>` for `x`.', '* Added `+a<<b>>+`.',
             '* Added a shift, `a << b`, and `a >> b`.', '* Added `std::vector<std::byte>`.']
    rendered = asciidoctor(''.join(f'== Case {number}\n\n{line}\n\n'
                                   for number, line in enumerate(linked + plain)))
    sections = [section for section in rendered.elements() if section.kind == 'sect1']
    for line, section in zip(linked + plain, sections):
        assert bool(section.elements()[1].links_into_the_page()) == (line in linked), line
        text = log('alpha', ('Unreleased', [line]))
        expected = [(line_of(text, line), CROSS_REFERENCE)] if line in linked else []
        assert changelog.changelog_findings(text, 'alpha') == expected, line


def test_text_outside_every_region_fails() -> None:
    # A line after a region's end shows on the page, but no release note includes it; so does a
    # bullet among the opening paragraphs. Before [appendix], only the notice may come.
    text = log('alpha', ('Unreleased', ['* Added a line.']), ('webcpp 0.1.0', [])).replace(
        '// end::unreleased[]\n', '// end::unreleased[]\n* Added a stray line.\n')
    assert changelog.changelog_findings(text, 'alpha') == [
        (line_of(text, '* Added a stray line.'),
         'a changelog holds its lines inside the regions of its sections: * Added a stray '
         'line.')]
    paragraph = text.replace('* Added a stray line.', 'A stray paragraph.')
    assert changelog.changelog_findings(paragraph, 'alpha') == [
        (line_of(paragraph, 'A stray paragraph.'),
         'a changelog holds its lines inside the regions of its sections: A stray paragraph.')]
    early = log('alpha', ('Unreleased', [])).replace('What changed.\n',
                                                     'What changed.\n\n* Added an early line.\n')
    assert changelog.changelog_findings(early, 'alpha') == [
        (line_of(early, '* Added an early line.'),
         'a changelog holds its lines inside the regions of its sections: * Added an early '
         'line.')]
    first = 'A first paragraph.\n' + log('alpha', ('Unreleased', []))
    assert changelog.changelog_findings(first, 'alpha') == [
        (1, 'a changelog holds nothing but its notice before [appendix]: A first paragraph.')]


def test_sections_in_order_each_with_its_region() -> None:
    late = log('alpha', ('webcpp 0.1.0', []), ('Unreleased', []))
    assert (line_of(late, '[appendix]'), 'a changelog has one section "Unreleased", first') in \
        changelog.changelog_findings(late, 'alpha')
    old = log('alpha', ('Unreleased', []), ('webcpp 0.1.0', []), ('webcpp 0.2.0', []))
    assert (line_of(old, '[appendix]'),
            'the versions of a changelog come newest first, each once') in \
        changelog.changelog_findings(old, 'alpha')
    open_region = log('alpha', ('Unreleased', ['* Added a line.'])).replace(
        '// end::unreleased[]\n', '')
    assert (line_of(open_region, '// tag::unreleased[]'),
            'the region unreleased has no // end::unreleased[]') in \
        changelog.changelog_findings(open_region, 'alpha')
    headless = '[appendix]\n[#other-changelog]\n== Changelog\n'
    assert changelog.changelog_findings(headless, 'alpha') == [
        (1, 'a changelog opens, after its notice, with [appendix], [#alpha-changelog], '
            '== Changelog')]


def test_each_section_named_as_its_title() -> None:
    good = log('alpha', ('Unreleased', ['* Added a line.']), ('webcpp 0.1.0', []))
    tag = good.replace('// tag::0.1.0[]\n// end::0.1.0[]', '// tag::0.2.0[]\n// end::0.2.0[]')
    assert changelog.changelog_findings(tag, 'alpha') == [
        (line_of(tag, '// tag::0.2.0[]'), 'the region of webcpp 0.1.0 is 0.1.0')]
    anchor = good.replace('[#alpha-changelog-0-1-0]', '[#alpha-changelog-0-2-0]')
    assert changelog.changelog_findings(anchor, 'alpha') == [
        (line_of(anchor, '[#alpha-changelog-0-2-0]'),
         'the section webcpp 0.1.0 is [#alpha-changelog-0-1-0]')]
    title = good.replace('=== webcpp 0.1.0', '=== Version 0.1.0')
    assert changelog.changelog_findings(title, 'alpha') == [
        (line_of(title, '=== Version 0.1.0'),
         'a section is Unreleased or webcpp <a.b.c>: Version 0.1.0')]
    twice = log('alpha', ('Unreleased', []), ('Unreleased', []))
    assert changelog.changelog_findings(twice, 'alpha') == [
        (line_of(twice, '[appendix]'), 'a changelog has one section "Unreleased", first')]
    unended = good.replace('// end::unreleased[]\n', '')
    assert changelog.changelog_findings(unended, 'alpha') == [
        (line_of(unended, '// tag::unreleased[]'), 'the region unreleased has no '
                                                   '// end::unreleased[]')]
    assert [region.title for region in changelog.parse_changelog(unended, 'alpha')[0]] == [
        'Unreleased', 'webcpp 0.1.0']
    other = good.replace('// end::unreleased[]', '// end::other[]')
    assert changelog.changelog_findings(other, 'alpha') == [
        (line_of(other, '// tag::unreleased[]'), 'the region unreleased has no '
                                                 '// end::unreleased[]')]


def notes(*, preparing: bool = True, new: str = 'None.', updated: str = 'None.',
          removed: str = 'None.', tools: str = 'None.', compilers: str = 'None.') -> str:
    """Release notes of 0.2.0, each section's body as given."""
    text = '// The notice.\n\n[#webcpp-0-2-0]\n= webcpp 0.2.0\n'
    if preparing:
        text += '\n' + '\n'.join(changelog.IN_PREPARATION) + '\n'
    for slug, title, body in (('new-libraries', 'New Libraries', new),
                              ('updated-libraries', 'Updated Libraries', updated),
                              ('removed-libraries', 'Removed Libraries', removed),
                              ('tools-and-build', 'Tools and build', tools),
                              ('compilers-tested', 'Compilers tested', compilers)):
        text += f'\n[#webcpp-0-2-0-{slug}]\n== {title}\n\n{body}\n'
    return text


def updated_entry(name: str, anchor: str = '0-2-0') -> str:
    """An entry of Updated Libraries: the library's heading and the include of its region."""
    return (f'[#webcpp-{anchor}-{name}]\n=== link:{{library-pages}}{name}/{{library-page}}'
            f'[{name}]\n\ninclude::{{webcpp-root}}/libs/{name}/doc/changelog.adoc'
            '[tag=unreleased]')


UPDATED = updated_entry('alpha')


def findings_of(text: str) -> list[changelog.Finding]:
    """What breaks the form of the release notes of 0.2.0 text."""
    return changelog.notes_findings(text, '0.2.0')


def test_release_notes_in_form() -> None:
    text = notes(new='* link:{library-pages}gamma/{library-page}[gamma]: a library,\n'
                     'from R.',
                 updated=UPDATED, tools='* Added a target.', compilers='* GCC 14')
    parsed, found = changelog.parse_notes(text, '0.2.0')
    assert found == [], found
    assert parsed.preparing
    assert parsed.new == [('gamma', 'a library, from R.')]
    assert parsed.updated == [('alpha', 'unreleased')]
    assert [bullet.text for bullet in parsed.tools] == ['Added a target.']
    assert parsed.compilers == ['GCC 14']
    frozen, found = changelog.parse_notes(notes(preparing=False), '0.2.0')
    assert found == [] and not frozen.preparing and frozen.compilers is None
    two = notes(updated=updated_entry('alpha') + '\n\n' + updated_entry('beta'),
                removed='* delta: what went, for a reason.\n* epsilon: what went too.')
    parsed, found = changelog.parse_notes(two, '0.2.0')
    assert found == [] and parsed.updated == [('alpha', 'unreleased'), ('beta', 'unreleased')]
    assert parsed.removed == [('delta', 'what went, for a reason.'),
                              ('epsilon', 'what went too.')]


def test_release_notes_out_of_form() -> None:
    text = notes(new='* link:{library-pages}gamma/{library-page}[gamma]: a library.')
    _, found = changelog.parse_notes(text, '0.2.0')
    assert found == [(line_of(text, '* link:{library-pages}gamma/{library-page}[gamma]: a '
                                    'library.'),
                      'not a line of new-libraries: link:{library-pages}gamma/{library-page}'
                      '[gamma]: a library.')], found
    unsorted = notes(new='* link:{library-pages}zeta/{library-page}[zeta]: z, from R.\n'
                         '* link:{library-pages}eta/{library-page}[eta]: e, from R.')
    assert any('in alphabetical order' in message
               for _, message in changelog.parse_notes(unsorted, '0.2.0')[1])
    swapped = notes().replace('== Removed Libraries', '== Tools and build', 1)
    assert changelog.parse_notes(swapped, '0.2.0')[1][0][1].startswith(
        'release notes hold five sections, in order')
    assert changelog.notes_findings(notes(tools='* Built a thing.'), '0.2.0') != []


def test_release_notes_hold_nothing_else() -> None:
    preamble = notes().replace('= webcpp 0.2.0\n', '= webcpp 0.2.0\n\nA stray paragraph.\n')
    assert findings_of(preamble) == [
        (line_of(preamble, '= webcpp 0.2.0') + 1,
         'between the title and New Libraries, release notes hold the paragraph '
         '"In preparation: ..." or nothing')]
    other = notes(updated=updated_entry('alpha', '0-1-0'))
    updated_form = ('Updated Libraries holds, for each library, [#webcpp-0-2-0-<name>], === '
                    'link:{library-pages}<name>/{library-page}[<name>] and the include of its '
                    'changelog\'s region, or None.')
    assert findings_of(other) == [(line_of(other, '== Updated Libraries') + 1, updated_form)]
    trailing = notes(updated=UPDATED + '\n\nA stray paragraph.')
    assert findings_of(trailing) == [(line_of(trailing, '== Updated Libraries') + 1,
                                      updated_form)]
    tools = notes(tools='* Added a target.\n\nA stray paragraph.')
    assert findings_of(tools) == [(line_of(tools, 'A stray paragraph.'),
                                   'not a line of a changelog, which starts with "* ": '
                                   'A stray paragraph.')]
    lanes = notes(compilers='* GCC 14\n\nGCC 13')
    assert findings_of(lanes) == [(line_of(lanes, 'GCC 13'),
                                   'not a line of a changelog, which starts with "* ": GCC 13')]
    joined = notes(compilers='* GCC 14\nGCC 13')
    assert findings_of(joined) == [(line_of(joined, '* GCC 14'),
                                    'a lane of Compilers tested is one line: GCC 14 GCC 13')]


def test_release_notes_list_each_library_once_in_order() -> None:
    updated = notes(updated=updated_entry('beta') + '\n\n' + updated_entry('alpha'))
    assert findings_of(updated) == [(line_of(updated, '== Updated Libraries') + 1,
                                     'updated-libraries lists its libraries in alphabetical '
                                     'order')]
    removed = notes(removed='* epsilon: what went.\n* delta: what went.')
    assert findings_of(removed) == [(line_of(removed, '== Removed Libraries') + 1,
                                     'removed-libraries lists its libraries in alphabetical '
                                     'order')]
    twice = notes(removed='* delta: what went.\n* delta: what went again.')
    assert findings_of(twice) == [(line_of(twice, '== Removed Libraries') + 1,
                                   'removed-libraries lists each library once')]


def test_release_notes_sections_each_once_and_never_empty() -> None:
    for title, empty in (('New Libraries', notes(new='')),
                         ('Removed Libraries', notes(removed='')),
                         ('Tools and build', notes(tools='')),
                         ('Compilers tested', notes(compilers=''))):
        assert findings_of(empty) == [(line_of(empty, f'== {title}'),
                                       f'{title} holds its entries, or the paragraph None.')], \
            title
    empty = notes(updated='')
    assert findings_of(empty) != []
    twice = notes() + '\n[#webcpp-0-2-0-tools-and-build]\n== Tools and build\n\nNone.\n'
    assert findings_of(twice)[0][1].startswith('release notes hold five sections, in order')


def test_release_notes_hold_no_cross_reference() -> None:
    new = '* link:{library-pages}gamma/{library-page}[gamma]: see <<gamma-intro>>, from R.'
    removed = '* delta: see xref:delta-intro[its page].'
    tools = '* Added <<webcpp-0-2-0>>.'
    for line, text in ((new, notes(new=new)), (removed, notes(removed=removed)),
                       (tools, notes(tools=tools))):
        assert findings_of(text) == [(line_of(text, line), CROSS_REFERENCE)], line


def test_a_lane_as_the_notes_write_it() -> None:
    # Every lane of the CI, as Compilers tested writes it: no ++, which doc-check refuses in prose,
    # and Asciidoctor renders the CI's name back; the reader keeps the line as written.
    written = [changelog.notes_lane(lane.name) for lane in matrix.LANES]
    assert not any('++' in line for line in written), written
    assert 'Clang 18 (libstdc{plus}{plus}, container, no network)' in written, written
    rendered = flat_items(asciidoctor(''.join(f'* {line}\n' for line in written)))
    assert rendered == [lane.name for lane in matrix.LANES], rendered
    parsed, found = changelog.parse_notes(
        notes(compilers='\n'.join(f'* {line}' for line in written)), '0.2.0')
    assert found == [] and parsed.compilers == written, (found, parsed.compilers)


def test_findings_by_path() -> None:
    text = log('alpha', ('Unreleased', ['* Made a mistake.']))
    assert changelog.file_findings('libs/alpha/doc/changelog.adoc', text) != []
    assert changelog.file_findings('libs/alpha/doc/other.adoc', text) == []
    assert changelog.file_findings('doc/releases/0.2.0.adoc', notes(tools='* Made it.')) != []
    assert changelog.file_findings('doc/index.adoc', 'anything') == []


def test_the_tree_s_changelogs_keep_their_form() -> None:
    # The real files, read only: what the lint's rule changelog reads on every run.
    paths = [*ROOT.glob('libs/*/doc/changelog.adoc'), *ROOT.glob('doc/releases/*.adoc')]
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        assert changelog.file_findings(relative, path.read_text(encoding='utf-8')) == [], relative


CASES: list[Callable[[], None]] = [
    test_a_changelog_in_form_passes,
    test_wrapped_lines_are_one_bullet,
    test_a_list_inside_a_bullet_fails,
    test_the_reader_reads_a_list_as_asciidoctor_does,
    test_eleven_wrapped_lines_fail,
    test_a_line_holds_at_most_thirty_words,
    test_text_outside_a_bullet_and_a_cross_reference_fail,
    test_a_breaking_change_goes_on_with_a_verb,
    test_cross_references_as_asciidoctor_reads_them,
    test_text_outside_every_region_fails,
    test_sections_in_order_each_with_its_region,
    test_each_section_named_as_its_title,
    test_release_notes_in_form,
    test_release_notes_out_of_form,
    test_release_notes_hold_nothing_else,
    test_release_notes_list_each_library_once_in_order,
    test_release_notes_sections_each_once_and_never_empty,
    test_release_notes_hold_no_cross_reference,
    test_a_lane_as_the_notes_write_it,
    test_findings_by_path,
    test_the_tree_s_changelogs_keep_their_form,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'changelog_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        case()
        print(f'{case.__name__}: ok')
    print('changelog_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
