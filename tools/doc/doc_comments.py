#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks the rules of webcpp's Doc Comments that MrDocs does not: every template parameter of a
public template has a @tparam, every symbol of a detail namespace has a brief, a public symbol's
brief is one sentence, and every symbol has a Doc Comment of its own.

Usage: doc_comments.py --library <name> --include <dir> [--clang <clang++>] -- <arguments>

clang++ reads the translation unit the arguments compile (the language standard, the include
paths, the defines and the source) and dumps, as JSON, the declarations of the namespace
webcpp::<name>. A declaration is checked when it is written in a header under the include
directory given, the library's own: one of another library, or of Boost, is not.

A declaration is public at namespace scope, or as a public member of a public class, outside any
namespace named detail. Each of its templates (of a function, a class, a partial specialization,
an alias, a variable or a concept, hidden friends and member templates included) documents each
of its named template parameters with @tparam, and names no other; the invented parameter of an
`auto` function parameter, and an unnamed one, cannot be named. A declaration under a namespace
named detail, at any depth, has a brief: its Doc Comment opens with a sentence. A public
symbol's brief, the first paragraph of its Doc Comment, which MrDocs shows whole as the brief, is
one sentence: it holds one `.`, `!` or `?` followed by a space or by its end, an abbreviation
such as e.g., i.e. or etc. and a code span (`x.y`, \\c x.y) not counting.

A Doc Comment is the one clang attaches, which MrDocs reads too; a declaration and its
redeclarations, such as an out-of-line definition, are one symbol, documented when any of them
is, with the template parameters of the one that holds the Doc Comment. clang attaches a comment
to every declaration that follows it until a `;`, `{`, `}`, `#` or `@`, so that in
`/** The x. */ int x, y;` and in an enumerator list `/** A. */ a, b,` the second declarator has
the first one's: the first symbol that takes a comment owns it, and another that gets the same
one has no Doc Comment of its own, a finding public or detail.

MrDocs reports the rest: a public symbol without a Doc Comment, a parameter without @param, and a
function without @return.

Each finding is printed as `<file>:<line>: <symbol>: <message>`. Exit 0 when there is none, 1
when there is one, 2 on a usage error or when clang++ cannot read the translation unit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Node = dict[str, Any]

COMPILER_PATHS = ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH')

FUNCTIONS = {'FunctionDecl', 'CXXMethodDecl', 'CXXConstructorDecl', 'CXXDestructorDecl',
             'CXXConversionDecl', 'CXXDeductionGuideDecl'}
RECORDS = {'CXXRecordDecl', 'ClassTemplateSpecializationDecl'}
TEMPLATES = {'FunctionTemplateDecl', 'ClassTemplateDecl', 'ClassTemplatePartialSpecializationDecl',
             'TypeAliasTemplateDecl', 'VarTemplateDecl', 'ConceptDecl'}
# The declarations each template declares, the first of which in its children is the templated
# one; the others are its instantiations.
TEMPLATED = {'FunctionTemplateDecl': FUNCTIONS, 'ClassTemplateDecl': {'CXXRecordDecl'},
             'TypeAliasTemplateDecl': {'TypeAliasDecl'}, 'VarTemplateDecl': {'VarDecl'}}
TEMPLATE_PARAMETERS = {'TemplateTypeParmDecl', 'NonTypeTemplateParmDecl',
                       'TemplateTemplateParmDecl'}
SYMBOLS = FUNCTIONS | RECORDS | TEMPLATES | {
    'EnumDecl', 'EnumConstantDecl', 'TypedefDecl', 'TypeAliasDecl', 'VarDecl', 'FieldDecl',
    'UsingDecl'}

# The commands that hold a brief, when a comment opens with one rather than with prose.
BRIEF_COMMANDS = {'brief', 'short'}

Finding = tuple[str, int, str]


@dataclass
class Symbol:
    """A declaration and its redeclarations: where the first is, and what they document."""

    name: str
    file: str
    line: int
    detail: bool
    comments: list[Node] = field(default_factory=list)
    # The named template parameters of the declaration that holds a Doc Comment, else of the
    # first; None when the symbol is no template.
    parameters: list[str] | None = None
    commented_parameters: bool = False
    # The symbol whose Doc Comment clang gave this one, which has none of its own.
    borrowed: str | None = None


class Locations:
    """Where each declaration of a dump is.

    clang's JSON dump writes a location's file only when it differs from the location written
    before it, and its line only when the file or the line does: the dump is read in its order
    to know them."""

    def __init__(self, objects: list[Node]) -> None:
        self.file: str | None = None
        self.line: int | None = None
        self.offset: int | None = None
        self.where: dict[int, tuple[str | None, int | None, int | None]] = {}
        for value in objects:
            self.read(value)

    def read(self, value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                self.read(item)
            return
        if not isinstance(value, dict):
            return
        if 'offset' in value:
            # A location: its includedFrom is the include stack, not a location.
            self.file = value.get('file', self.file)
            self.line = value.get('line', self.line)
            self.offset = value.get('offset')
            return
        for key, item in value.items():
            if key == 'includedFrom':
                continue
            self.read(item)
            if key == 'loc' and 'kind' in value:
                # A macro's expansion is written after its spelling: the declaration is where the
                # macro is used.
                self.where[id(value)] = (self.file, self.line, self.offset)

    def of(self, node: Node) -> tuple[str | None, int | None]:
        """The file and the line of node."""
        file, line, _ = self.where.get(id(node), (None, None, None))
        return file, line

    def at(self, node: Node) -> tuple[str | None, int | None]:
        """The file and the offset in it of node, which tell a comment from any other."""
        file, _, offset = self.where.get(id(node), (None, None, None))
        return file, offset


def comment_of(node: Node | None) -> Node | None:
    """The Doc Comment clang attaches to node, a FullComment among its children."""
    for child in (node or {}).get('inner', []):
        if child.get('kind') == 'FullComment':
            return child
    return None


def text_of(node: Node) -> str:
    """The text of a comment node and of everything under it."""
    return node.get('text', '') + ''.join(text_of(child) for child in node.get('inner', []))


def has_brief(comment: Node) -> bool:
    """Whether a Doc Comment opens with a brief: prose before any command, or @brief."""
    for child in comment.get('inner', []):
        kind = child.get('kind')
        if kind == 'ParagraphComment':
            if text_of(child).strip():
                return True
            continue
        if kind == 'BlockCommandComment' and child.get('name') in BRIEF_COMMANDS:
            return bool(text_of(child).strip())
        return False
    return False


def brief_of(comment: Node) -> str:
    """The text of a Doc Comment's brief: its first paragraph that holds prose, before any
    command, or its @brief; an inline command's argument (\\c x) is left out."""
    for child in comment.get('inner', []):
        kind = child.get('kind')
        if kind == 'ParagraphComment' and text_of(child).strip():
            return ' '.join(text_of(part) for part in child.get('inner', []))
        if kind == 'BlockCommandComment' and child.get('name') in BRIEF_COMMANDS:
            return text_of(child)
        if kind != 'ParagraphComment':
            return ''
    return ''


# What ends no sentence: a span of code, and an abbreviation.
CODE_SPAN = re.compile(r'`[^`]*`')
ABBREVIATION = re.compile(r'\b(?:e\.g|i\.e|etc|vs|cf)\.', re.IGNORECASE)
# A sentence's end: a ., ! or ? followed by a space or by the end of the text.
SENTENCE_END = re.compile(r'[.!?]+(?=\s|$)')


def sentences(text: str) -> int:
    """How many sentences text holds, as its sentence ends count them."""
    text = ABBREVIATION.sub('abbreviation', CODE_SPAN.sub('code', text))
    return len(SENTENCE_END.findall(text.strip()))


def documented_parameters(comment: Node) -> Iterator[str]:
    """The template parameters a Doc Comment names with @tparam."""
    stack = [comment]
    while stack:
        node = stack.pop()
        if node.get('kind') == 'TParamCommandComment' and node.get('param'):
            yield node['param']
        stack.extend(node.get('inner', []))


class Checker:
    """Reads the dump of a library's namespace and collects its symbols."""

    def __init__(self, objects: list[Node], include: Path) -> None:
        self.locations = Locations(objects)
        self.include = include.resolve()
        self.symbols: dict[tuple[str, ...], Symbol] = {}
        # The name of each class, by the id of its declarations, for the members defined out
        # of it.
        self.records: dict[str, str] = {}
        # The symbol of each declaration, by its id, for the redeclarations after it.
        self.keys: dict[str, tuple[str, ...]] = {}
        # The symbol that took each Doc Comment first, by the comment's file and offset.
        self.owners: dict[tuple[str | None, int | None], Symbol] = {}

    def ours(self, file: str | None) -> bool:
        """Whether the file is a header of the library's include directory."""
        if file is None:
            return False
        try:
            return Path(file).resolve().is_relative_to(self.include)
        except OSError:
            return False

    def visit(self, node: Node, path: list[str], detail: bool, public: bool) -> None:
        """Collects node and what it holds; path names the scope it is declared in."""
        kind = node.get('kind', '')
        if node.get('isImplicit'):
            return
        if kind == 'NamespaceDecl':
            name = node.get('name', '(anonymous)')
            for child in node.get('inner', []):
                self.visit(child, [*path, name], detail or name == 'detail', True)
            return
        if kind == 'LinkageSpecDecl':
            for child in node.get('inner', []):
                self.visit(child, path, detail, public)
            return
        if kind == 'FriendDecl':
            for child in node.get('inner', []):
                if child.get('kind') in FUNCTIONS | {'FunctionTemplateDecl'}:
                    self.visit(child, path, detail, public)
            return
        if node.get('access') in ('private', 'protected') or not public:
            return
        if kind not in SYMBOLS:
            return
        file, line = self.locations.of(node)
        if not self.ours(file) or file is None or line is None:
            return
        templated = self.templated(node)
        owner = self.records.get(node.get('parentDeclContextId', '')) \
            if node.get('previousDecl') or 'parentDeclContextId' in node else None
        name = '::'.join([owner] if owner else path)
        name = f'{name}::{node.get("name", "(anonymous)")}' if name else node.get('name', '')
        if kind == 'ClassTemplatePartialSpecializationDecl':
            name += ', a partial specialization'
        symbol = self.symbol(node, templated, name, file, line, detail)
        comment = comment_of(node) or comment_of(templated)
        if comment is not None:
            owner = self.owners.setdefault(self.locations.at(comment), symbol)
            if owner is symbol:
                symbol.comments.append(comment)
            else:
                symbol.borrowed = owner.name
                comment = None
        parameters = self.parameters(node) if kind in TEMPLATES else None
        if parameters is not None and (symbol.parameters is None or
                                       (comment is not None and not symbol.commented_parameters)):
            symbol.parameters = parameters
            symbol.commented_parameters = comment is not None
        record = templated if templated is not None and \
            templated.get('kind') in RECORDS else node
        if record.get('kind') in RECORDS | {'ClassTemplatePartialSpecializationDecl'}:
            self.records[record.get('id', '')] = name
            self.records[node.get('id', '')] = name
            self.members(record, name.split(', ')[0].split('::'), detail)
        if kind == 'EnumDecl':
            for child in node.get('inner', []):
                if child.get('kind') == 'EnumConstantDecl':
                    self.visit(child, name.split('::'), detail, True)

    def templated(self, node: Node) -> Node | None:
        """The declaration a template declares, the first of its children of that kind."""
        kinds = TEMPLATED.get(node.get('kind', ''))
        if kinds is None:
            return None
        for child in node.get('inner', []):
            if child.get('kind') in kinds:
                return child
        return None

    def parameters(self, node: Node) -> list[str]:
        """The named template parameters of a template, those clang did not invent."""
        return [child['name'] for child in node.get('inner', [])
                if child.get('kind') in TEMPLATE_PARAMETERS and child.get('name')
                and not child.get('isImplicit')]

    def symbol(self, node: Node, templated: Node | None, name: str, file: str, line: int,
               detail: bool) -> Symbol:
        """The symbol node declares, created on its first declaration: a redeclaration names the
        one before it, and a class declared before its definition is the same class. Overloads
        are told apart by their type."""
        declarations = [node] if templated is None else [node, templated]
        key = next((self.keys[declaration['previousDecl']] for declaration in declarations
                    if declaration.get('previousDecl') in self.keys), None)
        if key is None:
            kind = node.get('kind', '')
            if kind == 'ClassTemplateDecl' or kind in RECORDS:
                kind = 'record'
            key = (name, kind, (templated or node).get('type', {}).get('qualType', ''))
        for declaration in declarations:
            self.keys[declaration.get('id', '')] = key
        if key not in self.symbols:
            self.symbols[key] = Symbol(name, file, line, detail)
        return self.symbols[key]

    def members(self, record: Node, path: list[str], detail: bool) -> None:
        """Collects the members of a class, the public ones: those after `public:`, and every one
        of a struct or a union until an access specifier says otherwise."""
        if not record.get('completeDefinition'):
            return
        public = record.get('tagUsed', 'class') != 'class'
        for child in record.get('inner', []):
            if child.get('kind') == 'AccessSpecDecl':
                public = child.get('access') == 'public'
                continue
            access = child.get('access')
            self.visit(child, path, detail, public if access is None else access == 'public')

    def findings(self) -> list[Finding]:
        """Each finding, in the order of the files and lines."""
        found: list[Finding] = []
        for symbol in self.symbols.values():
            if symbol.borrowed is not None and not symbol.comments:
                found.append((symbol.file, symbol.line,
                              f'{symbol.name}: has no Doc Comment of its own; clang gives it the '
                              f'one of {symbol.borrowed}'))
                continue
            if symbol.detail:
                if not any(has_brief(comment) for comment in symbol.comments):
                    found.append((symbol.file, symbol.line,
                                  f'{symbol.name}: a detail symbol needs a brief, a Doc Comment '
                                  'that opens with a sentence saying what it is'))
                continue
            briefs = [sentences(brief_of(comment)) for comment in symbol.comments]
            if briefs and briefs[0] > 1:
                found.append((symbol.file, symbol.line,
                              f'{symbol.name}: the brief, the first paragraph of its Doc Comment, '
                              f'holds {briefs[0]} sentences; MrDocs shows that paragraph whole as '
                              'the brief, so keep one sentence there and start a paragraph for '
                              'the rest'))
            if symbol.parameters is None:
                continue
            documented = {name for comment in symbol.comments
                          for name in documented_parameters(comment)}
            for parameter in symbol.parameters:
                if parameter not in documented:
                    found.append((symbol.file, symbol.line,
                                  f'{symbol.name}: the template parameter {parameter} has no '
                                  '@tparam'))
            for parameter in sorted(documented - set(symbol.parameters)):
                found.append((symbol.file, symbol.line,
                              f'{symbol.name}: @tparam {parameter} names no template parameter'))
        return sorted(found, key=lambda finding: (finding[0], finding[1]))


def dump(clang: str, library: str, arguments: list[str]) -> list[Node]:
    """The declarations of webcpp::<library>, as clang++ dumps them for arguments."""
    command = [clang, '-fsyntax-only', '-Xclang', '-ast-dump=json', '-Xclang',
               f'-ast-dump-filter=webcpp::{library}', *arguments]
    environment = {name: value for name, value in os.environ.items()
                   if name not in COMPILER_PATHS}
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=environment, check=False)
    except OSError as error:
        raise Unreadable(f'cannot run {clang}: {error.strerror}') from error
    if completed.returncode != 0:
        raise Unreadable(f'clang++ could not read the headers ({" ".join(command)}):\n'
                         f'{completed.stderr}')
    text = completed.stdout
    decoder = json.JSONDecoder()
    objects = []
    position = 0
    while True:
        start = text.find('{', position)
        if start < 0:
            break
        value, position = decoder.raw_decode(text, start)
        objects.append(value)
    return objects


class Unreadable(Exception):
    """clang++ could not give the declarations to check."""


def check(clang: str, library: str, include: Path, arguments: list[str]) -> list[Finding]:
    """The findings of the library's headers under include, read through arguments."""
    objects = dump(clang, library, arguments)
    checker = Checker(objects, include)
    namespaces = [value for value in objects
                  if value.get('kind') == 'NamespaceDecl' and value.get('name') == library]
    if not any(checker.ours(checker.locations.of(value)[0]) for value in namespaces):
        raise Unreadable(f'no declaration of webcpp::{library} is in a header under {include}')
    for namespace in namespaces:
        checker.visit(namespace, ['webcpp'], False, True)
    return checker.findings()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description='Checks @tparam in public templates and the brief of detail symbols.')
    parser.add_argument('--library', required=True)
    parser.add_argument('--include', required=True, type=Path)
    parser.add_argument('--clang', default='clang++')
    parser.add_argument('arguments', nargs='+')
    options = parser.parse_args(argv)
    try:
        found = check(options.clang, options.library, options.include, options.arguments)
    except Unreadable as failure:
        print(f'doc_comments.py: {failure}')
        return 2
    for file, line, message in found:
        print(f'{file}:{line}: {message}')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
