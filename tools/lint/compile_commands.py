#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Writes the compilation database of a superproject: what b2 compiles for the libraries'
tests and examples, and the aggregate translation units of each library.

Usage: compile_commands.py <root> <out> [--wasi-clang <clang++>]

b2 5.5.3's --command-database writes nothing, so its dry runs (b2 -n -a) are read instead, from
root. `b2 declared-targets` first says which targets the libraries' programs are built for, and
`b2 declared-lanes` which own lanes they declare, on which targets; then `test example`, every
library's programs, is dry-run for each of those targets, in the order native, wasip2, wasip3,
emscripten, with every own lane on that target, <directory>//<lane>, whose programs leave `test
example` (a served component among them), and natively with every own lane that names no
target: natively with the host's default toolset, and for each other target with its toolset
(toolset=clang-wasip2, which also generates the bindings of webcpp.wit-bindings, as a build
does). A served program that no own lane runs fails `b2 declared-lanes`, and the database with
it, by name. A target that some library declares and whose toolset is
not configured fails the database, naming the target: its programs would otherwise go unanalysed
without a word. Every line that compiles a .cpp file of the source tree becomes an entry of
<out>, once per distinct command: every native command, and, from the dry run of each other
target, the commands of the sources that no earlier target compiles, which are analysed as the
first target that compiles them does, with its own --target.

clang-tidy reads a WebAssembly command only with the --target and the sysroot it names, and the
lint gives any other command the host's --target, as to a native one. A command of wasip2 or
wasip3 must therefore name wasi-sdk's clang++, as the compiler itself says: the resource
directory it names when asked with -print-resource-dir, which a wrapper such as ccache asks the
compiler it runs, has wasi-sdk's share/wasi-sysroot three levels above it. A command of
emscripten names Emscripten's em++, as the compiler itself says too (em++ --version names emcc
(Emscripten ...)), which clang-tidy cannot run: it is kept with its compiler replaced by
wasi-sdk's clang++, the one --wasi-clang names (the lint gives the one beside its clang-tidy),
after the words that em++ gives clang for that compile, which `em++ <its options> --cflags`
prints (its target, wasm32-unknown-emscripten, its sysroot in Emscripten's cache, the
-iwithsysroot directories compat and fakesdl, and the words of its exceptions: with b2's
-fwasm-exceptions, the legacy encoding em++ compiles with; without exceptions,
-fignore-exceptions), read once per run for each set of options, and before b2's own words.
--cflags alone is not enough: without -fwasm-exceptions, em++ gives -enable-emscripten-sjlj,
which clang refuses beside -fwasm-exceptions. The sysroot holds Emscripten's headers once em++
has compiled with that cache, so em++ first compiles an empty translation unit, as a build's
first compile would. Any other compiler of a WebAssembly command fails the database, naming its
file, its compiler and what that compiler said. Four kinds of line are left out:

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
the database fails, naming the header. An aggregate translation unit of a library includes
public headers, and is compiled with the command of a headers-alone translation unit, which
holds exactly a public header's: a header that no test includes is still analysed. When the
units of a target are compiled with different options (one call of webcpp.headers-alone adds the
bindings or the dependency a header needs, another does not), the command is the first of
theirs with which the aggregate compiles.

A library whose public headers one target builds whole has one aggregate, of every public
header, bin/aggregate/<name>.cpp, with the command of the first target, in the order native,
wasip2, wasip3, emscripten, on which every public header has a headers-alone unit: a library
whose aggregate builds natively has that command; a library whose aggregate builds only for WASI
has one for each of wasip2 and wasip3 on which every public header has a unit, each reading the
branch of its version; a library whose aggregate builds on emscripten alone has that one
command. A library whose headers no single target builds, one that builds only natively against
a dependency of the host's and another only on emscripten, has an aggregate per target its
headers-alone units run on, of the headers that target builds, bin/aggregate/<name>-<target>.cpp,
with that target's command. An aggregate is written inside the tree, since clang-tidy takes its
configuration from the .clang-tidy nearest a source file. The reference of tools/doc/reference.py
writes the aggregate of every public header, with write_aggregate, for MrDocs to read the
library's interface through.

Every target builds with exceptions, so what is analysed on each target has a twin: the command
b2 gives the same translation unit in a dry run of that target with exception-handling=off,
under which Boost.Config defines BOOST_NO_EXCEPTIONS, so that what a header holds for a user's
build without exceptions alone is analysed too, though no test is built so. Each aggregate
command is followed by its twin, and every program's source analysed on the target has its twin
as an entry of its own: a program instantiates the templates the headers hold, and clang refuses
a throw, a try or a catch under -fno-exceptions in a template only where it is instantiated. The
native request also builds `/webcpp//throw_exception`, the superproject's handler as such a build
links it. A program that declares <exception-handling>on, which b2 builds with exceptions
whatever the request, has no twin; the database prints its source, with every other that the
requests without exceptions compile only with them (a Boost.Test suite's framework). An
aggregate's twin holds the aggregate's headers less those whose headers-alone unit still
compiles with exceptions in that run, its call of webcpp.headers-alone declaring
<exception-handling>on (a header that wraps a dependency which reports errors by throwing): the
database prints each such header. A twin that holds every header of its aggregate is the same
translation unit; one that holds fewer is a translation unit of its own,
<aggregate>-exception-handling-off.cpp beside it; one left with no header is no entry.

b2 runs with root/.local/user-config.jam when it exists, else with $WEBCPP_USER_CONFIG when it
is set, else with its own search; and without CPATH, CPLUS_INCLUDE_PATH and C_INCLUDE_PATH,
which the Jamroot refuses.

Exit 0 with the database written; 1 when b2 fails, when a target's toolset is not configured,
when a WebAssembly command's compiler is neither wasi-sdk's clang++ nor, on emscripten,
Emscripten's em++, when an emscripten command has no wasi-sdk's clang++ to be analysed with,
when a public header has no headers-alone translation unit, or when nothing at all is compiled;
2 on a usage error.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import os
import re
import shlex
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

# The property of the request that builds a program without exceptions as a user asks b2 for one,
# and what the native request builds besides the headers-alone translation unit of each library
# whose aggregate builds natively: the handler such a program links.
WITHOUT_EXCEPTIONS = 'exception-handling=off'
HANDLER = '/webcpp//throw_exception'

# The WASI targets, on which a library whose headers build only for WASI has its aggregate.
WASI = ('wasip2', 'wasip3')

# The target whose commands name Emscripten's em++, which the database gives wasi-sdk's clang++.
EMSCRIPTEN = 'emscripten'

# What the first line em++ --version prints starts with.
EMSCRIPTEN_VERSION = 'emcc (Emscripten'

# The suffix of the stem of an aggregate's twin that holds fewer headers than the aggregate.
WITHOUT_SUFFIX = '-exception-handling-off'

# What a compile command holds when b2 builds it without exceptions, on every toolset the lint
# reads: clang's and GCC's flag.
NO_EXCEPTIONS = '-fno-exceptions'

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

# A line of `b2 declared-lanes`: a library, one of its lanes, the directory that declares it and
# the target it runs on, when it names one.
LANE = re.compile(rf'[a-z][a-z0-9_]* (\S+) (libs/\S+)(?: ({"|".join(TARGETS)}))?')


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


def declared_lanes(root: str) -> dict[str, list[str]]:
    """The own lanes the libraries declare, <directory>//<lane>, by the target they run on, those
    that name none under native, as `b2 declared-lanes` lists them, which reads only Jamfiles. A
    line that is no lane's, such as a Jamfile's ECHO, is skipped."""
    command, completed = run_b2(root, ['-d0', 'declared-lanes'])
    if completed.returncode != 0:
        raise Failure(f'{completed.stdout}{" ".join(command)} exited {completed.returncode}')
    lanes: dict[str, list[str]] = {}
    for line in completed.stdout.splitlines():
        lane = LANE.fullmatch(line)
        if lane:
            lanes.setdefault(lane.group(3) or 'native', []).append(
                f'{lane.group(2)}//{lane.group(1)}')
    return lanes


def target_run(root: str, target: str, libraries: list[str],
               lanes: list[str]) -> list[list[str]]:
    """The compile commands of the dry run of every library's programs for target, which the
    libraries named declare, and of the own lanes given; a dry run that fails names the target
    and its toolset."""
    try:
        return compiles(dry_run(root, [*TARGETS[target], *PROGRAMS, *lanes]))
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


@functools.lru_cache(maxsize=None)
def resource_dir(compiler: str) -> str | None:
    """The resource directory compiler names, asked with -print-resource-dir, which a wrapper
    such as ccache passes on to the compiler it runs; None when it names none, as GCC does."""
    try:
        completed = subprocess.run([compiler, '-print-resource-dir'], stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    named = completed.stdout.strip()
    return named if completed.returncode == 0 and named else None


def wasi_sdk(compiler: str) -> bool:
    """Whether compiler, a path or a name on PATH, is a wasi-sdk's clang++, as the compiler itself
    says: its resource directory is <sdk>/lib/clang/<version>, with its sysroot in
    <sdk>/share/wasi-sysroot."""
    resource = resource_dir(compiler)
    return resource is not None and (Path(resource).parents[2] / 'share/wasi-sysroot').is_dir()


@functools.lru_cache(maxsize=None)
def emscripten(compiler: str) -> bool:
    """Whether compiler, a path or a name on PATH, is Emscripten's em++ (or a wrapper of it), as
    the compiler itself says: the first line --version prints names emcc (Emscripten ...)."""
    try:
        completed = subprocess.run([compiler, '--version'], stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, check=False, timeout=120,
                                   env=environment())
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and completed.stdout.startswith(EMSCRIPTEN_VERSION)


@functools.lru_cache(maxsize=None)
def emscripten_ready(compiler: str) -> None:
    """Has Emscripten's em++, compiler, write its headers into the sysroot of its cache,
    EM_CACHE, which em++ --cflags names, as a build's first compile would: em++ compiles an empty
    translation unit. --cflags alone writes nothing. Once per run."""
    run_emscripten(compiler, ['-fsyntax-only', '-x', 'c++', '-'],
                   'compile an empty translation unit, which writes its headers into its cache')


@functools.lru_cache(maxsize=None)
def emscripten_words(compiler: str, options: tuple[str, ...]) -> tuple[str, ...]:
    """The words Emscripten's em++, compiler, gives clang for a compile with options, as
    `em++ <options> --cflags` prints them: its target, its sysroot in Emscripten's cache, and the
    -iwithsysroot directories compat and fakesdl, with the words of the exceptions options asks
    for (-fwasm-exceptions: the legacy encoding; none: -fignore-exceptions). Read once per run for
    each set of options."""
    emscripten_ready(compiler)
    return tuple(shlex.split(run_emscripten(compiler, [*options, '--cflags'],
                                            'print the words it gives clang, --cflags')))


def run_emscripten(compiler: str, arguments: list[str], what: str) -> str:
    """Runs Emscripten's em++, compiler, with arguments and an empty standard input, and returns
    what it printed on its standard output; a run that fails says what it was to do."""
    try:
        completed = subprocess.run([compiler, *arguments], input='', capture_output=True,
                                   text=True, check=False, env=environment())
    except OSError as error:
        raise Failure(f'cannot run {compiler}: {error.strerror}') from error
    if completed.returncode != 0:
        raise Failure(f'{completed.stdout}{completed.stderr}{compiler} could not {what}; it '
                      f'exited {completed.returncode}')
    return completed.stdout


def check_compiler(target: str, source: str, words: list[str]) -> None:
    """Refuses the command words that compiles source for target when target is a WebAssembly one
    and its compiler is not wasi-sdk's clang++, nor, on emscripten, Emscripten's em++: the lint
    would analyse it as a native command. Says what was asked."""
    if target == 'native' or wasi_sdk(words[0]):
        return
    if target == EMSCRIPTEN and emscripten(words[0]):
        return
    resource = resource_dir(words[0])
    asked = (f'{words[0]} -print-resource-dir names {resource}, with no share/wasi-sysroot three '
             'levels above it, as in wasi-sdk' if resource is not None else
             f'{words[0]} -print-resource-dir names no resource directory')
    if target == EMSCRIPTEN:
        raise Failure(f'{source} is compiled for {target} by {words[0]}, which is neither '
                      f'wasi-sdk\'s clang++ nor Emscripten\'s em++: {asked}, and its --version '
                      f'does not start with {EMSCRIPTEN_VERSION}. clang-tidy reads a WebAssembly '
                      'command only with the --target and the sysroot of wasi-sdk, or of em++ '
                      '--cflags, and the lint would analyse this one as a native command, with '
                      f'the host\'s --target; configure the toolset of {target} with '
                      'Emscripten\'s em++')
    raise Failure(f'{source} is compiled for {target} by {words[0]}, which is not wasi-sdk\'s '
                  f'clang++: {asked}. clang-tidy reads a WebAssembly command only with the '
                  '--target and the sysroot of wasi-sdk, and the lint would analyse this one as a '
                  f'native command, with the host\'s --target; configure the toolset of {target} '
                  'with wasi-sdk\'s clang++')


def analysed(target: str, source: str, words: list[str], wasi_clang: str | None) -> list[str]:
    """The command the lint analyses for the command words, which compiles source for target:
    words itself, natively or when wasi-sdk's clang++ is its compiler; for Emscripten's em++,
    words with em++ replaced by wasi_clang, wasi-sdk's clang++, and the words em++ --cflags
    prints for the command's own options before b2's own words. Any other compiler of a
    WebAssembly command fails, as an emscripten command does when wasi_clang is not wasi-sdk's
    clang++."""
    check_compiler(target, source, words)
    if target == 'native' or wasi_sdk(words[0]):
        return words
    if wasi_clang is None or not wasi_sdk(wasi_clang):
        given = (f'--wasi-clang names {wasi_clang}, which is not wasi-sdk\'s clang++'
                 if wasi_clang is not None else 'no --wasi-clang was given')
        raise Failure(f'{source} is compiled for {target} by Emscripten\'s em++, {words[0]}, '
                      'which clang-tidy cannot run: the database gives its command wasi-sdk\'s '
                      f'clang++, and {given}; the lint gives the clang++ beside its clang-tidy')
    return [wasi_clang, *emscripten_words(words[0], options_of(words)[1:]), *words[1:]]


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


def write_aggregate(root: str, library: str, source: str,
                    headers: list[str] | None = None) -> None:
    """Writes an aggregate translation unit of the library to the file source: an include of
    each of headers, or of every public header when headers is None.

    Runs at once, of lint shards or of a lint and a reference, write the same text: each writes a
    file of its own, and renames it over the aggregate."""
    included = public_headers(root, library) if headers is None else headers
    includes = ''.join(f'#include <{header}>\n' for header in included)
    which = ('Every public header' if headers is None else
             f'{len(included)} of the public headers')
    written = f'{source}.{os.getpid()}'
    with open(written, 'w') as file:
        file.write(f'// {which} of {library}, written by compile_commands.py.\n{includes}')
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
    refusals = []
    for command in candidates:
        said = compiles_aggregate(root, command, source)
        if not said:
            return command
        refusals.append(f'- {output_of(command)}: {first_error(said)}')
    raise Failure(f'libs/{library}: its aggregate translation unit, which includes every public '
                  f'header, compiles with the options of none of its headers-alone translation '
                  f'units on {target}; with the options of each unit, the first error:\n'
                  + '\n'.join(refusals))


def first_error(said: str) -> str:
    """The first line of what a compiler said that names an error, else its first line."""
    lines = [line for line in said.splitlines() if line.strip()]
    errors = [line for line in lines if 'error:' in line]
    return (errors or lines or ['the compiler failed'])[0]


@dataclasses.dataclass
class Aggregate:
    """A command of one of a library's aggregate translation units: the target it builds for,
    whether it is the twin b2 compiles with exception-handling=off, the translation unit's path,
    the public headers it includes, and b2's command of the headers-alone unit it is compiled
    with."""

    target: str
    without: bool
    source: str
    headers: list[str]
    command: list[str]


def aggregate_entries(root: str, aggregates: list[Aggregate],
                      wasi_clang: str | None) -> list[dict[str, object]]:
    """The entries of a library's aggregate translation units, one per command given, each as the
    lint analyses it: the first one's object is in bin/aggregate, each other's in a directory
    named after its target, and after exception-handling-off for a twin."""
    directory = os.path.join(root, BUILD_DIR, 'aggregate')
    entries: list[dict[str, object]] = []
    for index, aggregate in enumerate(aggregates):
        source = aggregate.source
        arguments = analysed(aggregate.target, os.path.relpath(source, root), aggregate.command,
                             wasi_clang)
        arguments = arguments[:-1] + [source]
        place = (os.path.join(directory, aggregate.target,
                              *(['exception-handling-off'] if aggregate.without else []))
                 if index else directory)
        arguments[arguments.index('-o') + 1] = os.path.join(place, f'{Path(source).stem}.o')
        entries.append({'directory': root, 'file': source, 'arguments': arguments})
    return entries


def libraries(root: str) -> list[str]:
    """The libraries the Jamroot registers: each directory of libs/ with a build.jam."""
    return sorted(build.parent.name for build in Path(root, 'libs').glob('*/build.jam'))


Units = dict[str, dict[str, list[list[str]]]]


def read(root: str, target: str, commands: list[list[str]], entries: list[dict[str, object]],
         seen: set[tuple[str, ...]], earlier: set[str],
         wasi_clang: str | None) -> tuple[Units, set[str]]:
    """Adds to entries each command of commands, compiled for target, that compiles a .cpp file of
    the source tree that is not in earlier, a source an earlier target compiles, and that is not
    in seen, as the lint analyses it (analysed); a WebAssembly command of a compiler other than
    wasi-sdk's clang++ or, on emscripten, Emscripten's em++ fails. Returns the commands of the
    headers-alone translation units, by library and by unit, and the sources of the tree that
    commands compile."""
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
        if source in earlier or key in seen:
            continue
        seen.add(key)
        entries.append({'directory': root, 'file': os.path.join(root, source),
                        'arguments': analysed(target, source, words, wasi_clang)})
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


def unit_commands(units: dict[str, list[list[str]]], headers: list[str]) -> list[list[str]]:
    """The commands of the headers-alone units of headers, by their units' names."""
    names = {alone_name(header) for header in headers}
    return [command for name in sorted(names) for command in units[name]]


def pick(root: str, library: str, targets: list[str], units: dict[str, Units]) -> list[Aggregate]:
    """The aggregate of every public header of a library that one target builds whole, with its
    command on each of targets, after writing it as bin/aggregate/<library>.cpp."""
    directory = os.path.join(root, BUILD_DIR, 'aggregate')
    os.makedirs(directory, exist_ok=True)
    source = os.path.join(directory, f'{library}.cpp')
    headers = public_headers(root, library)
    write_aggregate(root, library, source)
    return [Aggregate(target, False, source, headers,
                      aggregate_command(root, library, target,
                                        unit_commands(units[target][library], headers), source))
            for target in targets]


def per_target(root: str, library: str, headers: list[str],
               units: dict[str, Units]) -> list[Aggregate]:
    """An aggregate for each target, in the order of units, on which some of the library's
    headers have a headers-alone unit, of those headers, with that target's command, after
    writing it as bin/aggregate/<library>-<target>.cpp: the aggregates of a library whose headers
    no single target builds."""
    directory = os.path.join(root, BUILD_DIR, 'aggregate')
    os.makedirs(directory, exist_ok=True)
    aggregates = []
    for target, theirs in units.items():
        built = [header for header in headers if alone_name(header) in theirs.get(library, {})]
        if not built:
            continue
        source = os.path.join(directory, f'{library}-{target}.cpp')
        write_aggregate(root, library, source, built)
        aggregates.append(Aggregate(target, False, source, built, aggregate_command(
            root, library, target, unit_commands(theirs[library], built), source)))
    return aggregates


@dataclasses.dataclass
class Twinned:
    """What the dry runs without exceptions found compiled with exceptions all the same: the
    sources of the tree, programs that declare <exception-handling>on, and the public headers
    whose headers-alone units do, which no twin holds."""

    programs: set[str] = dataclasses.field(default_factory=set)
    headers: set[str] = dataclasses.field(default_factory=set)


def twins(root: str, target: str, chosen: dict[str, list[Aggregate]], units: Units,
          lanes: list[str], first: dict[str, str], entries: list[dict[str, object]],
          seen: set[tuple[str, ...]], wasi_clang: str | None, twinned: Twinned) -> None:
    """Adds the twins of what is analysed on target: b2's dry run of every library's programs and
    of the lanes given, for target with exception-handling=off, gives each source of the tree that
    first says target compiles first, and that is not there yet, its command without exceptions,
    added to entries, and each aggregate of chosen on target its twin, inserted after it: the
    aggregate's headers less those whose headers-alone unit, among units, the headers-alone units
    of target, b2 still compiles with exceptions, its own translation unit when that leaves some
    out, and none when it leaves none in. Natively the dry run also builds the handler, which only
    a build without exceptions links. Adds to twinned the sources of the tree that the dry run
    compiles only with exceptions all the same, a program that declares <exception-handling>on,
    which therefore has no twin, and the headers left out of a twin. A unit b2 does not compile
    without exceptions fails, naming its library and its header."""
    aggregates = {library: theirs for library, theirs in chosen.items()
                  if any(aggregate.target == target for aggregate in theirs)}
    programs = [source for source, where in first.items() if where == target]
    if target != 'native' and not aggregates and not programs:
        return
    requested = sorted({target_of_unit(command) for library, theirs in aggregates.items()
                        for aggregate in theirs if aggregate.target == target
                        for command in unit_commands(units[library], aggregate.headers)})
    handler = [HANDLER] if target == 'native' else []
    without: Units = {}
    kept: set[str] = set()
    compiled: set[str] = set()
    for words in compiles(dry_run(root, [*TARGETS[target], WITHOUT_EXCEPTIONS, *PROGRAMS, *lanes,
                                         *handler, *requested])):
        source = words[-1]
        unit = ALONE.match(source)
        if unit:
            without.setdefault(unit.group(1), {}).setdefault(unit.group(2), []).append(words)
        if source.startswith(f'{BUILD_DIR}/') or first.setdefault(source, target) != target:
            continue
        if NO_EXCEPTIONS not in words:
            kept.add(source)
            continue
        compiled.add(source)
        key = tuple(without_output(words))
        if key in seen:
            continue
        seen.add(key)
        entries.append({'directory': root, 'file': os.path.join(root, source),
                        'arguments': analysed(target, source, words, wasi_clang)})
    twinned.programs |= kept - compiled
    for library, theirs in aggregates.items():
        index = next(index for index, aggregate in enumerate(theirs)
                     if aggregate.target == target)
        aggregate = theirs[index]
        theirs_without = without.get(library, {})
        for header in aggregate.headers:
            if not theirs_without.get(alone_name(header)):
                raise Failure(f'libs/{library}: b2 compiles no translation unit of '
                              f'webcpp.headers-alone for {header} on {target} with '
                              f'{WITHOUT_EXCEPTIONS}')
        headers = [header for header in aggregate.headers
                   if all(NO_EXCEPTIONS in command
                          for command in theirs_without[alone_name(header)])]
        twinned.headers |= {f'libs/{library}/include/{header}' for header in aggregate.headers
                            if header not in headers}
        if not headers:
            continue
        if headers == aggregate.headers:
            # The same translation unit, with the twin of the unit its command is taken from.
            unit = ALONE.match(aggregate.command[-1])
            assert unit is not None, aggregate
            twin = Aggregate(target, True, aggregate.source, headers,
                             theirs_without[unit.group(2)][0])
        else:
            source = os.path.join(os.path.dirname(aggregate.source),
                                  f'{Path(aggregate.source).stem}{WITHOUT_SUFFIX}.cpp')
            write_aggregate(root, library, source, headers)
            twin = Aggregate(target, True, source, headers, aggregate_command(
                root, library, target, unit_commands(theirs_without, headers), source))
        theirs.insert(index + 1, twin)


def database(root: str, wasi_clang: str | None = None) -> list[dict[str, object]]:
    """The entries of the database of root, after writing the aggregates; wasi_clang is
    wasi-sdk's clang++, with which an emscripten command is analysed."""
    entries: list[dict[str, object]] = []
    seen: set[tuple[str, ...]] = set()
    declared = declared_targets(root)
    lanes = declared_lanes(root)
    published = [library for library in libraries(root) if public_headers(root, library)]
    headers = {library: public_headers(root, library) for library in published}

    # Natively, every library's programs; then, for each other target some library declares, the
    # programs no earlier target compiles. first records where each source is analysed.
    units: dict[str, Units] = {}
    first: dict[str, str] = {}
    for target in TARGETS:
        declaring = sorted(library for library, theirs in declared.items() if target in theirs)
        if target != 'native' and not declaring:
            continue
        units[target], sources = read(root, target,
                                      target_run(root, target, declaring, lanes.get(target, [])),
                                      entries, seen, set(first), wasi_clang)
        for source in sources:
            first.setdefault(source, target)

    # Each library's aggregates: one of every public header when one target builds them whole,
    # else one per target of the headers it builds.
    chosen: dict[str, list[Aggregate]] = {}
    for library in published:
        compiled = {name for target in units for name in units[target].get(library, {})}
        missing = [header for header in headers[library] if alone_name(header) not in compiled]
        if missing:
            raise Failure(f'libs/{library}: no target compiles alone '
                          f'{", ".join(f"libs/{library}/include/{header}" for header in missing)}, '
                          'whose analysis goes through the aggregate translation unit; declare it '
                          f'with `webcpp.headers-alone {library} : ../include ...` in '
                          f'libs/{library}/test/Jamfile')
        whole = whole_targets(headers[library], units, library)
        wasi = [target for target in whole if target in WASI]
        chosen[library] = (pick(root, library, ['native'] if 'native' in whole else
                                wasi or whole[:1], units) if whole else
                           per_target(root, library, headers[library], units))

    # Then the twins without exceptions, on each target, of the programs and the aggregates
    # analysed there.
    twinned = Twinned()
    for target in TARGETS:
        twins(root, target, chosen, units.get(target, {}), lanes.get(target, []), first, entries,
              seen, wasi_clang, twinned)
    if twinned.programs:
        print('compile_commands.py: built with exceptions whatever the build asks, so analysed '
              f'with them alone: {", ".join(sorted(twinned.programs))}')
    if twinned.headers:
        print('compile_commands.py: left out of the analysis without exceptions, their '
              'headers-alone units built with exceptions whatever the build asks: '
              f'{", ".join(sorted(twinned.headers))}')
    for library in published:
        entries.extend(aggregate_entries(root, chosen[library], wasi_clang))
    if not entries:
        raise Failure('b2 compiled no .cpp file, not even tools/throw_exception.cpp; is its '
                      'dry run printed another way?')
    return entries


def main(arguments: list[str]) -> int:
    wasi_clang = None
    if len(arguments) == 4 and arguments[2] == '--wasi-clang':
        wasi_clang = os.path.abspath(arguments[3])
        arguments = arguments[:2]
    if len(arguments) != 2:
        print('usage: compile_commands.py <root> <out> [--wasi-clang <clang++>]', file=sys.stderr)
        return 2
    root, out = (os.path.abspath(argument) for argument in arguments)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:
        entries = database(root, wasi_clang)
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
