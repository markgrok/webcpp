#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Writes a library's API reference with MrDocs, strict, and checks what MrDocs does not.

Usage: reference.py --library <name> --root <superproject> --output <reference.adoc>
    --mrdocs <mrdocs> --clang <clang++> --std <standard> [--include <dir>]...
    [--include-after <dir>]... [--define <macro>]...

The target webcpp.reference declares runs it, from the directory b2 runs in, with the include
directories and the defines of the library's target and of the requirements its doc Jamfile
gives (the native backend's dependencies, Emscripten's own headers for a header that builds only
on emscripten, the bindings of a WASI world), and the language standard of the build: one native
parse of every public header. A directory given with --include-after is searched after every one
of the host's (-idirafter): Emscripten's own headers hold some a host has too (uuid/uuid.h, GL/,
X11/), which must stay the host's. Beside the output it writes:

- aggregate.cpp, the library's aggregate translation unit, which tools/lint/compile_commands.py
  writes for the lint too: an include of every public header;
- compile_commands.json, that translation unit's one command, whose source root is
  ${MRDOCS_SOURCE_ROOT}, libs/<name>, and whose other include directories are system ones, those
  of --include-after searched last;
- mrdocs.yml, tools/doc/mrdocs.yml.in filled in for the library, with the keys of
  libs/<name>/doc/mrdocs.yml, when there is one, added: only keys of how the reference is
  presented, PRESENTATION below.

Then MrDocs writes the reference, and any warning fails it; and tools/doc/doc_comments.py checks
the @tparam of each public template and the brief of each detail symbol. Both run, and the
output is written only when both pass: MrDocs's text from the library's namespace on, without
the sections of the global namespace and of webcpp, which hold a table of one row each (a table
of the library's macros, which the first holds, becomes a section of its own), with each link
MrDocs writes inside another link's text, link:#a[handler<void(link:#b[bytes])>], written as its
text, since Asciidoctor would end the outer link at the inner ], and with the first row of each
table, which names its columns, marked as the table's header. The character
references MrDocs writes in place of the characters AsciiDoc could read as markup stay:
postprocess.mjs decodes them in the converted page, where nothing reads them as markup. One
goes before: an apostrophe of prose in a word, which AsciiDoc reads as no markup, is written
back as ', so that Asciidoctor makes it the curly one of the guide's prose.

MrDocs reads CPATH, CPLUS_INCLUDE_PATH and C_INCLUDE_PATH as a compiler does, so neither tool
sees them.

Exit 0 with the reference written; 1 when MrDocs or doc_comments.py finds a fault, or the
library's settings hold a key that is not one of how the reference is presented; 2 on a usage
error or a tool that does not run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'lint'))

import compile_commands
import doc_comments

SHARED = HERE / 'mrdocs.yml.in'

COMPILER_PATHS = ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH')

LIBRARY = re.compile(r'[a-z][a-z0-9_]*')

STANDARD = re.compile(r'[0-9][0-9a-z]')

# The keys a library's doc/mrdocs.yml may set: how its reference is presented, never what it
# documents or how strictly. Any other key, of mrdocs.yml.in or not, MrDocs's or not, is
# refused: the corpus (include-symbols, exclude-symbols, implementation-defined, see-below,
# file-patterns, exclude, the macros), the input, the output and every warning are every
# library's alike.
PRESENTATION = {'sort-members', 'sort-members-by', 'sort-namespace-members-by',
                'sort-members-ctors-1st', 'sort-members-dtors-1st',
                'sort-members-assignment-1st', 'sort-members-conversion-last',
                'sort-members-relational-last', 'overloads', 'sfinae', 'inherit-base-members',
                'inherit-hidden-friends', 'legible-names', 'show-enum-constants'}

# A top-level key of a YAML mapping, at the start of its line.
KEY = re.compile(r'([A-Za-z][\w-]*)\s*:(\s|$)')

# MrDocs's request for a bug report, which it prints after each warning when warnings are errors:
# it reports nothing of the library's, and is no bug.
BUG_REPORT = re.compile(r'\n*An issue occurred during execution\.\n'
                        r'If you believe this is a bug, please report it at \S+\n'
                        r'with the following details:\n(?:    .*\n?)*')

ANSI = re.compile(r'\x1b\[[0-9;]*m')

# The line that numbers a diagnostic of MrDocs's, under the location it is at.
DIAGNOSTIC = re.compile(r'^ {4}\d+\) ', re.MULTILINE)

# A table of MrDocs's, whose first row names its columns, "| Name| Description", which MrDocs
# does not mark as the header: Asciidoctor would show it as one more row.
NAMED_COLUMNS = re.compile(r'^\[cols="([^"]*)"\]\n\|===\n\| Name\b', re.MULTILINE)

# A section of MrDocs's reference: its anchor, [#<anchor>], then its title, == <title>.
SECTION = re.compile(r'^\[#([^\]\n]+)\]\n== ', re.MULTILINE)

# The sections of the global namespace, [#index], and of webcpp, which hold a table of one row,
# the way to the library's namespace; and a link to either, which every title of the reference
# holds.
DROPPED = ('index', 'webcpp')
DROPPED_LINK = re.compile(r'link:#(?:index|webcpp)\[([^\]]*)\]')

# A link inside another link's text, which MrDocs writes for a type named among another's
# template arguments, link:#a[handler&lt;void(link:#b[bytes])&gt;]: Asciidoctor would end the
# outer link at the inner ]. The outer link and the text before the inner one, then its text.
NESTED_LINK = re.compile(r'(\blink:[^\s\[]*\[[^\[\]]*)\blink:[^\s\[]*\[([^\[\]]*)\]')

# The table of the macros, in the section of the global namespace: from its title to the next.
MACROS = re.compile(r'^=== Macros\n(.*?)(?=^=== |\Z)', re.MULTILINE | re.DOTALL)


# An apostrophe MrDocs wrote as a reference in a word, between a letter or a digit and a letter:
# the one Asciidoctor's replacements make curly in the guide, ([[:alnum:]])'(?=[[:alpha:]]).
APOSTROPHE = re.compile(r'(?<=[^\W_])&apos;(?=[^\W\d_])')

# The line that opens or closes a block AsciiDoc shows as written: a listing, a literal, a
# passthrough or a comment.
VERBATIM = re.compile(r'(-{4,}|\.{4,}|\+{4,}|/{4,})')

# What of a paragraph holds no apostrophe of prose, Asciidoctor's replacements reading it or not:
# code, between two backticks or two pairs of them; a passthrough, +...+, ++...++, +++...+++ or
# pass:[...], the one group a match names; and a link's target or a URL. MrDocs writes a
# literal backtick as &grave; and a + as &plus;, so each of its own is markup.
UNREAD = re.compile(r'``.*?``|`[^`]*`'
                    r'|(\+\+\+.*?\+\+\+|\+\+.*?\+\+|\+[^+]*\+|pass:[a-z,]*\[[^\]]*\])'
                    r'|\b(?:link|xref|mailto):[^\s\[]*|\b(?:https?|ftp|irc|file)://[^\s\[\]]*',
                    re.DOTALL)


def prose_apostrophes(paragraph: str) -> str:
    """The paragraph with each apostrophe MrDocs wrote in a word of its prose written as ', and
    each of a passthrough too: Asciidoctor shows a passthrough as written, its replacements
    never reading it, and +...+ would show the reference itself, its & escaped. Code, a link's
    target and a URL keep their &apos;."""
    pieces = []
    position = 0
    for match in UNREAD.finditer(paragraph):
        pieces.append(APOSTROPHE.sub("'", paragraph[position:match.start()]))
        kept = match.group(0)
        pieces.append(kept.replace('&apos;', "'") if match.group(1) else kept)
        position = match.end()
    pieces.append(APOSTROPHE.sub("'", paragraph[position:]))
    return ''.join(pieces)


def apostrophes(text: str) -> str:
    """MrDocs's text with each apostrophe of prose in a word written as ', which Asciidoctor then
    makes curly as it does the guide's. An apostrophe Asciidoctor would read in code, in a
    passthrough, in a link's target or a URL, or in a verbatim block keeps its &apos;, which
    shows straight: a synopsis's link text, which Asciidoctor's replacements read, among them.
    Each paragraph is read alone, so a backtick that does not close ends with its paragraph."""
    lines: list[str] = []
    paragraph: list[str] = []
    delimiter: Optional[str] = None

    def flush() -> None:
        if paragraph:
            lines.append(prose_apostrophes('\n'.join(paragraph)))
            paragraph.clear()

    for line in text.split('\n'):
        if delimiter is not None:
            delimiter = None if line == delimiter else delimiter
            lines.append(line)
        elif VERBATIM.fullmatch(line):
            flush()
            delimiter = line
            lines.append(line)
        elif not line.strip():
            flush()
            lines.append(line)
        else:
            paragraph.append(line)
    flush()
    return '\n'.join(lines)


def unnested(text: str) -> str:
    """The text with each link inside another link's text written as its text alone, the outer
    link kept, as many in one as it holds."""
    while True:
        flat = NESTED_LINK.sub(lambda link: link.group(1) + link.group(2), text)
        if flat == text:
            return text
        text = flat


def finished(text: str, library: str) -> str:
    """MrDocs's reference as the page shows it: from the library's namespace, the sections of the
    global namespace and of webcpp left out, but for the table of the library's macros, which
    becomes a section of its own; each link to them their text; each link inside another's text
    its text; and the first row of each table, which names its columns, the table's header; and
    each apostrophe of its prose in a word as Asciidoctor reads the guide's."""
    starts = [match.start() for match in SECTION.finditer(text)]
    kept = [text[:starts[0]] if starts else text]
    for start, end in zip(starts, [*starts[1:], len(text)]):
        section = text[start:end]
        anchor = SECTION.match(section)
        if anchor is None or anchor.group(1) not in DROPPED:
            kept.append(section)
            continue
        macros = MACROS.search(section) if anchor.group(1) == 'index' else None
        if macros is not None:
            kept.append(f'[#webcpp-{library}-macros]\n== Macros\n\n{macros.group(1).strip()}\n\n')
    shown = unnested(DROPPED_LINK.sub(lambda link: link.group(1), ''.join(kept)))
    return apostrophes(NAMED_COLUMNS.sub(
        lambda table: f'[%header,cols="{table.group(1)}"]\n|===\n| Name', shown))


class Failure(Exception):
    """A fault of the library, said to the user; the reference fails with status 1."""


class Broken(Exception):
    """A tool or a setting that does not work, said to the user; status 2."""


Block = tuple[Optional[str], int, list[str]]


def blocks(text: str, origin: Path) -> list[Block]:
    """The top-level keys of a YAML mapping, each with its line and its lines: the comments and
    blank lines before it, its own, and those under it. The comments after the last key are a
    block without a key."""
    found: list[Block] = []
    pending: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        key = KEY.match(line)
        if key is not None:
            found.append((key.group(1), number, [*pending, line]))
            pending = []
        elif not line.strip() or line.startswith('#'):
            pending.append(line)
        elif line[0] in ' \t-' and found and found[-1][0] is not None:
            # An indented line, or an item of a list at the key's own indentation.
            found[-1][2].extend([*pending, line])
            pending = []
        else:
            raise Broken(f'{origin}:{number}: not a top-level key of a YAML mapping: {line}')
    if pending:
        found.append((None, 0, pending))
    return found


def settings(library: str, values: dict[str, str], override: Path | None) -> str:
    """The text of mrdocs.yml: the shared settings filled in with values, @NAME@ by values[NAME],
    with the keys of override, each a key of PRESENTATION, in place of the same keys, or added."""
    shared = SHARED.read_text()
    for name, value in values.items():
        shared = shared.replace(f'@{name}@', value)
    left = re.search(r'@[A-Z_]+@', shared)
    if left is not None:
        raise Broken(f'{SHARED}: {left.group(0)} is not filled in')
    replaced: dict[str, Block] = {}
    if override is not None:
        for block in blocks(override.read_text(), override):
            key, number, _ = block
            if key is None:
                continue
            if key not in PRESENTATION:
                raise Failure(f'{override}:{number}: {key} is not a setting a library may give '
                              'its reference: a library chooses how its reference is presented, '
                              f'with {", ".join(sorted(PRESENTATION))}; what it documents and '
                              'how strictly are tools/doc/mrdocs.yml.in\'s, every library\'s')
            replaced[key] = block
    lines = [f'# Written by tools/doc/reference.py for {library}: tools/doc/mrdocs.yml.in, with '
             f'the keys of {override}.' if override else
             f'# Written by tools/doc/reference.py for {library}: tools/doc/mrdocs.yml.in.']
    for key, _, text in blocks(shared, SHARED):
        lines += replaced.pop(key)[2] if key in replaced else text
    for _, _, text in replaced.values():
        lines += text
    return '\n'.join(lines) + '\n'


def quoted(path: Path) -> str:
    """A path as a YAML scalar: a JSON string is a double-quoted YAML one."""
    return json.dumps(str(path))


def environment() -> dict[str, str]:
    """This process's environment, without the variables a compiler reads include paths from."""
    return {name: value for name, value in os.environ.items() if name not in COMPILER_PATHS}


def run_mrdocs(mrdocs: str, config: Path, output: Path) -> list[str]:
    """Runs MrDocs with config, and returns what it reported when it failed, else nothing."""
    try:
        completed = subprocess.run([mrdocs, f'--config={config}'], cwd=config.parent,
                                   env=environment(), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors='replace',
                                   check=False)
    except OSError as error:
        raise Broken(f'cannot run MrDocs, {mrdocs}: {error.strerror}') from error
    said = ANSI.sub('', completed.stdout)
    reported = BUG_REPORT.sub('\n', said).strip()
    if completed.returncode == 0 and output.is_file():
        return []
    if completed.returncode == 0:
        return [reported, f'reference.py: MrDocs wrote no {output}']
    count = len(DIAGNOSTIC.findall(reported))
    if count == 0:
        # Not a fault of the library's Doc Comments: all MrDocs said is shown.
        return [said.strip(), f'reference.py: MrDocs failed with status {completed.returncode}']
    return [reported, f'reference.py: MrDocs reported {count} '
            f'{"fault" if count == 1 else "faults"} in the Doc Comments above: every public '
            'symbol has a Doc Comment, with @param for each parameter and @return for a '
            'function that returns a value']


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description='Writes a library\'s reference with MrDocs.')
    parser.add_argument('--library', required=True)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--mrdocs', required=True)
    parser.add_argument('--clang', required=True)
    parser.add_argument('--std', required=True)
    parser.add_argument('--include', action='append', default=[])
    parser.add_argument('--include-after', action='append', default=[])
    parser.add_argument('--define', action='append', default=[])
    options = parser.parse_args(argv)
    library: str = options.library
    if not LIBRARY.fullmatch(library):
        parser.error(f'--library {library} is not a library\'s name')
    if not STANDARD.fullmatch(options.std):
        parser.error(f'--std {options.std} is not a C++ standard, such as 20')
    try:
        return reference(options)
    except Failure as failure:
        print(f'reference.py: {failure}')
        return 1
    except Broken as broken:
        print(f'reference.py: {broken}')
        return 2


def reference(options: argparse.Namespace) -> int:
    """Writes the reference the options describe, and returns the exit status."""
    library: str = options.library
    root = options.root.resolve()
    source_root = root / 'libs' / library
    include = source_root / 'include'
    output = Path(os.path.abspath(options.output))
    work = output.parent
    work.mkdir(parents=True, exist_ok=True)
    if not compile_commands.public_headers(str(root), library):
        raise Broken(f'{include} holds neither webcpp/{library}.hpp nor a header under '
                     f'webcpp/{library}/')
    aggregate = work / 'aggregate.cpp'
    compile_commands.write_aggregate(str(root), library, str(aggregate))

    # The library's own headers are read as the library's; every other include directory, as
    # Boost's, is a system one.
    others = []
    for directory in options.include:
        absolute = Path(os.path.abspath(directory))
        if absolute.resolve() != include.resolve() and absolute not in others:
            others.append(absolute)
    flags = [f'-std=c++{options.std}', *(f'-D{macro}' for macro in options.define)]
    systems = [word for directory in others for word in ('-isystem', str(directory))]
    systems += [word for directory in options.include_after
                for word in ('-idirafter', os.path.abspath(directory))]
    database = work / 'compile_commands.json'
    database.write_text(json.dumps([{
        'directory': '${MRDOCS_SOURCE_ROOT}',
        'file': str(aggregate),
        'arguments': ['clang++', *flags, '-I${MRDOCS_SOURCE_ROOT}/include', *systems, '-c',
                      str(aggregate)],
    }], indent=4) + '\n')

    written = work / 'reference.mrdocs.adoc'
    written.unlink(missing_ok=True)
    override = source_root / 'doc/mrdocs.yml'
    config = work / 'mrdocs.yml'
    config.write_text(settings(library, {
        'LIBRARY': library,
        'MACROS': f'WEBCPP_{library.upper()}_',
        'SOURCE_ROOT': quoted(source_root),
        'DATABASE': quoted(database),
        'INPUT': quoted(include),
        'OUTPUT': quoted(written),
    }, override if override.is_file() else None))

    faults = run_mrdocs(options.mrdocs, config, written)
    try:
        found = doc_comments.check(options.clang, library, include,
                                   [*flags, f'-I{include}', *systems, str(aggregate)])
    except doc_comments.Unreadable as unreadable:
        print('\n'.join([*faults, f'reference.py: doc_comments.py: {unreadable}']))
        return 2
    for file, line, message in found:
        faults.append(f'{file}:{line}: {message}')
    if found:
        faults.append(f'reference.py: doc_comments.py reported {len(found)} '
                      f'{"fault" if len(found) == 1 else "faults"} above: every template '
                      'parameter of a public template has a @tparam, and every detail symbol a '
                      'brief')
    if faults:
        print('\n'.join(faults))
        return 1
    shown = work / 'reference.finished.adoc'
    shown.write_text(finished(written.read_text(), library))
    os.replace(shown, output)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
