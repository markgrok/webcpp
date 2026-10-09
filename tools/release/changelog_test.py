#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/release/changelog.py: a library's changelog and a version's release notes in
AGENTS.md chapter 11's form pass, wrapped lines included; a line with no verb of the list, a
cross-reference, an eleventh line, text outside a bullet, a section out of order or without its
region, and notes out of form each fail, at their line. Run with the names of some cases to run
only those."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import changelog

ROOT = Path(__file__).resolve().parents[2]


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


def test_eleven_wrapped_lines_fail() -> None:
    lines = [part for number in range(11) for part in (f'* Added line {number}', 'wrapped.')]
    text = log('alpha', ('Unreleased', lines))
    found = changelog.changelog_findings(text, 'alpha')
    assert found == [(line_of(text, '=== Unreleased'),
                      'Unreleased holds 11 lines, and a library holds at most 10 per version')]


def test_text_outside_a_bullet_and_a_cross_reference_fail() -> None:
    text = log('alpha', ('Unreleased', ['* Added <<alpha-intro>>.', '', 'A paragraph.']))
    assert changelog.changelog_findings(text, 'alpha') == [
        (line_of(text, '* Added <<alpha-intro>>.'), 'a line holds no cross-reference, <<...>>: '
                                                    'the index page shows it too'),
        (line_of(text, 'A paragraph.'), 'not a line of a changelog, which starts with "* ": '
                                        'A paragraph.')]


def test_a_breaking_change_goes_on_with_a_verb() -> None:
    # *Breaking change:* comes before the verb, whose first letter may then be lower case.
    text = log('alpha', ('Unreleased', ['* *Breaking change:* Removed `x`.',
                                        '* *Breaking change:* `x` is gone.']))
    assert changelog.changelog_findings(text, 'alpha') == [
        (line_of(text, '* *Breaking change:* `x` is gone.'),
         'after *Breaking change:*, a line goes on with one of Added, Changed, Deprecated, '
         'Fixed, Improved, Removed, Updated: *Breaking change:* `x` is gone.')]


def test_an_xref_is_a_cross_reference() -> None:
    text = log('alpha', ('Unreleased', ['* Added xref:alpha-intro[the introduction].']))
    assert changelog.changelog_findings(text, 'alpha') == [
        (line_of(text, '* Added xref:alpha-intro[the introduction].'),
         'a line holds no cross-reference, <<...>>: the index page shows it too')]


def test_text_outside_every_region_fails() -> None:
    # A line after a region's end shows on the page, but no release note includes it.
    text = log('alpha', ('Unreleased', ['* Added a line.']), ('webcpp 0.1.0', [])).replace(
        '// end::unreleased[]\n', '// end::unreleased[]\n* Added a stray line.\n')
    assert changelog.changelog_findings(text, 'alpha') == [
        (line_of(text, '* Added a stray line.'),
         'a changelog holds its lines inside the regions of its sections: * Added a stray '
         'line.')]


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


def notes(*, preparing: bool = True, new: str = 'None.', updated: str = 'None.',
          tools: str = 'None.', compilers: str = 'None.') -> str:
    """Release notes of 0.2.0, each section's body as given."""
    text = '// The notice.\n\n[#webcpp-0-2-0]\n= webcpp 0.2.0\n'
    if preparing:
        text += '\n' + '\n'.join(changelog.IN_PREPARATION) + '\n'
    for slug, title, body in (('new-libraries', 'New Libraries', new),
                              ('updated-libraries', 'Updated Libraries', updated),
                              ('removed-libraries', 'Removed Libraries', 'None.'),
                              ('tools-and-build', 'Tools and build', tools),
                              ('compilers-tested', 'Compilers tested', compilers)):
        text += f'\n[#webcpp-0-2-0-{slug}]\n== {title}\n\n{body}\n'
    return text


UPDATED = ('[#webcpp-0-2-0-alpha]\n=== link:{library-pages}alpha/{library-page}[alpha]\n\n'
           'include::{webcpp-root}/libs/alpha/doc/changelog.adoc[tag=unreleased]')


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
    test_eleven_wrapped_lines_fail,
    test_text_outside_a_bullet_and_a_cross_reference_fail,
    test_a_breaking_change_goes_on_with_a_verb,
    test_an_xref_is_a_cross_reference,
    test_text_outside_every_region_fails,
    test_sections_in_order_each_with_its_region,
    test_release_notes_in_form,
    test_release_notes_out_of_form,
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
