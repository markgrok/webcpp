#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Writes the compilation database of a superproject: what b2 compiles for the libraries'
tests and examples, and one aggregate translation unit per library.

Usage: compile_commands.py <root> <out>

b2 5.5.3's --command-database writes nothing, so its dry run (b2 -n -a) is read instead, from
root, with the host's default toolset: `test example`, every library's programs, then
`exception-handling=off /webcpp//throw_exception`, the superproject's handler as a program built
without exceptions links it. Every line that compiles a .cpp file of the source tree becomes an
entry of <out>, once per distinct command. Three kinds of line are left out:

- a source b2 generates under bin/, the Jamroot's build directory, which is not ours to analyse;
- a source b2 expects not to compile (webcpp.compile-fail): the dry run prints its object as a
  `(failed-as-expected)` marker, and an analysis would stop at the error the test exists to
  show. A run-fail test's marker is its .run file: its sources compile, and are analysed;
- the same source compiled again with the same options, under another name.

The aggregate translation unit of a library includes every public header, webcpp/<name>.hpp and
each .hpp under webcpp/<name>/, the headers webcpp.headers-alone checks. It is compiled with the
command of the library's headers-alone translation units, which are exactly a public header's:
a header that no test includes is still analysed, and a tool that reads the library's interface
(MrDocs) reads one translation unit. It is written as bin/aggregate/<name>.cpp, inside the tree,
since clang-tidy takes its configuration from the .clang-tidy nearest a source file.

b2 runs with root/.local/user-config.jam when it exists, else with $WEBCPP_USER_CONFIG when it
is set, else with its own search; and without CPATH, CPLUS_INCLUDE_PATH and C_INCLUDE_PATH,
which the Jamroot refuses.

Exit 0 with the database written; 1 when b2 fails, when a library has public headers but no
headers-alone translation unit, or when nothing at all is compiled; 2 on a usage error.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

# The b2 requests whose compile lines the database holds.
REQUESTS = (['test', 'example'], ['exception-handling=off', '/webcpp//throw_exception'])

# The Jamroot's build-dir, where b2 writes what it generates.
BUILD_DIR = 'bin'

COMPILER_PATHS = ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH')

MARKER = re.compile(r'^\(failed-as-expected\) (.+)$')

# A translation unit of webcpp.headers-alone: bin/libs/<library>/.../alone-<header>.cpp.
ALONE = re.compile(rf'^{BUILD_DIR}/libs/([^/]+)/.*/alone-[^/]+\.cpp$')


class Failure(Exception):
    """What stops the database from being written, said to the user."""


def b2_command(root: str) -> list[str]:
    """b2, with the user-config.jam this superproject uses."""
    local = os.path.join(root, '.local', 'user-config.jam')
    configured = os.environ.get('WEBCPP_USER_CONFIG')
    if os.path.isfile(local):
        return ['b2', f'--user-config={local}']
    if configured:
        return ['b2', f'--user-config={os.path.abspath(configured)}']
    return ['b2']


def dry_run(root: str, request: list[str]) -> list[str]:
    """The lines b2 prints for a dry run of request, in root; b2's failure is a Failure."""
    environment = {name: value for name, value in os.environ.items()
                   if name not in COMPILER_PATHS}
    command = [*b2_command(root), '-n', '-a', *request]
    try:
        completed = subprocess.run(command, cwd=root, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, check=False)
    except OSError as error:
        raise Failure(f'cannot run b2: {error.strerror}') from error
    if completed.returncode != 0:
        raise Failure(f'{completed.stdout}{" ".join(command)} exited {completed.returncode}')
    return completed.stdout.splitlines()


def compiles(lines: list[str]) -> list[list[str]]:
    """The commands of lines that compile a .cpp file, as words, without those b2 expects to
    fail: a compile-fail test's, whose object is itself a `(failed-as-expected)` marker. A
    run-fail test's marker is its .run file, so its sources stay."""
    commands = [shlex.split(line) for line in lines
                if ' -c ' in line and line.rstrip().endswith('.cpp"')]
    failing = {marker.group(1) for marker in map(MARKER.match, lines) if marker}
    return [words for words in commands if output_of(words) not in failing]


def output_of(words: list[str]) -> str:
    """The object file a compile command writes."""
    return words[words.index('-o') + 1] if '-o' in words else ''


def without_output(words: list[str]) -> list[str]:
    """The command without its object file, which names the program it is compiled for."""
    if '-o' not in words:
        return words
    index = words.index('-o')
    return words[:index] + words[index + 2:]


def public_headers(root: str, library: str) -> list[str]:
    """The headers webcpp.headers-alone checks, as they are included: webcpp/<library>.hpp."""
    include = Path(root, 'libs', library, 'include')
    headers = [include / 'webcpp' / f'{library}.hpp']
    headers += (include / 'webcpp' / library).rglob('*.hpp')
    return sorted(header.relative_to(include).as_posix() for header in headers if header.is_file())


def aggregate(root: str, library: str, alone: list[str]) -> dict[str, object]:
    """The entry of the library's aggregate translation unit, after writing it.

    Lint shards running at once write the same text: each writes a file of its own, and renames
    it over the aggregate."""
    directory = os.path.join(root, BUILD_DIR, 'aggregate')
    os.makedirs(directory, exist_ok=True)
    source = os.path.join(directory, f'{library}.cpp')
    includes = ''.join(f'#include <{header}>\n' for header in public_headers(root, library))
    written = f'{source}.{os.getpid()}'
    with open(written, 'w') as file:
        file.write(f'// Every public header of {library}, written by compile_commands.py.\n'
                   f'{includes}')
    os.replace(written, source)
    arguments = alone[:-1] + [source]
    arguments[arguments.index('-o') + 1] = source.removesuffix('.cpp') + '.o'
    return {'directory': root, 'file': source, 'arguments': arguments}


def libraries(root: str) -> list[str]:
    """The libraries the Jamroot registers: each directory of libs/ with a build.jam."""
    return sorted(build.parent.name for build in Path(root, 'libs').glob('*/build.jam'))


def database(root: str) -> list[dict[str, object]]:
    """The entries of the database of root, after writing the aggregates."""
    entries: list[dict[str, object]] = []
    seen: set[tuple[str, ...]] = set()
    alone: dict[str, list[str]] = {}
    for request in REQUESTS:
        for words in compiles(dry_run(root, request)):
            source = words[-1]
            generated = ALONE.match(source)
            if generated:
                alone.setdefault(generated.group(1), words)
            key = tuple(without_output(words))
            if source.startswith(f'{BUILD_DIR}/') or key in seen:
                continue
            seen.add(key)
            entries.append({'directory': root, 'file': os.path.join(root, source),
                            'arguments': words})
    for library in libraries(root):
        if not public_headers(root, library):
            continue
        if library not in alone:
            raise Failure(f'libs/{library}: b2 compiles no translation unit of '
                          f'webcpp.headers-alone for it natively, whose command its aggregate '
                          f'translation unit takes; declare `webcpp.headers-alone {library} : '
                          f'../include ;` in libs/{library}/test/Jamfile')
        entries.append(aggregate(root, library, alone[library]))
    if not entries:
        raise Failure('b2 compiled no .cpp file, not even tools/throw_exception.cpp; is its '
                      'dry run printed another way?')
    return entries


def main(arguments: list[str]) -> int:
    if len(arguments) != 2:
        print('usage: compile_commands.py <root> <out>', file=sys.stderr)
        return 2
    root, out = (os.path.abspath(argument) for argument in arguments)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:
        entries = database(root)
    except Failure as failure:
        print(f'compile_commands.py: {failure}; no compilation database written',
              file=sys.stderr)
        return 1
    with open(out, 'w') as file:
        json.dump(entries, file, indent=1)
    count = len(entries)
    print(f'{out}: {count} compile command{"s" if count != 1 else ""}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
