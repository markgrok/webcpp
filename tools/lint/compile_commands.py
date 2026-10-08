#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Writes the compilation database of a superproject: what b2 compiles for the libraries'
tests and examples, and the aggregate translation units of each library.

Usage: compile_commands.py <root> <out>

b2 5.5.3's --command-database writes nothing, so its dry runs (b2 -n -a) are read instead, from
root. `b2 declared-targets` first says which targets the libraries' programs are built for; then
`test example`, every library's programs, is dry-run for each of those targets, in the order
native, wasip2, wasip3, emscripten: natively with the host's default toolset, and for each other
target with its toolset (toolset=clang-wasip2, which also generates the bindings of
webcpp.wit-bindings, as a build does). A target that some library declares and whose toolset is
not configured fails the database, naming the target: its programs would otherwise go unanalysed
without a word. Every line that compiles a .cpp file of the source tree becomes an entry of
<out>, once per distinct command: every native command, and, from the dry run of each other
target, the commands of the sources that no earlier target compiles, which are analysed as the
first target that compiles them does, with its own --target. A command of wasip2, wasip3 or
emscripten, a program's or an aggregate's, must name wasi-sdk's clang++, which has its
wasi-sysroot beside it: clang-tidy reads a WebAssembly command only with the --target and the
sysroot of wasi-sdk, and the lint would give any other compiler's, emscripten's em++ for one, the
host's --target, as to a native command. Such a command fails the database, naming its file and
its compiler. Four kinds of line are left out:

- a source b2 generates under bin/, the Jamroot's build directory, which is not ours to analyse;
- a source b2 expects not to compile (webcpp.compile-fail): the dry run prints its object as a
  `(failed-as-expected)` marker, and an analysis would stop at the error the test exists to
  show. A run-fail test's marker is its .run file: its sources compile, and are analysed;
- a source that must stop with the error it states (webcpp.compile-diagnostic), whose command
  holds clang's `-Xclang -verify`: it compiles only because -verify finds that error, at which an
  analysis would stop;
- the same source compiled again with the same options, under another name.

Every public header of a library, webcpp/<name>.hpp and each .hpp under webcpp/<name>/, the
headers webcpp.headers-alone checks, has a headers-alone translation unit on some target, else
the database fails, naming the header. The aggregate translation unit of a library includes
every public header, and is compiled with the command of a headers-alone translation unit, which
holds exactly a public header's: a header that no test includes is still analysed. Its command is
that of the first target, in the order native, wasip2, wasip3, emscripten, on which every public
header has a headers-alone unit; when the units of that target are compiled with different
options (one call of webcpp.headers-alone adds the bindings a header needs, another does not), the
command is the first of theirs with which the aggregate compiles. A library whose aggregate builds
natively has two entries: that command as the tests are built, and the one b2 gives the same
translation unit with exception-handling=off, under which Boost.Config defines
BOOST_NO_EXCEPTIONS, so that what a header holds for a program built without exceptions alone is
analysed too, though no native test is built so; that request also builds
`/webcpp//throw_exception`, the superproject's handler as a program built without exceptions links
it. A library whose aggregate builds only for WASI has an entry for each of wasip2 and wasip3 on
which every public header has a unit: wasip2's without exceptions and wasip3's with them, each
reading the branch of its version. The aggregate is written as bin/aggregate/<name>.cpp, inside
the tree, since clang-tidy takes its configuration from the .clang-tidy nearest a source file. The
reference of tools/doc/reference.py writes the same translation unit, with write_aggregate, for
MrDocs to read the library's interface through.

b2 runs with root/.local/user-config.jam when it exists, else with $WEBCPP_USER_CONFIG when it
is set, else with its own search; and without CPATH, CPLUS_INCLUDE_PATH and C_INCLUDE_PATH,
which the Jamroot refuses.

Exit 0 with the database written; 1 when b2 fails, when a target's toolset is not configured,
when a WebAssembly command's compiler is not wasi-sdk's clang++, when a public header has no
headers-alone translation unit, when no target compiles every public header of a library alone,
or when nothing at all is compiled; 2 on a usage error.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# The b2 request whose compile lines the database holds: every library's programs.
PROGRAMS = ['test', 'example']

# The targets of tools/webcpp.jam, in the order the database prefers them, each with what its dry
# run adds to the request: native is the host's default toolset.
TARGETS = {
    'native': [],
    'wasip2': ['toolset=clang-wasip2'],
    'wasip3': ['toolset=clang-wasip3'],
    'emscripten': ['toolset=emscripten'],
}

# The property of the native request that builds a program without exceptions as a user asks b2
# for one, and what that request builds besides the headers-alone translation unit of each library
# whose aggregate builds natively: the handler such a program links.
WITHOUT_EXCEPTIONS = 'exception-handling=off'
HANDLER = '/webcpp//throw_exception'

# The Jamroot's build-dir, where b2 writes what it generates.
BUILD_DIR = 'bin'

COMPILER_PATHS = ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH')

MARKER = re.compile(r'^\(failed-as-expected\) (.+)$')

# A translation unit of webcpp.headers-alone, bin/libs/<library>/.../alone-<header>.cpp, and its
# object, under the build directory of the project that declares the test, the directory
# alone-<header>.test.
ALONE = re.compile(rf'^{BUILD_DIR}/libs/([^/]+)/.*/(alone-[^/]+)\.cpp$')
ALONE_OBJECT = re.compile(rf'^{BUILD_DIR}/(libs/.+?)/(alone-[^/]+)\.test/')

# A line of `b2 declared-targets`: a library and a target its programs are built for.
DECLARED = re.compile(rf'([a-z][a-z0-9_]*) ({"|".join(TARGETS)})')


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


def environment() -> dict[str, str]:
    """This process's environment, without the variables a compiler reads include paths from."""
    return {name: value for name, value in os.environ.items() if name not in COMPILER_PATHS}


def run_b2(root: str, arguments: list[str]) -> tuple[list[str], subprocess.CompletedProcess[str]]:
    """Runs b2 with arguments in root, and returns its command and what it did."""
    command = [*b2_command(root), *arguments]
    try:
        completed = subprocess.run(command, cwd=root, env=environment(), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, check=False)
    except OSError as error:
        raise Failure(f'cannot run b2: {error.strerror}') from error
    return command, completed


def dry_run(root: str, request: list[str]) -> list[str]:
    """The lines b2 prints for a dry run of request, in root; b2's failure is a Failure."""
    command, completed = run_b2(root, ['-n', '-a', *request])
    if completed.returncode != 0:
        raise Failure(f'{completed.stdout}{" ".join(command)} exited {completed.returncode}')
    return completed.stdout.splitlines()


def declared_targets(root: str) -> dict[str, set[str]]:
    """The targets each library's programs are built for, by library, as
    `b2 declared-targets` lists them, which reads only Jamfiles. What a Jamfile itself prints as
    it loads (an ECHO) is no line of the list, and is skipped."""
    command, completed = run_b2(root, ['-d0', 'declared-targets'])
    if completed.returncode != 0:
        raise Failure(f'{completed.stdout}{" ".join(command)} exited {completed.returncode}')
    declared: dict[str, set[str]] = {}
    for line in completed.stdout.splitlines():
        pair = DECLARED.fullmatch(line)
        if pair:
            declared.setdefault(pair.group(1), set()).add(pair.group(2))
    return declared


def target_run(root: str, target: str, libraries: list[str]) -> list[list[str]]:
    """The compile commands of the dry run of every library's programs for target, which the
    libraries named declare; a dry run that fails names the target and its toolset."""
    try:
        return compiles(dry_run(root, [*TARGETS[target], *PROGRAMS]))
    except Failure as failure:
        if target == 'native':
            raise
        raise Failure(f'{failure}\nb2 could not dry-run the programs for {target}, which '
                      f'{", ".join(f"libs/{library}" for library in libraries)} '
                      f'{"declares" if len(libraries) == 1 else "declare"}, with '
                      f'{TARGETS[target][0]} (above): is that toolset configured in the '
                      'user-config.jam b2 reads? The database needs it, or those programs and '
                      'headers go unanalysed') from failure


def compiles(lines: list[str]) -> list[list[str]]:
    """The commands of lines that compile a .cpp file, as words, without those b2 expects to
    fail: a compile-fail test's, whose object is itself a `(failed-as-expected)` marker, and a
    compile-diagnostic test's, whose command holds `-Xclang -verify`. A run-fail test's marker is
    its .run file, so its sources stay."""
    commands = [shlex.split(line) for line in lines
                if ' -c ' in line and line.rstrip().endswith('.cpp"')]
    failing = {marker.group(1) for marker in map(MARKER.match, lines) if marker}
    return [words for words in commands
            if output_of(words) not in failing and not verifies(words)]


def verifies(words: list[str]) -> bool:
    """Whether the compile command words runs clang's -verify, as webcpp.compile-diagnostic's
    does: `-Xclang -verify`."""
    return any(first == '-Xclang' and second == '-verify'
               for first, second in zip(words, words[1:]))


def wasi_sdk(compiler: str) -> bool:
    """Whether compiler, a path or a name on PATH, is a wasi-sdk's clang++: <sdk>/bin/clang++, with
    its sysroot in <sdk>/share/wasi-sysroot."""
    real = os.path.realpath(shutil.which(compiler) or compiler)
    return os.path.isdir(os.path.join(os.path.dirname(os.path.dirname(real)), 'share',
                                      'wasi-sysroot'))


def check_compiler(target: str, source: str, words: list[str]) -> None:
    """Refuses the command words that compiles source for target when target is a WebAssembly one
    and its compiler is not wasi-sdk's clang++, which the lint would analyse as a native one."""
    if target == 'native' or wasi_sdk(words[0]):
        return
    raise Failure(f'{source} is compiled for {target} by {words[0]}, which is not wasi-sdk\'s '
                  'clang++. clang-tidy reads a WebAssembly command only with the --target and the '
                  'sysroot of wasi-sdk, and the lint would analyse this one as a native command, '
                  f'with the host\'s --target; configure the toolset of {target} with wasi-sdk\'s '
                  'clang++')


def output_of(words: list[str]) -> str:
    """The object file a compile command writes."""
    return words[words.index('-o') + 1] if '-o' in words else ''


def without_output(words: list[str]) -> list[str]:
    """The command without its object file, which names the program it is compiled for."""
    if '-o' not in words:
        return words
    index = words.index('-o')
    return words[:index] + words[index + 2:]


def options_of(words: list[str]) -> tuple[str, ...]:
    """The options of a compile command: without its object file, its -c and its source."""
    return tuple(word for word in without_output(words)[:-1] if word != '-c')


def public_headers(root: str, library: str) -> list[str]:
    """The headers webcpp.headers-alone checks, as they are included: webcpp/<library>.hpp."""
    include = Path(root, 'libs', library, 'include')
    headers = [include / 'webcpp' / f'{library}.hpp']
    headers += (include / 'webcpp' / library).rglob('*.hpp')
    return sorted(header.relative_to(include).as_posix() for header in headers if header.is_file())


def alone_name(header: str) -> str:
    """The headers-alone translation unit of a public header, as webcpp.headers-alone names it:
    alone-xactor-scheduler for webcpp/xactor/scheduler.hpp."""
    return 'alone-' + header.removeprefix('webcpp/').removesuffix('.hpp').replace('/', '-')


def write_aggregate(root: str, library: str, source: str) -> None:
    """Writes the library's aggregate translation unit to the file source.

    Runs at once, of lint shards or of a lint and a reference, write the same text: each writes a
    file of its own, and renames it over the aggregate."""
    includes = ''.join(f'#include <{header}>\n' for header in public_headers(root, library))
    written = f'{source}.{os.getpid()}'
    with open(written, 'w') as file:
        file.write(f'// Every public header of {library}, written by compile_commands.py.\n'
                   f'{includes}')
    os.replace(written, source)


def compiles_aggregate(root: str, command: list[str], source: str) -> str:
    """What the compiler says when the options of command do not compile the aggregate source,
    run in root as the database's commands are; nothing when they do."""
    try:
        completed = subprocess.run([*options_of(command), '-fsyntax-only', source], cwd=root,
                                   env=environment(), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, check=False)
    except OSError as error:
        return f'cannot run {command[0]}: {error.strerror}'
    return '' if completed.returncode == 0 else completed.stdout or 'the compiler failed'


def aggregate_command(root: str, library: str, target: str, units: list[list[str]],
                      source: str) -> list[str]:
    """The command of the library's aggregate on target: that of its headers-alone units, or, when
    they are compiled with different options, the first of theirs with which it compiles."""
    distinct: dict[tuple[str, ...], list[str]] = {}
    for command in units:
        distinct.setdefault(options_of(command), command)
    candidates = list(distinct.values())
    if len(candidates) == 1:
        return candidates[0]
    said = ''
    for command in candidates:
        said = compiles_aggregate(root, command, source)
        if not said:
            return command
    raise Failure(f'libs/{library}: its aggregate translation unit, which includes every public '
                  f'header, compiles with the options of none of its headers-alone translation '
                  f'units on {target}; the last said:\n{said}')


def aggregate_entries(root: str, library: str,
                      commands: list[tuple[str, list[str]]]) -> list[dict[str, object]]:
    """The entries of the library's aggregate translation unit, one per command given with its
    variant: the first variant's object is in bin/aggregate, each other's in a directory named
    after it."""
    directory = os.path.join(root, BUILD_DIR, 'aggregate')
    source = os.path.join(directory, f'{library}.cpp')
    entries: list[dict[str, object]] = []
    for index, (variant, command) in enumerate(commands):
        check_compiler(variant if variant in TARGETS else 'native',
                       os.path.relpath(source, root), command)
        arguments = command[:-1] + [source]
        place = os.path.join(directory, variant) if index else directory
        arguments[arguments.index('-o') + 1] = os.path.join(place, f'{library}.o')
        entries.append({'directory': root, 'file': source, 'arguments': arguments})
    return entries


def libraries(root: str) -> list[str]:
    """The libraries the Jamroot registers: each directory of libs/ with a build.jam."""
    return sorted(build.parent.name for build in Path(root, 'libs').glob('*/build.jam'))


Units = dict[str, dict[str, list[list[str]]]]


def read(root: str, target: str, commands: list[list[str]], entries: list[dict[str, object]],
         seen: set[tuple[str, ...]], analysed: set[str]) -> tuple[Units, set[str]]:
    """Adds to entries each command of commands, compiled for target, that compiles a .cpp file of
    the source tree that is not in analysed, a source an earlier target compiles, and that is not
    in seen; a WebAssembly command of a compiler other than wasi-sdk's fails. Returns the commands
    of the headers-alone translation units, by library and by unit, and the sources of the tree
    that commands compile."""
    units: Units = {}
    sources: set[str] = set()
    for words in commands:
        source = words[-1]
        unit = ALONE.match(source)
        if unit:
            units.setdefault(unit.group(1), {}).setdefault(unit.group(2), []).append(words)
        if source.startswith(f'{BUILD_DIR}/'):
            continue
        sources.add(source)
        key = tuple(without_output(words))
        if source in analysed or key in seen:
            continue
        seen.add(key)
        check_compiler(target, source, words)
        entries.append({'directory': root, 'file': os.path.join(root, source),
                        'arguments': words})
    return units, sources


def target_of_unit(command: list[str]) -> str:
    """The b2 target of a headers-alone translation unit's command:
    libs/<library>/test//alone-<header>, the test in the project that declares it."""
    unit = ALONE_OBJECT.match(output_of(command))
    if unit is None:
        raise Failure(f'b2 compiled a translation unit of webcpp.headers-alone into '
                      f'{output_of(command)}, outside the directory alone-<header>.test of its '
                      'project; is its dry run printed another way?')
    return f'{unit.group(1)}//{unit.group(2)}'


def whole_targets(headers: list[str], units: dict[str, Units], library: str) -> list[str]:
    """The targets, in the order of units, on which every header has a headers-alone unit of the
    library."""
    return [target for target in units
            if all(alone_name(header) in units[target].get(library, {}) for header in headers)]


def pick(root: str, library: str, targets: list[str],
         units: dict[str, Units]) -> list[tuple[str, list[str]]]:
    """Each of targets with the command of the library's aggregate there, after writing it."""
    directory = os.path.join(root, BUILD_DIR, 'aggregate')
    os.makedirs(directory, exist_ok=True)
    source = os.path.join(directory, f'{library}.cpp')
    write_aggregate(root, library, source)
    return [(target, aggregate_command(root, library, target,
                                       [command for name in sorted(units[target][library])
                                        for command in units[target][library][name]], source))
            for target in targets]


def database(root: str) -> list[dict[str, object]]:
    """The entries of the database of root, after writing the aggregates."""
    entries: list[dict[str, object]] = []
    seen: set[tuple[str, ...]] = set()
    declared = declared_targets(root)
    published = [library for library in libraries(root) if public_headers(root, library)]
    headers = {library: public_headers(root, library) for library in published}

    # Natively: every library's programs, then, built without exceptions, the handler and the
    # headers-alone translation unit of each library whose aggregate builds natively.
    units: dict[str, Units] = {}
    units['native'], analysed = read(root, 'native', target_run(root, 'native', []), entries,
                                     seen, set())
    chosen = {library: pick(root, library, ['native'], units) for library in published
              if whole_targets(headers[library], units, library)}
    twins = [target_of_unit(commands[0][1]) for commands in chosen.values()]
    without, sources = read(root, 'native',
                            compiles(dry_run(root, [WITHOUT_EXCEPTIONS, HANDLER, *twins])),
                            entries, seen, set())
    analysed |= sources
    for library, commands in chosen.items():
        unit = ALONE.match(commands[0][1][-1])
        assert unit is not None, commands
        twin = without.get(library, {}).get(unit.group(2))
        if not twin:
            raise Failure(f'libs/{library}: b2 compiles no translation unit of '
                          f'webcpp.headers-alone for it with {WITHOUT_EXCEPTIONS}')
        commands.append((WITHOUT_EXCEPTIONS, twin[0]))

    # Each other target some library declares: the programs no earlier target compiles.
    for target in TARGETS:
        declaring = sorted(library for library, theirs in declared.items() if target in theirs)
        if target == 'native' or not declaring:
            continue
        units[target], sources = read(root, target, target_run(root, target, declaring), entries,
                                      seen, analysed)
        analysed |= sources

    for library in published:
        compiled = {name for target in units for name in units[target].get(library, {})}
        missing = [header for header in headers[library] if alone_name(header) not in compiled]
        if missing:
            raise Failure(f'libs/{library}: no target compiles alone '
                          f'{", ".join(f"libs/{library}/include/{header}" for header in missing)}, '
                          'whose analysis goes through the aggregate translation unit; declare it '
                          f'with `webcpp.headers-alone {library} : ../include ...` in '
                          f'libs/{library}/test/Jamfile')
        if library in chosen:
            continue
        whole = whole_targets(headers[library], units, library)
        if not whole:
            raise Failure(f'libs/{library}: no one target compiles every public header alone, so '
                          'none gives its aggregate translation unit, which includes them all, a '
                          'command')
        wasi = [target for target in whole if target in ('wasip2', 'wasip3')]
        chosen[library] = pick(root, library, wasi or whole[:1], units)
    for library in published:
        entries.extend(aggregate_entries(root, library, chosen[library]))
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
