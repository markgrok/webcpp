#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""The rules of tools/lint/lint.sh that read a file the way its language does, not line by line.

Usage: rules.py <rule> < paths

The paths, relative to the current directory and separated by NUL bytes, come on the standard
input, and the rule reads those it applies to. Each finding is printed as `path:line: message`.
Exit 0 when there is none, 1 when there is one, 2 on a usage error.

  licence       every source file opens with the WebCpp.org licence notice;
  raw-rules     a library's test or example Jamfile declares its programs only with the rules of
                tools/webcpp.jam;
  doc-comments  a Doc Comment uses only the commands webcpp allows, no bare @, and no reference
                that a colon or a possessive follows;
  line-length   no line of a Python file is longer than 100 columns, .clang-format's ColumnLimit.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Iterator
from pathlib import PurePosixPath

Finding = tuple[str, int, str]

# The notice, without its comment markers. The year may be any year, or a range of years.
COPYRIGHT = re.compile(r'Copyright \(c\) \d{4}(-\d{4})? WebCpp\.org')
NOTICE = ('',
          'Distributed under the Boost Software License, Version 1.0. (See',
          'accompanying file LICENSE_1_0.txt or copy at',
          'https://www.boost.org/LICENSE_1_0.txt)')


def comment_marker(path: str) -> str | None:
    """The comment marker the notice takes in the file at path, or None when it needs none."""
    name = PurePosixPath(path).name
    if name.endswith(('.hpp', '.cpp', '.mjs')):
        return '//'
    if name.endswith(('.py', '.sh', '.jam', '.yml', '.yaml')) or name in ('Jamroot', 'Jamfile'):
        return '#'
    return None


def licence(path: str, text: str) -> Iterator[Finding]:
    """A source file opens with the notice, after its #! line when it has one."""
    marker = comment_marker(path)
    if marker is None:
        return
    lines = text.splitlines()
    first = 1 if lines and lines[0].startswith('#!') else 0
    expected = [None, *(f'{marker} {line}' if line else marker for line in NOTICE)]
    for number, wanted in enumerate(expected, first):
        line = lines[number] if number < len(lines) else ''
        if wanted is None:
            matches = line.startswith(f'{marker} ') and COPYRIGHT.fullmatch(
                line[len(marker) + 1:]) is not None
        else:
            matches = line == wanted
        if not matches:
            yield (path, number + 1, f'the file does not open with the licence notice, "{marker} '
                   f'Copyright (c) 2026 WebCpp.org" and the Boost Software License; this line '
                   f'reads {line!r}')
            return


# b2's rules that declare a program, each with the rule of tools/webcpp.jam that replaces it.
RAW_RULES = {
    'run': 'webcpp.run',
    'run-fail': 'webcpp.run-fail',
    'compile': 'webcpp.compile',
    'compile-fail': 'webcpp.compile-fail',
    'exe': 'webcpp.example or webcpp.run',
    'unit-test': 'webcpp.run',
}

# The names b2 loads as a directory's Jamfile.
JAMFILE = re.compile(r'[Bb]uild\.jam|[Jj]amfile(\.v2|\.jam)?')

# Where a library's test and example Jamfiles are: under libs/<name>/test and example, and
# under the same directories of a fixture library, which the tests of the build place in libs/.
LIBRARY_JAMFILE = re.compile(r'(libs|tools/test/fixtures)/[^/]+/(test|example)/.+')

# The tokens after which a Jam statement starts, whose first token is the rule it invokes; `[`
# starts an invocation inside a statement.
STATEMENT_STARTS = {';', '{', '}', '[', 'else'}

# The second token of a statement that assigns the variable its first token names (`run = 1 ;`,
# `run on $(target) = 1 ;`) rather than invoke the rule of that name.
ASSIGNMENTS = {'=', '+=', '-=', '?=', 'default', 'on'}


def jam_tokens(text: str) -> Iterator[tuple[str, int]]:
    """Each token of the Jam text with the line it starts on, without comments, # to the end of
    the line or #| to |#.

    The body of an actions block is shell text: it is skipped, and its closing brace is the token
    that ends the block."""
    position = 0
    line = 1
    previous = ';'
    while position < len(text):
        character = text[position]
        if character.isspace():
            line += character == '\n'
            position += 1
            continue
        if text.startswith('#|', position):
            # A block comment, to its |#, which b2 reads as Jam's.
            end = text.find('|#', position + 2)
            end = len(text) if end < 0 else end + 2
            line += text.count('\n', position, end)
            position = end
            continue
        if character == '#':
            end = text.find('\n', position)
            position = len(text) if end < 0 else end
            continue
        start, quoted = line, False
        token = position
        while position < len(text) and (quoted or not text[position].isspace()):
            if text[position] == '\\':
                position += 1
            elif text[position] == '"':
                quoted = not quoted
            line += text[position:position + 1] == '\n'
            position += 1
        word = text[token:position]
        yield word, start
        if word == 'actions' and previous in STATEMENT_STARTS:
            depth = 0
            while position < len(text):
                character = text[position]
                line += character == '\n'
                position += 1
                if character == '{':
                    depth += 1
                elif character == '}' and depth > 0:
                    depth -= 1
                    if depth == 0:
                        break
            word = '}'
            yield word, line
        previous = word


def raw_rules(path: str, text: str) -> Iterator[Finding]:
    """A library's test or example Jamfile invokes none of b2's rules that declare a program, as
    a statement or inside [ ], bare or through a module other than webcpp (testing.run). A
    statement that assigns a variable of that name invokes nothing."""
    if not JAMFILE.fullmatch(PurePosixPath(path).name) or not LIBRARY_JAMFILE.fullmatch(path):
        return
    tokens = list(jam_tokens(text))
    statement = True
    case_pattern = False
    for index, (word, line) in enumerate(tokens):
        following = tokens[index + 1][0] if index + 1 < len(tokens) else ''
        if statement and following not in ASSIGNMENTS:
            # Jam removes the quotes of a token: "run" invokes run.
            module, _, rule = word.replace('"', '').rpartition('.')
            if rule in RAW_RULES and module != 'webcpp':
                yield (path, line, f'{word} is b2\'s own rule; a test or example Jamfile declares '
                       f'its programs with the rules of tools/webcpp.jam, here {RAW_RULES[rule]}')
        # `case <pattern> :` is followed by a statement.
        if case_pattern and word == ':':
            statement, case_pattern = True, False
            continue
        case_pattern = case_pattern or (statement and word == 'case')
        statement = word in STATEMENT_STARTS


# The Doc Comment commands webcpp uses, each of which MrDocs renders. MrDocs drops @sa,
# @deprecated, @since, @todo and @retval without a word, and an @ that starts no command
# confuses its parser.
DOC_COMMANDS = {'brief', 'param', 'tparam', 'return', 'returns', 'throws', 'pre', 'post', 'note',
                'see', 'code', 'endcode', 'details', 'par', 'copydoc', 'ref'}

# The characters that clang's comment parser, which MrDocs uses, reads literally after a
# backslash: \@ is a literal @.
DOC_ESCAPES = set('\\@&$#<>%".:|-')

DOC_COMMAND_LIST = ', '.join(f'@{command}' for command in sorted(DOC_COMMANDS))

COMMAND = re.compile(r'[A-Za-z]+')

IDENTIFIER = re.compile(r'[A-Za-z0-9_]+')

NUMBER = re.compile(r"[A-Za-z0-9_.']+")

# What @ref or \ref takes for its argument, as clang's comment parser reads it: the word after
# the spaces that follow the command, up to the next space.
REF_ARGUMENT = re.compile(r'\s+(\S+)')

# The apostrophes of a possessive, ASCII and typographic.
APOSTROPHES = "'\u2019"

# A raw string literal's opening, up to its parenthesis: R"delimiter(.
RAW_STRING = re.compile(r'(?<![A-Za-z0-9_])(?:u8|[uUL])?R"([^()\\\s]{0,16})\(')

Character = tuple[str, int]


def doc_comments_of(text: str) -> Iterator[list[Character]]:
    """Each Doc Comment of the C++ text as its characters, each with its line.

    A Doc Comment is a /** */ or /*! */ block, or a run of /// or //! comments on consecutive
    lines, which clang reads as one. A marker inside a string or a character literal, raw or not,
    opens nothing, and neither does a digit separator: 1'000."""
    position = 0
    line = 1
    run: list[Character] = []
    run_line = 0
    while position < len(text):
        character = text[position]
        if character.isspace():
            line += character == '\n'
            position += 1
            continue
        if run and not text.startswith('//', position):
            yield run
            run = []
        if text.startswith('//', position):
            end = text.find('\n', position)
            end = len(text) if end < 0 else end
            body = text[position + 2:end]
            if body[:1] in ('/', '!') and not body.startswith('//'):
                if run and line != run_line + 1:
                    yield run
                    run = []
                run.extend((part, line) for part in body[1:] + '\n')
                run_line = line
            elif run:
                yield run
                run = []
            position = end
            continue
        if text.startswith('/*', position):
            end = text.find('*/', position + 2)
            end = len(text) if end < 0 else end
            body = text[position + 2:end]
            comment: list[Character] = []
            for part in body:
                comment.append((part, line))
                line += part == '\n'
            if body[:1] in ('*', '!') and not body.startswith('**') and body != '*':
                yield comment[1:]
            position = end + 2
            continue
        raw = RAW_STRING.match(text, position) if character in 'uULR' else None
        if raw:
            close = text.find(f'){raw.group(1)}"', raw.end())
            close = len(text) if close < 0 else close + len(raw.group(1)) + 2
            line += text.count('\n', position, close)
            position = close
            continue
        if character in '"\'':
            # The literal ends at its closing quote, or at a newline that no backslash splices:
            # the apostrophe of an #error opens one that never closes. The newline is left to
            # the loop, which counts it, as it counts a spliced one here.
            position += 1
            while position < len(text) and text[position] not in (character, '\n'):
                if text[position] == '\\':
                    line += text[position + 1:position + 2] == '\n'
                    position += 1
                position += 1
            if text[position:position + 1] == character:
                position += 1
            continue
        if character.isalnum() or character == '_':
            # A number may hold digit separators, which an identifier cannot.
            word = NUMBER if character.isdigit() else IDENTIFIER
            matched = word.match(text, position)
            position = matched.end() if matched else position + 1
            continue
        position += 1
    if run:
        yield run


def reference_faults(command: str, argument: str) -> Iterator[str]:
    """What is wrong with the argument of a reference, @ref or \\ref, which is the name alone: a
    colon after it, which MrDocs drops from the page, and a possessive, which leaves the name to
    MrDocs's own trimming of what follows it."""
    if argument.endswith(':'):
        yield (f'{command} {argument} MrDocs drops the colon that follows a reference; reword the '
               'sentence so that no colon follows it')
    if any(apostrophe in argument for apostrophe in APOSTROPHES):
        yield (f'{command} {argument}: a possessive after a reference; write "the <member> of '
               f'{command} <name>"')


def doc_comments(path: str, text: str) -> Iterator[Finding]:
    """Every command of a Doc Comment, @name or \\name, is one of DOC_COMMANDS, and an @ that
    starts no command is written \\@; a reference, @ref or \\ref, is followed neither by a colon
    nor by a possessive. What lies between @code and @endcode is verbatim."""
    if not path.endswith(('.hpp', '.cpp')):
        return
    for comment in doc_comments_of(text):
        characters = ''.join(character for character, _ in comment)
        verbatim = False
        index = 0
        while index < len(characters):
            character = characters[index]
            index += 1
            if character not in '@\\':
                continue
            if character == '\\' and characters[index:index + 1] in DOC_ESCAPES:
                index += 1
                continue
            line = comment[index - 1][1]
            name = COMMAND.match(characters, index)
            if name is None:
                if character == '@' and not verbatim:
                    yield (path, line, 'a bare @ in a Doc Comment; write \\@ for a literal one')
                continue
            command = name.group(0)
            index = name.end()
            if verbatim:
                verbatim = command != 'endcode'
            elif command == 'code':
                verbatim = True
            elif command == 'ref':
                argument = REF_ARGUMENT.match(characters, index)
                if argument is not None:
                    for message in reference_faults(f'{character}ref', argument.group(1)):
                        yield (path, line, message)
            elif command not in DOC_COMMANDS:
                yield (path, line, f'{character}{command} is not a Doc Comment command webcpp '
                       f'uses; write \\{character} for a literal {character}')


LINE_LIMIT = 100


def line_length(path: str, text: str) -> Iterator[Finding]:
    """No line of a Python file is longer than LINE_LIMIT columns."""
    if not path.endswith('.py'):
        return
    for number, line in enumerate(text.splitlines(), 1):
        if len(line) > LINE_LIMIT:
            yield (path, number, f'{len(line)} columns, over the limit of {LINE_LIMIT}')


RULES: dict[str, Callable[[str, str], Iterator[Finding]]] = {
    'licence': licence,
    'raw-rules': raw_rules,
    'doc-comments': doc_comments,
    'line-length': line_length,
}

# What a rule prints once after its findings.
NOTES = {
    'doc-comments': f'The Doc Comment commands webcpp uses are {DOC_COMMAND_LIST}.',
}


def main(arguments: list[str]) -> int:
    if len(arguments) != 1 or arguments[0] not in RULES:
        print(f'usage: rules.py {"|".join(RULES)} < paths', file=sys.stderr)
        return 2
    rule = RULES[arguments[0]]
    found = False
    for path in sys.stdin.buffer.read().decode().split('\0'):
        if not path:
            continue
        with open(path, encoding='utf-8', errors='replace') as file:
            text = file.read()
        for where, line, message in rule(path, text):
            print(f'{where}:{line}: {message}')
            found = True
    if found and arguments[0] in NOTES:
        print(NOTES[arguments[0]])
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
