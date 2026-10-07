#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Finds what Asciidoctor would get wrong in a library's page without a warning.

Four faults pass Asciidoctor's own checks. A line that starts with `//`, and not `///`, inside a
table is read as a comment and vanishes from its cell: a line of the section itself, or a line of
an included file once the include's `lines`, `tag` and `indent` are applied. An include of an
output, an example's `{examples}/<path>.expected` or a twin's `{twins}/<path>.expected`, names a
program that is not there: an example or a twin removed or renamed left the include behind, and
the page would show what no program printed. Any other `include::`, one of a section or of an
example's or a twin's own source, names a file that is not there, or one that exists but strays
outside `doc/`, `{examples}` and `{twins}` - Asciidoctor resolves it (with `-S unsafe`) wherever
it points. And a `++` in prose, outside a block, inline code and an explicit passthrough
(`pass:[...]`, `+++...+++`): two of them in one paragraph make Asciidoctor read what lies between
them as a passthrough, which drops both and swallows a cross-reference with no warning; `{cpp}`
writes the language's name without the risk.

An example is a program under `--examples`, at any depth, with the output it prints beside it:
`<name>.cpp` and `<name>.expected`, as webcpp.example compares them. A twin is the same program
written for the original a library ports, `<name>.mjs` under `--twins`, and its `<name>.expected`,
when there is one, is the output of a difference the port makes on purpose. `{reference}` is the
reference MrDocs writes, which webcpp.doc names.

The page answers for itself and for the files around it. `--page` names the page's entry file;
every `.adoc` the page's `include::` graph does not reach, among the sections given, is a fault
naming the file, and only a reached section's anchors count toward the checks below. A file of
the library that sends its reader to the page, with `doc: #<anchor>`, or a list or a range of them
on one line, `doc: #<a>, #<b> and #<c>` or `doc: #<a> to #<b>`, or with a link
`index.html#<anchor>`, names anchors a reached section defines, each of them; with
`--repository`, every file git lists there, those it tracks and those it would track, is read for
one, skipping what does not decode as UTF-8. With `--readme`, each fenced block of the README
that a comment `<!-- include::<file>[<attributes>] -->` opens is that file's region, as an include
with those attributes would give it, and every C++ block of the README is one. With --complete,
the page is whole: every block's language is one of the page's, C++, JavaScript, JSON or shell,
as Asciidoctor reads it; its C++ is included from the example programs, the reference's synopses
being MrDocs's; it shows JavaScript only as an include of a twin; it shows every example's code
or output, and every output of a twin, each a difference from the original that the page
explains; and it shows the reference, `include::{reference}[leveloffset=+1]`.

And the rendered page, given alone with `--rendered`, shows no cross-reference left as text,
`&lt;&lt;id&gt;&gt;`, outside its blocks of code, inline code included; no literal `++` outside
its code; no backtick outside its blocks of code: one inside inline code is the mark of two spans
run together by a passthrough, and one outside it of a span that did not close (postprocess.mjs
keeps a + and a backtick MrDocs escaped as references, as Asciidoctor writes {cpp}); no escape of
MrDocs's left undecoded and no U+2010, which MrDocs writes for an ASCII hyphen; and no link of a
synopsis left as text in a block of code, which a highlighter that broke the link leaves.

Usage: doc-check.py --page <page.adoc> [--examples <dir>] [--twins <dir>] [--repository <dir>]
[--readme <README.md>] [--complete] <section.adoc>...; or doc-check.py --rendered <page.html>.
Prints each fault and exits 1 when there is one.
"""

from __future__ import annotations

import argparse
import re
from html import unescape
import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

INCLUDE = re.compile(r'^include::([^\[]+)\[(.*)\]$')
# A table opens with |, a comma, a colon or ! and three or more =, and closes with the same line;
# one table holds another under a different delimiter.
TABLE = re.compile(r'^[|,:!]={3,}$')
TAG_DIRECTIVE = re.compile(r'\b(tag|end)::(\S+?)\[\]')
# A path under {examples} or {twins}, at any depth.
NESTED = r'((?:[\w-]+/)*[\w-]+)'
OUTPUT = re.compile(rf'^\{{examples\}}/{NESTED}\.expected$')
TWIN_OUTPUT = re.compile(rf'^\{{twins\}}/{NESTED}\.expected$')
TWIN_SOURCE = re.compile(rf'^include::\{{twins\}}/{NESTED}\.mjs\[[^\]]*\]$')
EXAMPLE_SOURCE = re.compile(rf'^include::\{{examples\}}/{NESTED}\.(cpp|hpp)\[[^\]]*\]$')
SHOWN = re.compile(rf'^include::\{{(examples|twins)\}}/{NESTED}\.(cpp|expected)\[')
REFERENCE = '{reference}'
ANCHOR = re.compile(r'^\[#([\w-]+)[\],.]|\[\[([\w-]+)\]\]')
# `doc: #<a>`, or a list or a range of anchors, `doc: #<a>, #<b> and #<c>` or `doc: #<a> to
# #<b>`, on one line; or a link to the built page.
DOC_REFERENCE = re.compile(r'doc: (#[\w-]+(?:(?:,| and| or| to) #[\w-]+)*)')
DOC_ANCHOR = re.compile(r'#([\w-]+)')
PAGE_LINK = re.compile(r'index\.html#([\w-]+)')
# A list cut at the end of its line, whose rest the line-by-line read would miss.
DOC_REFERENCE_CUT = re.compile(
    r'doc: #[\w-]+(?:(?:,| and| or| to) #[\w-]+)*(?:,| and| or| to)\s*$')
ATTRIBUTE_ENTRY = re.compile(r'^:([\w-]+!?):\s*(.*)$')
ATTRIBUTE_REFERENCE = re.compile(r'\{([\w-]+)\}')

# The languages of the page's blocks, those highlighter.mjs colours. C++ is the language of a
# block that names none, as the page's `:source-language:` makes it; it is only an example's
# code. JavaScript is only a twin's code. JSON is a configuration, and bash the commands a reader
# runs. Any other spelling, `js` or `c++`, is a fault, so that neither rule can be passed by
# naming the language another way.
LANGUAGES = ('cpp', 'javascript', 'json', 'bash')
DEFAULT_LANGUAGE = 'cpp'
# Blocks whose lines Asciidoctor does not read as prose: listing, literal, passthrough and
# comment.
VERBATIM = re.compile(r'^(-{4,}|\.{4,}|\+{4,}|/{4,})$')
FENCE = re.compile(r'^```')
# A block's attribute list, `[source,cpp]`, not a block anchor `[[name]]`.
ATTRIBUTE_LIST = re.compile(r'^\[(?!\[)(.*)\]$')
BLOCK_ANCHOR = re.compile(r'^\[\[[\w-]+(?:,[^\]]*)?\]\]$')
TITLE = re.compile(r'^\.[^.\s]')
# The delimiters of blocks whose lines are prose: example, sidebar, quote, open and table.
COMPOUND = re.compile(r'^(={4,}|\*{4,}|_{4,}|--|[|,:!]={3,})$')
DIRECTIVE = re.compile(r'^(include|ifdef|ifndef|ifeval|endif)::')
# What may hold ++ in prose, removed before it is looked for: an explicit passthrough, then
# inline code. A constrained passthrough, `+...+`, is not one of them: a ++ inside it breaks it
# as it breaks a paragraph.
SAFE_INLINE = (re.compile(r'pass:[a-z,]*\[(?:\\.|[^\]\\])*\]'),
               re.compile(r'\+\+\+.*?\+\+\+', re.S),
               re.compile(r'``.+?``', re.S),
               re.compile(r'`[^`]+`'))
# A copy in the README: `<!-- include::<file>[<attributes>] -->` on the line before the fenced
# block it opens.
README_COPY = re.compile(r'^<!-- include::([^\[\s]+)\[([^\]]*)\] -->$')
README_FENCE = re.compile(r'^(`{3,})\s*([\w+-]*)')

# The character references MrDocs writes in place of the characters AsciiDoc could read as
# markup, which postprocess.mjs decodes in the converted page; &lt;, &gt;, &amp; and &quot; stay,
# as HTML needs them.
MRDOCS_ESCAPE = re.compile(r'&(circ|lowbar|ast|grave|num|lsqb|rsqb|lcub|rcub|bsol|verbar|hyphen|'
                           r'equals|semi|plus|colon|period|apos|sol);')
# U+2010, which &hyphen; stands for and MrDocs means as -.
HYPHEN = '\u2010'
# A link of a synopsis, which the macros substitution reads only when the highlighter keeps it.
LINK_MACRO = re.compile(r'link:[^\s\[]*\[')
# A cross-reference as Asciidoctor leaves it when it reads none, <<id>> or <<id,text>>; not the
# << of an operator<< that MrDocs names.
CROSS_REFERENCE = re.compile(r'&lt;&lt;[\w-]+(?:,.*?)?&gt;&gt;')

Fault = tuple[int, str]


def dropped_by_table(line: str) -> bool:
    """Whether a table's reader takes `line` for a comment, as Asciidoctor's does."""
    return line.startswith('//') and not line.startswith('///')


def attributes(text: str) -> dict[str, str]:
    """The include's attributes, as a dict."""
    found = {}
    for name, value in re.findall(r'(\w+)=("[^"]*"|[^,]*)', text):
        found[name] = value.strip('"')
    return found


def numbered(lines: list[str], ranges: str) -> list[str]:
    """The lines a `lines` attribute selects: `2`, `1..5`, `3..-1`, `;` or `,` between."""
    kept: list[int] = []
    for part in re.split(r'[;,]', ranges):
        if not part.strip():
            continue
        if '..' in part:
            first, last = part.split('..', 1)
        else:
            first = last = part
        start = int(first)
        end = len(lines) if int(last) == -1 else int(last)
        kept.extend(range(start, end + 1))
    return [lines[index - 1] for index in sorted(set(kept)) if 1 <= index <= len(lines)]


def tagged(lines: list[str], tags: str) -> list[str]:
    """The lines a `tag` or `tags` attribute selects, as Asciidoctor selects them.

    `**` keeps every line, `*` every tagged line, `!name` leaves a tag out; a region not named
    takes the selection around it, or the wildcard's.
    """
    wanted: dict[str, bool] = {}
    for name in re.split(r'[;,]', tags):
        name = name.strip()
        if not name:
            continue
        if name.startswith('!'):
            wanted[name[1:]] = False
        else:
            wanted[name] = True
    if '**' in wanted:
        base = wanted.pop('**')
        wildcard: bool | None = wanted.pop('*', base)
    else:
        base = not any(wanted.values())
        wildcard = wanted.pop('*', None)
    kept = []
    stack: list[tuple[str, bool]] = []
    select = base
    for line in lines:
        directive = TAG_DIRECTIVE.search(line)
        if directive is not None and directive.group(1) == 'tag':
            name = directive.group(2)
            if name in wanted:
                select = wanted[name]
            elif wildcard is not None:
                select = wildcard
            stack.append((name, select))
            continue
        if directive is not None:
            if stack and stack[-1][0] == directive.group(2):
                stack.pop()
            select = stack[-1][1] if stack else base
            continue
        if select:
            kept.append(line)
    return kept


def selected(lines: list[str], given: dict[str, str]) -> list[str]:
    """The lines an include keeps: `lines` first, as Asciidoctor gives it precedence, else
    tags."""
    if 'lines' in given:
        return numbered(lines, given['lines'])
    tags = given.get('tags', given.get('tag'))
    if tags is not None:
        return tagged(lines, tags)
    return [line for line in lines if TAG_DIRECTIVE.search(line) is None]


def indented(lines: list[str], indent: int) -> list[str]:
    """The lines as Asciidoctor's indent attribute leaves them."""
    margins = [len(line) - len(line.lstrip(' ')) for line in lines if line.strip()]
    margin = min(margins, default=0)
    return [(' ' * indent + line[margin:]) if line.strip() else line for line in lines]


class Library:
    """Where a page's includes resolve: its examples and its twins, each a directory or None
    when the library has none."""

    def __init__(self, examples: Path | None, twins: Path | None) -> None:
        self.examples = examples
        self.twins = twins

    def defined(self) -> dict[str, str]:
        """The attributes webcpp.doc gives the page, as Asciidoctor seeds an attribute given on
        its command line."""
        found = {}
        if self.examples is not None:
            found['examples'] = str(self.examples)
        if self.twins is not None:
            found['twins'] = str(self.twins)
        return found

    def example_output(self, target: str) -> tuple[Path | None, Path | None]:
        """For an include of an example's output, the output and the program that prints it."""
        output = OUTPUT.match(target)
        if output is None or self.examples is None:
            return None, None
        return (self.examples / f'{output.group(1)}.expected',
                self.examples / f'{output.group(1)}.cpp')

    def twin_output(self, target: str) -> tuple[Path | None, Path | None]:
        """For an include of a twin's output, the output and the twin that prints it."""
        output = TWIN_OUTPUT.match(target)
        if output is None or self.twins is None:
            return None, None
        return (self.twins / f'{output.group(1)}.expected',
                self.twins / f'{output.group(1)}.mjs')

    def roots(self) -> list[Path]:
        """The directories, besides the page's own, an include may reach into."""
        return [root for root in (self.examples, self.twins) if root is not None]


def resolved(section: Path, target: str, library: Library,
             defined: dict[str, str]) -> Path | None:
    """Where an include's target is, or None for an attribute the section does not define."""
    for output, _ in (library.example_output(target), library.twin_output(target)):
        if output is not None:
            return output
    target = ATTRIBUTE_REFERENCE.sub(lambda name: defined.get(name.group(1), name.group(0)),
                                     target)
    if '{' in target:
        return None
    return section.parent / target


def within(path: Path, roots: Iterable[Path]) -> bool:
    """Whether `path`, once resolved, is under one of `roots`."""
    target = path.resolve()
    return any(target.is_relative_to(root.resolve()) for root in roots)


def faults(section: Path, library: Library, doc_root: Path) -> list[Fault]:
    """Each fault of `section`, as (line number, text)."""
    found: list[Fault] = []
    tables: list[str] = []
    defined = library.defined()
    for number, line in enumerate(section.read_text().split('\n'), start=1):
        stripped = line.rstrip()
        entry = ATTRIBUTE_ENTRY.match(stripped)
        if entry is not None:
            defined[entry.group(1)] = entry.group(2)
            continue
        if TABLE.match(stripped):
            if tables and tables[-1] == stripped:
                tables.pop()
            else:
                tables.append(stripped)
            continue
        if tables and dropped_by_table(line):
            found.append((number, f'a table drops this line: {line}'))
        match = INCLUDE.match(stripped)
        if match is None:
            continue
        target = match.group(1)
        _, program = library.example_output(target)
        if program is not None and not program.is_file():
            found.append((number, f'includes the output of no example: {target}'))
            continue
        _, twin = library.twin_output(target)
        if twin is not None and not twin.is_file():
            found.append((number, f'includes the output of no twin: {target}'))
            continue
        path = resolved(section, target, library, defined)
        # Any other include answers for itself: an output already did, above, against the
        # program that would print it.
        if program is None and twin is None and path is not None:
            if not path.is_file():
                found.append((number, f'includes a file that is not there: {target}'))
                continue
            if not within(path, [doc_root, *library.roots()]):
                found.append((number,
                              f'includes a file outside doc, examples or twins: {target}'))
                continue
        if not tables or path is None or not path.is_file():
            continue
        given = attributes(match.group(2))
        lines = selected(path.read_text().split('\n'), given)
        if 'indent' in given:
            if not given['indent'].isdigit():
                found.append((number, f'indent is not a number: {given["indent"]}'))
                continue
            lines = indented(lines, int(given['indent']))
        for text in lines:
            if dropped_by_table(text):
                found.append((number, f'a table drops this line: {target}: {text}'))
    return found


def page_edges(section: Path, library: Library) -> set[Path]:
    """Every `.adoc` page `section` includes, by resolved path."""
    found = set()
    defined = library.defined()
    for line in section.read_text().split('\n'):
        stripped = line.rstrip()
        entry = ATTRIBUTE_ENTRY.match(stripped)
        if entry is not None:
            defined[entry.group(1)] = entry.group(2)
            continue
        match = INCLUDE.match(stripped)
        if match is None:
            continue
        target = match.group(1)
        if OUTPUT.match(target) is not None or TWIN_OUTPUT.match(target) is not None:
            continue
        path = resolved(section, target, library, defined)
        if path is not None and path.suffix == '.adoc':
            found.add(path.resolve())
    return found


def reached(page: Path, sections: list[Path], library: Library) -> set[Path]:
    """Every one of `sections`, by resolved path, that `page`'s include graph reaches."""
    known = {page.resolve()} | {section.resolve() for section in sections}
    by_path = {section.resolve(): section for section in sections}
    by_path[page.resolve()] = page
    seen = {page.resolve()}
    stack = [page.resolve()]
    while stack:
        current = by_path[stack.pop()]
        for target in page_edges(current, library):
            if target in known and target not in seen:
                seen.add(target)
                stack.append(target)
    return seen


def orphan_faults(page: Path, sections: list[Path], library: Library) -> list[str]:
    """Each of `sections` that `page`'s include graph does not reach."""
    visited = reached(page, sections, library)
    return [f'{section}: not reached from the page' for section in sections
            if section.resolve() not in visited]


def anchors(sections: list[Path]) -> set[str]:
    """Every anchor the sections define: [#name] before a block or a heading, and [[name]]."""
    found = set()
    for section in sections:
        for line in section.read_text().split('\n'):
            for match in ANCHOR.finditer(line):
                found.add(match.group(1) or match.group(2))
    return found


def listed_files(repository: Path) -> list[Path] | None:
    """Every file git lists in `repository`, those it tracks and those it would track, or None
    when it is not a git checkout."""
    listed = subprocess.run(['git', '-C', str(repository), 'ls-files', '-z', '--cached',
                             '--others', '--exclude-standard'], capture_output=True, check=False)
    if listed.returncode != 0:
        return None
    names = sorted(set(listed.stdout.decode('utf-8').split('\0')) - {''})
    return [repository / name for name in names]


def reference_faults(paths: list[Path], defined: set[str]) -> list[str]:
    """Each reference of a text file among `paths` to the page that names no anchor of it."""
    found = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.split('\n'), start=1):
            if DOC_REFERENCE_CUT.search(line):
                found.append(f'{path}:{number}: a doc: reference goes on to the next line; '
                             'keep its anchors on one line')
            named = [anchor for match in DOC_REFERENCE.finditer(line)
                     for anchor in DOC_ANCHOR.findall(match.group(1))]
            for anchor in named + PAGE_LINK.findall(line):
                if anchor not in defined:
                    found.append(f'{path}:{number}: names no anchor of the page: #{anchor}')
    return found


def attribute_items(text: str) -> list[str]:
    """The items of an attribute list, split at the commas outside quotes."""
    items, current, quote = [], '', None
    for character in text:
        if quote is not None:
            quote = None if character == quote else quote
        elif character in '"\'':
            quote = character
        elif character == ',':
            items.append(current.strip())
            current = ''
            continue
        current += character
    items.append(current.strip())
    return items


def style_of(attribute_lines: Iterable[str]) -> tuple[str, str | None]:
    """A block's style and the language its attribute lists give, merged as Asciidoctor merges
    them.

    The style is the first item, without its `#id`, `.role` and `%option` shorthand; the language
    is the second when it is positional, or the named `language`.
    """
    style, language = '', None
    for line in attribute_lines:
        match = ATTRIBUTE_LIST.match(line)
        if match is None:
            continue
        items = attribute_items(match.group(1))
        named = {}
        for item in items:
            pair = re.match(r'^([\w-]+)=(.*)$', item)
            if pair is not None:
                named[pair.group(1)] = pair.group(2).strip('"\'')
        given = re.sub(r'[#.%].*', '', items[0])
        if given and '=' not in items[0]:
            style = given
        if len(items) > 1 and items[1] and '=' not in items[1]:
            language = items[1]
        language = named.get('language', language)
    return style, language


def language_of(attribute_lines: list[str], delimiter: str | None) -> str | None:
    """The language Asciidoctor gives a block, or None for one that is not source code.

    A listing block with no style takes the page's `:source-language:` (Asciidoctor's parser), so
    `----` alone is C++, and `[listing]` keeps it plain; a literal block or a paragraph is code
    only when styled `source`.
    """
    style, language = style_of(attribute_lines)
    if delimiter is not None and delimiter.startswith('-'):
        return language or DEFAULT_LANGUAGE if style in ('', 'source') else None
    if delimiter is not None and not delimiter.startswith('.'):
        return None
    return language or DEFAULT_LANGUAGE if style == 'source' else None


# ('block', line, attribute lines, delimiter, body), ('entry', line, text) or ('prose', line, text).
Item = tuple


def walk(lines: list[str]) -> list[Item]:
    """A section as Asciidoctor reads it: its blocks, its attribute entries and its prose.

    Each item is ('block', line, attribute lines, opening delimiter or None, body) for a listing,
    literal, passthrough or comment block, a Markdown fence, or a paragraph styled `source`,
    `listing` or `literal`, its line the first of its attributes and title; ('entry', line, text)
    for an attribute entry; and ('prose', line, text) for each run of lines read as text: a
    paragraph, a heading, a block's title, a list item, table cells.

    Blank lines may stand between a block and its attribute lists, which the block, or the
    paragraph or heading that follows, then takes.
    """
    found: list[Item] = []
    preamble: list[tuple[int, str]] = []
    prose: list[tuple[int, str]] = []

    def flush() -> None:
        if prose:
            found.append(('prose', prose[0][0], '\n'.join(text for _, text in prose)))
            prose.clear()

    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        number = index + 1
        if VERBATIM.match(line) or FENCE.match(line):
            flush()
            closing = '```' if FENCE.match(line) else line
            end = index + 1
            while end < len(lines) and lines[end].rstrip() != closing:
                end += 1
            first = preamble[0][0] if preamble else number
            found.append(('block', first, [text for _, text in preamble], line,
                          lines[index + 1:end]))
            preamble = []
            index = end + 1
            continue
        index += 1
        if not line:
            flush()
        elif line.startswith('//') and not line.startswith('///') or DIRECTIVE.match(line):
            continue
        elif COMPOUND.match(line) or line == '+':
            # A list continuation, `+` alone, attaches the block that follows to the item
            # before it.
            flush()
            preamble = []
        elif prose:
            prose.append((number, line))
        elif ATTRIBUTE_LIST.match(line) or BLOCK_ANCHOR.match(line):
            preamble.append((number, line))
        elif TITLE.match(line):
            preamble.append((number, line))
            found.append(('prose', number, line[1:]))
        elif ATTRIBUTE_ENTRY.match(line):
            found.append(('entry', number, line))
        elif style_of(text for _, text in preamble)[0] in ('source', 'listing', 'literal'):
            end = index
            while end < len(lines) and lines[end].strip():
                end += 1
            found.append(('block', preamble[0][0], [text for _, text in preamble], None,
                          lines[index - 1:end]))
            preamble = []
            index = end
        else:
            preamble = []
            prose.append((number, line))
    flush()
    return found


def block_faults(section: Path) -> list[str]:
    """Each block of `section` in a language the page does not use, each C++ block that no
    example holds, and each JavaScript block that no twin holds.

    The reference's synopses are MrDocs's, in the file it writes at {reference}, which is no
    section: everywhere in the page the C++ is an example program's, included by tag, and the
    JavaScript a twin's.
    """
    found = []
    for kind, number, *rest in walk(section.read_text().split('\n')):
        if kind == 'entry':
            entry = ATTRIBUTE_ENTRY.match(rest[0])
            if entry is not None and entry.group(1).rstrip('!') == 'source-language' and \
                    (entry.group(1).endswith('!') or entry.group(2).strip() != DEFAULT_LANGUAGE):
                found.append(f'{section}:{number}: the blocks that name no language are C++, '
                             f'`:source-language: {DEFAULT_LANGUAGE}`; a block names another '
                             'itself')
            continue
        if kind != 'block':
            continue
        attribute_lines, delimiter, body = rest
        if delimiter is not None and FENCE.match(delimiter):
            found.append(f'{section}:{number}: a Markdown fence; write [source] and ----')
            continue
        language = language_of(attribute_lines, delimiter)
        if language is None:
            continue
        if language not in LANGUAGES:
            found.append(f'{section}:{number}: a block in {language}, a language the page does '
                         f'not use; write {", ".join(LANGUAGES)}')
        elif language == 'javascript' and (len(body) != 1 or TWIN_SOURCE.match(body[0]) is None):
            found.append(f'{section}:{number}: JavaScript that is not an include of a twin')
        elif language == DEFAULT_LANGUAGE and \
                any(line.strip() and EXAMPLE_SOURCE.match(line.strip()) is None for line in body):
            found.append(f'{section}:{number}: C++ that is not included from an example')
    return found


def prose_faults(section: Path) -> list[str]:
    """Each ++ in the prose of `section`, outside inline code and explicit passthroughs."""
    found = []
    for kind, number, *rest in walk(section.read_text().split('\n')):
        if kind != 'prose':
            continue
        text = rest[0]
        # Each span becomes a space and its line breaks, so that no ++ is made of the characters
        # around it and every line keeps its number.
        for pattern in SAFE_INLINE:
            text = pattern.sub(lambda span: ' ' + '\n' * span.group(0).count('\n'), text)
        for match in re.finditer(r'\+\+', text):
            line = number + text.count('\n', 0, match.start())
            found.append(f'{section}:{line}: a literal ++ in prose, which Asciidoctor reads as a '
                         'passthrough; write C++ as {cpp}, and code as inline code')
    return found


def copy_faults(readme: Path, copy: tuple[int, str, str], number: int,
                body: list[str]) -> list[str]:
    """What is wrong with one copy of the README: a file that is not there, or a body that
    differs."""
    line, target, given = copy
    source = readme.parent / target
    if not source.is_file():
        return [f'{readme}:{line}: copies a file that is not there: {target}']
    held = source.read_text(encoding='utf-8').split('\n')
    if held and held[-1] == '':
        held.pop()
    options = attributes(given)
    region = selected(held, options)
    if options.get('indent', '').isdigit():
        region = indented(region, int(options['indent']))
    # The blank lines around a region are left out, as a listing block leaves them out.
    while region and not region[-1].strip():
        region.pop()
    while region and not region[0].strip():
        region.pop(0)
    if body == region:
        return []
    first = next(index for index in range(max(len(body), len(region)))
                 if body[index:index + 1] != region[index:index + 1])
    shown = repr(body[first]) if first < len(body) else 'nothing'
    kept = repr(region[first]) if first < len(region) else 'nothing'
    return [f'{readme}:{number}: differs from {target}[{given}], first at its line {first + 1}: '
            f'{shown} where the file has {kept}']


def readme_faults(readme: Path) -> list[str]:
    """Each copy of `readme` that is not what its file holds, and each C++ block that copies
    nothing."""
    if not readme.is_file():
        return [f'{readme}: not there']
    lines = readme.read_text(encoding='utf-8').split('\n')
    found = []
    copy = None
    index = 0
    while index < len(lines):
        line = lines[index]
        fence = README_FENCE.match(line)
        if copy is not None and fence is None:
            found.append(f'{readme}:{copy[0]}: names a copy, but no fenced block follows it')
            copy = None
        named = README_COPY.match(line)
        if fence is None:
            if named is not None:
                copy = (index + 1, named.group(1), named.group(2))
            index += 1
            continue
        end = index + 1
        while end < len(lines) and lines[end].rstrip() != fence.group(1):
            end += 1
        body = lines[index + 1:end]
        if copy is not None:
            found += copy_faults(readme, copy, index + 1, body)
        elif fence.group(2) == 'cpp':
            found.append(f'{readme}:{index + 1}: a C++ block that copies no example; open it '
                         'with <!-- include::<file>[tag=<tag>] -->')
        copy = None
        index = end + 1
    if copy is not None:
        found.append(f'{readme}:{copy[0]}: names a copy, but no fenced block follows it')
    return found


def examples_of(directory: Path | None) -> Iterator[Path]:
    """Every example under `directory`, at any depth: a .cpp with its .expected beside it."""
    if directory is None:
        return
    for program in sorted(directory.rglob('*.cpp')):
        if program.with_suffix('.expected').is_file():
            yield program


def completeness_faults(page: Path, sections: list[Path], library: Library) -> list[str]:
    """Each example and each twin's output the page does not show, and the reference when the
    page does not show it."""
    shown = set()
    references = []
    for section in sections:
        for number, line in enumerate(section.read_text().split('\n'), start=1):
            match = SHOWN.match(line.strip())
            if match is not None:
                shown.add((match.group(1), match.group(2), match.group(3)))
            include = INCLUDE.match(line.strip())
            if include is not None and include.group(1) == REFERENCE:
                references.append((section, number, attributes(include.group(2))))
    found = []
    for program in examples_of(library.examples):
        assert library.examples is not None
        name = program.relative_to(library.examples).with_suffix('').as_posix()
        if ('examples', name, 'cpp') not in shown and ('examples', name, 'expected') not in shown:
            found.append(f'{program}: the page shows neither its code nor its output')
    if library.twins is not None:
        for output in sorted(library.twins.rglob('*.expected')):
            name = output.relative_to(library.twins).with_suffix('').as_posix()
            if ('twins', name, 'expected') not in shown:
                found.append(f'{output}: the page does not show this difference from the '
                             'original')
    if not references:
        found.append(f'{page}: the page does not show the reference: '
                     'include::{reference}[leveloffset=+1]')
    for section, number, given in references:
        if given.get('leveloffset') != '+1':
            found.append(f'{section}:{number}: includes the reference without leveloffset=+1, '
                         'which puts its symbols a level under the page\'s chapter')
    return found


def rendered_faults(page: Path) -> list[str]:
    """Each cross-reference left as text, literal ++, stray backtick, escape of MrDocs's, U+2010
    and link left as text in code of the rendered `page`."""
    html = page.read_text(encoding='utf-8')
    found = []

    def report(kind: str, words: str, match: re.Match[str]) -> None:
        around = ' '.join(words[max(0, match.start() - 50):match.end() + 50].split())
        found.append(f'{page}: {kind}: ...{around}...')

    # Everywhere, the head included: no escape of MrDocs's, and no hyphen MrDocs meant as -.
    for match in MRDOCS_ESCAPE.finditer(html):
        report(f'an escape of MrDocs left undecoded: {match.group(0)}', html, match)
    for match in re.finditer(HYPHEN, html):
        report('a U+2010 hyphen where MrDocs read -', html, match)
    # In the blocks of code, no link of a synopsis left as text.
    for block in re.finditer(r'<pre\b[^>]*>(.*?)</pre>', html, flags=re.S):
        code = unescape(re.sub(r'<[^>]+>', '', block.group(1)))
        for match in LINK_MACRO.finditer(code):
            report(f'a link of a listing left as text: {match.group(0)}', code, match)
    # The blocks of code go, and the style and the scripts, which are no text.
    text = re.sub(r'<(pre|style|script)\b[^>]*>.*?</\1>', ' ', html, flags=re.S)
    words = re.sub(r'<[^>]+>', ' ', text)
    for match in CROSS_REFERENCE.finditer(words):
        report('a cross-reference left as text', words, match)
    for code in re.finditer(r'<code\b[^>]*>(.*?)</code>', text, flags=re.S):
        inside = re.sub(r'<[^>]+>', ' ', code.group(1))
        for match in re.finditer('`', inside):
            report('a backtick inside inline code, two spans run together', inside, match)
    outside = re.sub(r'<[^>]+>', ' ', re.sub(r'<code\b[^>]*>.*?</code>', ' ', text, flags=re.S))
    for match in re.finditer(r'\+\+', outside):
        report('a literal ++ outside code', outside, match)
    for match in re.finditer('`', outside):
        report('a backtick outside code, a span of inline code that did not close', outside,
               match)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Finds what Asciidoctor would get wrong in a page without a warning.')
    parser.add_argument('--examples', type=Path)
    parser.add_argument('--twins', type=Path)
    parser.add_argument('--page', type=Path)
    parser.add_argument('--repository', type=Path)
    parser.add_argument('--readme', type=Path)
    parser.add_argument('--complete', action='store_true')
    parser.add_argument('--rendered', type=Path)
    parser.add_argument('sections', type=Path, nargs='*')
    arguments = parser.parse_args()
    if arguments.rendered is not None:
        if arguments.sections or arguments.page or arguments.examples or arguments.twins or \
                arguments.repository or arguments.readme or arguments.complete:
            parser.error('--rendered checks the rendered page alone')
        found = rendered_faults(arguments.rendered)
        for fault in found:
            print(fault)
        return 1 if found else 0
    if not (arguments.page and arguments.sections):
        parser.error('--page and at least one section are required')
    library = Library(arguments.examples, arguments.twins)
    page: Path = arguments.page
    sections: list[Path] = arguments.sections
    doc_root = page.parent
    found = []
    for section in sections:
        for number, text in faults(section, library, doc_root):
            found.append(f'{section}:{number}: {text}')
        found += prose_faults(section)
    found += orphan_faults(page, sections, library)
    visited = reached(page, sections, library)
    reached_sections = [section for section in sections if section.resolve() in visited]
    if arguments.repository is not None:
        files = listed_files(arguments.repository)
        if files is None:
            found.append(f'{arguments.repository}: is not a git checkout, whose files the check '
                         'reads')
        else:
            found += reference_faults(files, anchors(reached_sections))
    if arguments.readme is not None:
        found += readme_faults(arguments.readme)
    if arguments.complete:
        for section in sections:
            found += block_faults(section)
        found += completeness_faults(page, reached_sections, library)
    for fault in found:
        print(fault)
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
