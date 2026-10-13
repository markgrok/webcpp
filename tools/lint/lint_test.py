#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/lint/lint.sh: a clean superproject passes, with the fixture library and without any
library; each rule, planted alone, fails alone and names the file and the line; and
tools/lint/compile_commands.py lists what b2 builds, without what b2 expects to fail, plus the
aggregate translation units of each library: what builds only for WASI, the header of the fixture
library component_demo's world and its programs that declare no native target, is analysed as
wasi-sdk's clang++ builds it, with no host target, the header on wasip2 and on wasip3, each with
exceptions and without them; the fixture library browser_demo, whose headers no one target builds,
has an aggregate per target, its emscripten one analysed by wasi-sdk's clang++ with the words of
em++ --cflags, and its native one, against the fake dependency that throws, twinned without the
header that needs exceptions and with a native header whose own headers-alone call does not declare
them; a public header that no target compiles alone, a target whose toolset is not configured, and a
WebAssembly command whose compiler is neither wasi-sdk's clang++ nor, on emscripten, Emscripten's
em++, fail the database by name. Each case lints a scratch superproject whose libs/demo is the
fixture library demo, a repository of its own as a library's submodule is, and libs/component_demo
or libs/browser_demo too in the cases of WASI and of emscripten. Run with the names of some cases to
run only those."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# The harness lives beside the other tests of the build, in tools/test.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'test'))

import compile_commands
import harness

LINT = Path('tools/lint/lint.sh')

# The banned word, spelt so that this file never contains it.
WORD = 'ver' + 'us'

# U+2014, written as an escape so that this file never contains it.
EM_DASH = '\u2014'

NOTICE = ('Copyright (c) 2026 WebCpp.org\n'
          '\n'
          'Distributed under the Boost Software License, Version 1.0. (See\n'
          'accompanying file LICENSE_1_0.txt or copy at\n'
          'https://www.boost.org/LICENSE_1_0.txt)\n')

# The notice xstate-cpp's files open with, which a moved file must not keep.
OLD_NOTICE = ('Copyright (c) 2026 R\n'
              '\n'
              'Distributed under the Boost Software License, Version 1.0, or the MIT\n'
              'License, at your option. (See the accompanying files LICENSE_1_0.txt and\n'
              'LICENSE-MIT.txt.)\n')

# The MIT licence's own wording, under the right copyright line.
MIT_NOTICE = ('Copyright (c) 2026 WebCpp.org\n'
              '\n'
              'Permission is hereby granted, free of charge, to any person obtaining a copy\n'
              'of this software and associated documentation files (the "Software"), to deal\n')

FAILED = re.compile(r'^lint: failed: (.+)$', re.MULTILINE)

TIDY_CLEAN = re.compile(r'^clang-tidy is clean \((\d+) translation units?\)$', re.MULTILINE)

TIDY_SHARD = re.compile(r'^clang-tidy is clean \((\d+) of (\d+) translation units, shard (\S+)\)$',
                        re.MULTILINE)


def commented(notice: str, prefix: str) -> str:
    """The notice with each line commented by prefix: // or #."""
    return ''.join(f'{prefix} {line}' if line.strip() else f'{prefix}\n'
                   for line in notice.splitlines(keepends=True))


CPP = commented(NOTICE, '//')
HASH = commented(NOTICE, '#')


def wasi_sdk_tool(name: str) -> str:
    """The wasi-sdk tool name: from $WASI_SDK, as CI exports it, else from .local/wasi-sdk."""
    configured = os.environ.get('WASI_SDK')
    sdk = Path(configured) if configured else harness.ROOT / '.local/wasi-sdk'
    tool = sdk / 'bin' / name
    if not tool.is_file():
        raise RuntimeError(f'no {tool}: install wasi-sdk 34 there, or set WASI_SDK')
    return str(tool)


CLANG_FORMAT = wasi_sdk_tool('clang-format')
CLANG_TIDY = wasi_sdk_tool('clang-tidy')


def git(directory: Path, *arguments: str, name: str = 'webcpp lint test') -> str:
    """Runs git in directory as the author name, and returns what it printed."""
    command = ['git', '-c', f'user.name={name}', '-c', 'user.email=lint@webcpp.invalid',
               '-c', 'advice.addEmbeddedRepo=false', *arguments]
    completed = subprocess.run(command, cwd=directory, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, check=False)
    assert completed.returncode == 0, (command, completed.stdout)
    return completed.stdout


def commit(directory: Path, message: str, name: str = 'webcpp lint test') -> None:
    """Commits everything in the repository directory."""
    git(directory, 'add', '-A')
    git(directory, 'commit', '-q', '--allow-empty', '-m', message, name=name)


def pyright_installed() -> Path:
    """The node_modules of tools/lint, which tools/node/install.py installs once, here, for every
    case."""
    modules = harness.ROOT / 'tools/lint/node_modules'
    if not (modules / '.bin/pyright').exists():
        subprocess.run([sys.executable, str(harness.ROOT / 'tools/node/install.py'),
                        str(modules.parent)], check=True)
    return modules


def prepare(root: Path) -> None:
    """Makes the scratch superproject root and its libs/demo two repositories, as a checkout and
    its submodule are, and gives it the Pyright of this checkout."""
    for directory in (root / 'libs/demo', root):
        git(directory, 'init', '-q', '-b', 'main')
        commit(directory, 'The scratch copy')
    (root / 'tools/lint/node_modules').symlink_to(pyright_installed())


def add_component_demo(root: Path) -> None:
    """Places the fixture library component_demo beside demo in the scratch superproject root, a
    repository of its own too, with this checkout's wit-bindgen and WIT, which its bindings
    need. Its served test runs in an own lane, http, as every served program must for
    `b2 declared-lanes`, which the database reads, to list the lanes."""
    shutil.copytree(harness.FIXTURES / 'component_demo', root / 'libs/component_demo',
                    ignore=harness.built)
    append(root, 'libs/component_demo/test/Jamfile',
           'webcpp.lane http : answers : wasip2 wasip3 ;\n')
    git(root / 'libs/component_demo', 'init', '-q', '-b', 'main')
    commit(root / 'libs/component_demo', 'The fixture')
    harness.link_wasi_tools(root)


def add_browser_demo(root: Path) -> None:
    """Places the fixture library browser_demo beside demo in the scratch superproject root, a
    repository of its own too: its page.hpp builds only on emscripten, with Emscripten's own
    <emscripten/val.h>, and its native.hpp only natively, against the fake dependency of its
    deps/include, which throws."""
    shutil.copytree(harness.FIXTURES / 'browser_demo', root / 'libs/browser_demo',
                    ignore=harness.built)
    git(root / 'libs/browser_demo', 'init', '-q', '-b', 'main')
    commit(root / 'libs/browser_demo', 'The fixture')


BROWSER_DEMO = 'libs/browser_demo/include/webcpp/browser_demo.hpp'
PAGE = 'libs/browser_demo/include/webcpp/browser_demo/page.hpp'
NATIVE = 'libs/browser_demo/include/webcpp/browser_demo/native.hpp'
FAKE_DEPENDENCY = 'libs/browser_demo/deps/include/fake_dependency.hpp'


def includes(source: Path) -> list[str]:
    """The headers an aggregate translation unit includes, in order."""
    return [line.removeprefix('#include <').removesuffix('>')
            for line in source.read_text().splitlines() if line.startswith('#include <')]


def user_config_text(root: Path) -> str:
    """The user-config.jam b2 reads for the scratch superproject root, found as every test of the
    build finds it: root's .local/, else $WEBCPP_USER_CONFIG."""
    return harness.user_config(root).read_text()


def compile_database(root: Path) -> subprocess.CompletedProcess:
    """Runs the scratch superproject's compile_commands.py, writing root/compile database/."""
    script = root / 'tools/lint/compile_commands.py'
    out = root / 'compile database/compile_commands.json'
    return subprocess.run([sys.executable, str(script), str(root), str(out), '--wasi-clang',
                           wasi_sdk_tool('clang++')],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          check=False, timeout=harness.TIMEOUT)


def lint(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    """Runs the scratch superproject's lint, and returns what it printed, stderr in stdout."""
    command = ['bash', str(root / LINT), '--clang-format', CLANG_FORMAT, '--clang-tidy', CLANG_TIDY,
               *arguments]
    return subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, check=False, timeout=harness.TIMEOUT)


def expect_clean(result: subprocess.CompletedProcess) -> None:
    """Asserts that the lint passed."""
    assert result.returncode == 0, (result.returncode, result.stdout[-6000:])
    assert result.stdout.rstrip().endswith('lint: clean'), result.stdout[-6000:]


def expect_alone(result: subprocess.CompletedProcess, rule: str, named: list[str],
                 spared: tuple[str, ...] = ()) -> None:
    """Asserts that rule failed and no other did, that the output names each of named, and that
    it names none of spared."""
    expect_failed(result, [rule], named, spared)


def expect_failed(result: subprocess.CompletedProcess, rules: list[str], named: list[str],
                  spared: tuple[str, ...] = ()) -> None:
    """Asserts that the rules failed, in the lint's order, and no other did, that the output names
    each of named, and that it names none of spared."""
    output = result.stdout
    assert result.returncode == 1, (result.returncode, output[-6000:])
    assert FAILED.findall(output) == rules, (rules, FAILED.findall(output), output[-6000:])
    for text in named:
        assert text in output, (text, output[-6000:])
    for text in spared:
        assert text not in output, (text, output[-6000:])


def write(root: Path, path: str, text: str) -> None:
    """Writes text to the file path of the scratch superproject root."""
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text)


def append(root: Path, path: str, text: str) -> None:
    """Appends text to the file path of the scratch superproject root."""
    with (root / path).open('a') as file:
        file.write(text)


def at(root: Path, path: str, text: str) -> str:
    """path:<line>:, the line being the one of path where text is, which must be there once."""
    lines = [number for number, line in enumerate((root / path).read_text().splitlines(), 1)
             if text in line]
    assert len(lines) == 1, (path, text, lines)
    return f'{path}:{lines[0]}:'


def test_clean_tree_passes(root):
    prepare(root)
    result = lint(root)
    expect_clean(result)
    # rejects.cpp, which webcpp.compile-fail expects not to compile, would fail clang-tidy; it is
    # left out of the analysis. fails.cpp, which webcpp.run-fail expects to fail when it runs,
    # compiles, and is analysed.
    analysed = TIDY_CLEAN.search(result.stdout)
    assert analysed, result.stdout[-6000:]
    assert int(analysed.group(1)) > 1, analysed.group(0)


def test_no_library_passes(root):
    prepare(root)
    shutil.rmtree(root / 'libs/demo')
    commit(root, 'No library')
    result = lint(root)
    expect_clean(result)
    # Only the superproject's own translation unit: the handler of tools/throw_exception.cpp.
    assert 'clang-tidy is clean (1 translation unit)' in result.stdout, result.stdout[-6000:]


def test_a_user_config_the_environment_names_is_read(root):
    # A checkout whose user-config.jam is not in .local/ but where $WEBCPP_USER_CONFIG says: the
    # cases that rewrite it read that one, as b2 does. The scratch's .local may hold no
    # user-config.jam to begin with, as in a checkout configured by $WEBCPP_USER_CONFIG alone.
    given = root / 'elsewhere/user-config.jam'
    given.parent.mkdir()
    given.write_text('using clang ;\n')
    (root / '.local/user-config.jam').unlink(missing_ok=True)
    saved = os.environ.get('WEBCPP_USER_CONFIG')
    os.environ['WEBCPP_USER_CONFIG'] = str(given)
    try:
        assert user_config_text(root) == given.read_text()
    finally:
        if saved is None:
            del os.environ['WEBCPP_USER_CONFIG']
        else:
            os.environ['WEBCPP_USER_CONFIG'] = saved


def test_compile_database_lists_what_b2_builds(root):
    out = root / 'compile database/compile_commands.json'
    script = root / 'tools/lint/compile_commands.py'
    completed = subprocess.run([sys.executable, str(script), str(root), str(out)],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               check=False, timeout=harness.TIMEOUT)
    assert completed.returncode == 0, completed.stdout[-6000:]
    entries = json.loads(out.read_text())
    aggregate = root / 'bin/aggregate/demo.cpp'
    files = {Path(entry['file']) for entry in entries}
    expected = {root / source for source in ('libs/demo/test/pass.cpp',
                                             'libs/demo/test/fails.cpp',
                                             'libs/demo/test/native_only.cpp',
                                             'libs/demo/test/suite_test.cpp',
                                             'libs/demo/test/parses_json.cpp',
                                             'libs/demo/example/hello.cpp',
                                             'libs/demo/example/catches.cpp',
                                             'tools/throw_exception.cpp',
                                             'tools/boost_test_runner.cpp',
                                             'tools/boost_json.cpp')}
    assert files == expected | {aggregate}, sorted(map(str, files))
    for entry in entries:
        assert entry['directory'] == str(root), entry
    # Each program as its Jamfile declares it, and again as b2 compiles it with
    # exception-handling=off, where the templates it instantiates meet -fno-exceptions: pass.cpp
    # has two commands; native_only.cpp too, though the test native_only_compiles compiles it a
    # second time, the same way.
    by_file: dict[Path, list[list[str]]] = {}
    for entry in entries:
        by_file.setdefault(Path(entry['file']), []).append(entry['arguments'])
    for source in ('pass.cpp', 'native_only.cpp', 'suite_test.cpp', 'parses_json.cpp'):
        commands = by_file[root / 'libs/demo/test' / source]
        assert ['-fno-exceptions' in command for command in commands] == [False, True], (
            source, commands)
    # A Boost.Test suite's framework is one object, with exceptions whatever the build asks, as
    # is catches, which declares that it needs them: each has its one command, and the database
    # names both. Boost.JSON's definitions are compiled once per variant.
    for source in ('tools/boost_test_runner.cpp', 'libs/demo/example/catches.cpp'):
        assert len(by_file[root / source]) == 1, (source, by_file[root / source])
        assert '-fno-exceptions' not in by_file[root / source][0], by_file[root / source]
    assert ('built with exceptions whatever the build asks, so analysed with them alone: '
            'libs/demo/example/catches.cpp, tools/boost_test_runner.cpp') in completed.stdout, (
        completed.stdout[-6000:])
    assert len(by_file[root / 'tools/boost_json.cpp']) == 2, by_file[root / 'tools/boost_json.cpp']
    # The handler is analysed as a program built without exceptions links it.
    handler = [entry['arguments'] for entry in entries
               if Path(entry['file']) == root / 'tools/throw_exception.cpp']
    assert len(handler) == 1 and '-fno-exceptions' in handler[0], handler
    for entry in entries:
        assert '-fno-rtti' not in entry['arguments'], entry
    # The aggregate includes every public header, and is compiled as headers-alone compiles one,
    # twice: as the tests are built, and as a program built without exceptions is, so that what a
    # header holds for that build alone (#ifdef BOOST_NO_EXCEPTIONS) is analysed too.
    assert aggregate.read_text().splitlines()[-2:] == ['#include <webcpp/demo.hpp>',
                                                       '#include <webcpp/demo/answer.hpp>'], (
        aggregate.read_text())
    aggregates = [entry['arguments'] for entry in entries if Path(entry['file']) == aggregate]
    assert len(aggregates) == 2, aggregates
    for command in aggregates:
        assert '-Ilibs/demo/include' in command and command[-1] == str(aggregate), command
    assert ['-fno-exceptions' in command for command in aggregates] == [False, True], aggregates
    # Each command without exceptions is b2's own, which defines no macro for it: Boost.Config
    # reads -fno-exceptions as BOOST_NO_EXCEPTIONS, as it does in a user's build.
    for command in (handler[0], aggregates[1]):
        assert boost_sees_no_exceptions(root, command), command
    assert not boost_sees_no_exceptions(root, aggregates[0]), aggregates[0]
    # A test project whose requirements name a library b2 builds, as xstate's do, puts the source
    # of a headers-alone translation unit under a directory of properties; the unit's test is
    # still found by its object, and the aggregate's command without exceptions with it.
    jamfile = root / 'libs/demo/test/Jamfile'
    text = jamfile.read_text()
    harness.replace(jamfile, 'import webcpp ;\n',
                    'project : requirements <library>/webcpp//boost_json ;\n\nimport webcpp ;\n')
    completed = compile_database(root)
    assert completed.returncode == 0, completed.stdout[-6000:]
    entries = json.loads(out.read_text())
    aggregates = [entry['arguments'] for entry in entries if Path(entry['file']) == aggregate]
    assert ['-fno-exceptions' in command for command in aggregates] == [False, True], aggregates
    jamfile.write_text(text)
    # A library whose public headers headers-alone does not compile has no command to give its
    # aggregate, and is named.
    harness.replace(root / 'libs/demo/test/Jamfile', 'webcpp.headers-alone demo : ../include ;\n',
                    '')
    completed = compile_database(root)
    assert completed.returncode == 1, completed.stdout[-6000:]
    assert 'libs/demo' in completed.stdout and 'headers-alone' in completed.stdout, (
        completed.stdout[-6000:])


WORLD = 'libs/component_demo/include/webcpp/component_demo/world.hpp'


def test_compile_database_reads_what_only_wasi_builds(root):
    add_component_demo(root)
    completed = compile_database(root)
    assert completed.returncode == 0, completed.stdout[-6000:]
    entries = json.loads((root / 'compile database/compile_commands.json').read_text())
    by_file: dict[Path, list[list[str]]] = {}
    for entry in entries:
        by_file.setdefault(Path(entry['file']), []).append(entry['arguments'])
    # The header of the world builds only for WASI, so the library's aggregate does, on each
    # version as it builds there, with exceptions, with the macro and the bindings of that
    # version, then as b2 builds the same unit with exception-handling=off, which defines
    # BOOST_NO_EXCEPTIONS through Boost.Config: wasip2 with and without, then wasip3.
    aggregate = root / 'bin/aggregate/component_demo.cpp'
    assert aggregate.read_text().splitlines()[-2:] == [
        '#include <webcpp/component_demo.hpp>', '#include <webcpp/component_demo/world.hpp>'], (
        aggregate.read_text())
    commands = by_file[aggregate]
    assert len(commands) == 4, commands
    for command, (version, without) in zip(commands, (('p2', False), ('p2', True), ('p3', False),
                                                      ('p3', True))):
        assert f'--target=wasm32-wasi{version}' in command, command
        assert ('-fno-exceptions' in command) == without, command
        assert ('-fwasm-exceptions' in command) != without, command
        assert f'-DWEBCPP_COMPONENT_DEMO_{version.upper()}' in command, command
        assert any(word.endswith(f'generated/component_demo/demo-bindings-{version}')
                   for word in command), command
        assert boost_sees_no_exceptions(root, command) == without, command
    # The programs that declare no native target are analysed as wasip2 builds them, with
    # exceptions and without; the native one natively, both ways.
    for source in ('bindings.cpp', 'answers.cpp'):
        commands = by_file[root / 'libs/component_demo/test' / source]
        assert ['-fno-exceptions' in command for command in commands] == [False, True], commands
        for command in commands:
            assert '--target=wasm32-wasip2' in command, command
    native = by_file[root / 'libs/component_demo/test/native_alone.cpp']
    assert ['-fno-exceptions' in command for command in native] == [False, True], native
    for command in native:
        assert not any(word.startswith('--target') for word in command), command
    # demo's aggregate builds natively, and keeps its native command and the one without
    # exceptions; the handler is analysed once, natively without exceptions.
    demo = by_file[root / 'bin/aggregate/demo.cpp']
    assert ['-fno-exceptions' in command for command in demo] == [False, True], demo
    for command in demo:
        assert not any(word.startswith('--target') for word in command), command
    handler = by_file[root / 'tools/throw_exception.cpp']
    assert len(handler) == 1 and '-fno-exceptions' in handler[0], handler
    assert not any(word.startswith('--target') for word in handler[0]), handler
    # A public header that no target compiles alone fails the database, naming it.
    jamfile = root / 'libs/component_demo/test/Jamfile'
    text = jamfile.read_text()
    harness.replace(jamfile, 'webcpp.headers-alone component_demo : ../include : '
                    'component_demo/world.hpp\n  : <library>/webcpp/component_demo//demo-http : '
                    'wasip2 wasip3 ;\n', '')
    completed = compile_database(root)
    assert completed.returncode == 1, completed.stdout[-6000:]
    assert f'no target compiles alone {WORLD}' in completed.stdout, completed.stdout[-6000:]
    jamfile.write_text(text)
    # A target some library declares, whose toolset is not configured, fails it, naming the
    # target and its toolset.
    configured = user_config_text(root)
    harness.configure(root, re.sub(r'^using clang : wasip3 :.*?;\n', '', configured,
                                   flags=re.MULTILINE | re.DOTALL))
    completed = compile_database(root)
    assert completed.returncode == 1, completed.stdout[-6000:]
    for text in ('b2 could not dry-run the programs for wasip3, which libs/component_demo, '
                 'libs/demo declare, with toolset=clang-wasip3',
                 'is that toolset configured'):
        assert text in completed.stdout, (text, completed.stdout[-6000:])


def test_an_aggregate_no_units_options_compile_names_each(root):
    add_component_demo(root)
    # A third public header that compiles alone only with a macro of its own: the aggregate,
    # which includes every header, compiles with the options of none of the three headers-alone
    # units, and the database names each unit's object with its first error.
    write(root, 'libs/component_demo/include/webcpp/component_demo/planted.hpp',
          '#ifndef WEBCPP_PLANTED\n#error "planted.hpp needs WEBCPP_PLANTED"\n#endif\n')
    append(root, 'libs/component_demo/test/Jamfile',
           'webcpp.headers-alone component_demo : ../include : component_demo/planted.hpp\n'
           '  : <define>WEBCPP_PLANTED : wasip2 wasip3 ;\n')
    completed = compile_database(root)
    assert completed.returncode == 1, completed.stdout[-6000:]
    said = completed.stdout[completed.stdout.index('its aggregate translation unit'):]
    for unit, error in (('alone-component_demo', 'planted.hpp needs WEBCPP_PLANTED'),
                        ('alone-component_demo-planted', 'builds for wasip2 or wasip3'),
                        ('alone-component_demo-world', 'planted.hpp needs WEBCPP_PLANTED')):
        named = re.search(rf'^- \S*/{unit}\.test/\S*/{unit}\.o: .*{re.escape(error)}', said,
                          re.MULTILINE)
        assert named, (unit, error, said[-6000:])


def test_wasi_sdk_is_told_by_the_compiler_itself(root):
    # A compiler is wasi-sdk's clang++ when it says its resource directory is wasi-sdk's, with
    # share/wasi-sysroot three levels above it, whatever runs it: a script that runs wasi-sdk's
    # clang++, as a ccache wrapper does, is; a script that runs another clang, from a directory
    # with a wasi-sysroot beside it, is not, and the refusal says what was asked.
    wrapper = root / 'wrapper/bin/clang++'
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(f'#!/bin/sh\nexec "{wasi_sdk_tool("clang++")}" "$@"\n')
    wrapper.chmod(0o755)
    assert compile_commands.wasi_sdk(str(wrapper)), wrapper
    impostor = root / 'impostor/bin/clang++'
    impostor.parent.mkdir(parents=True)
    (root / 'impostor/share/wasi-sysroot').mkdir(parents=True)
    impostor.write_text('#!/bin/sh\nexec clang++ "$@"\n')
    impostor.chmod(0o755)
    assert not compile_commands.wasi_sdk(str(impostor)), impostor
    try:
        compile_commands.check_compiler('wasip2', 'x.cpp', [str(impostor), '-c', 'x.cpp'])
    except compile_commands.Failure as failure:
        said = str(failure)
    else:
        raise AssertionError(f'{impostor} was taken for wasi-sdk\'s clang++')
    resource = subprocess.run(['clang++', '-print-resource-dir'], capture_output=True, text=True,
                              check=True).stdout.strip()
    assert (f"x.cpp is compiled for wasip2 by {impostor}, which is not wasi-sdk's clang++: "
            f'{impostor} -print-resource-dir names {resource}, with no share/wasi-sysroot three '
            'levels above it') in said, said


def test_wasm_compiler_not_from_wasi_sdk_fails_by_name(root):
    prepare(root)
    add_component_demo(root)
    # A toolset of wasip2 whose compiler is not wasi-sdk's clang++: a script that runs a clang
    # of another installation, as em++ runs a clang of its own, whose resource directory is that
    # installation's, with no share/wasi-sysroot three levels above it. clang-tidy would read its
    # commands as native ones and give them the host's --target, so the database refuses them,
    # naming the file and the compiler. The clang it runs is wasi-sdk's, given the resource
    # directory of the other installation, a link to wasi-sdk's own: it compiles what the
    # Jamroot's check of Boost compiles for wasip2, whose -mllvm -wasm-use-legacy-eh=false the
    # host's clang++ may not know (Clang 18 refuses it, and the check failed before the database
    # could name the compiler).
    configured = user_config_text(root)
    using = re.search(r'^using clang : wasip2 : (\S+)', configured, re.MULTILINE)
    assert using is not None, configured
    clang = wasi_sdk_tool('clang++')
    resource = subprocess.run([clang, '-print-resource-dir'], capture_output=True, text=True,
                              check=True).stdout.strip()
    other = root / 'other sdk'
    (other / 'lib/clang').mkdir(parents=True)
    (other / 'lib/clang' / Path(resource).name).symlink_to(resource)
    compiler = other / 'bin/em++'
    compiler.parent.mkdir(parents=True)
    compiler.write_text(f'#!/bin/sh\nexec "{clang}" -resource-dir '
                        f'"{other}/lib/clang/{Path(resource).name}" "$@"\n')
    compiler.chmod(0o755)
    harness.configure(root, configured.replace(using.group(0),
                                               f'using clang : wasip2 : "{compiler}"', 1))
    named = ('libs/component_demo/', f'is compiled for wasip2 by {compiler}',
             "which is not wasi-sdk's clang++")
    completed = compile_database(root)
    assert completed.returncode == 1, completed.stdout[-6000:]
    for text in named:
        assert text in completed.stdout, (text, completed.stdout[-6000:])
    expect_alone(lint(root), 'clang-tidy', [*named, 'compile_commands.py wrote no compilation '
                                            'database'])


def test_clang_tidy_reads_what_only_wasi_builds(root):
    prepare(root)
    add_component_demo(root)
    # The fixture is clean, analysed as wasi-sdk's clang++ builds it.
    expect_clean(lint(root))
    # A finding in each branch of the header of the world, which only wasip2's aggregate and only
    # wasip3's read, and one in a program that declares no native target, behind __wasip2__,
    # which a host target given to clang-tidy would hide.
    harness.replace(root / WORLD, '    return "p2";\n}\n',
                    '    return "p2";\n}\n\n/** Planted.\n\n    @return 2.\n*/\n'
                    'constexpr int PlantedTwo() noexcept {\n    return 2;\n}\n')
    harness.replace(root / WORLD, '    return "p3";\n}\n',
                    '    return "p3";\n}\n\n/** Planted.\n\n    @return 3.\n*/\n'
                    'constexpr int PlantedThree() noexcept {\n    return 3;\n}\n')
    program = 'libs/component_demo/test/bindings.cpp'
    append(root, program, '\n#ifdef __wasip2__\nnamespace {\n\nint PlantedWasi() {\n'
                          '    return 2;\n}\n\n}  // namespace\n#endif\n')
    result = lint(root)
    expect_alone(result, 'clang-tidy', [f"{at(root, WORLD, 'PlantedTwo')}",
                                        f"{at(root, WORLD, 'PlantedThree')}",
                                        f"{at(root, program, 'PlantedWasi')}"])
    for name in ('PlantedTwo', 'PlantedThree', 'PlantedWasi'):
        assert f"invalid case style for function '{name}'" in result.stdout, (
            name, result.stdout[-6000:])


def test_clang_tidy_reads_what_an_own_lane_builds(root):
    prepare(root)
    add_component_demo(root)
    # A served program runs in an own lane, which takes it out of the test and example
    # directories' requests: it is analysed all the same, as the first target of its lane builds
    # it, and a finding in it fails the lint.
    program = 'libs/component_demo/test/answers.cpp'
    append(root, program, '\nnamespace {\n\nint PlantedServed() {\n    return 2;\n}\n\n'
                          '}  // namespace\n')
    result = lint(root)
    expect_alone(result, 'clang-tidy', [at(root, program, 'PlantedServed')])
    assert "invalid case style for function 'PlantedServed'" in result.stdout, (
        result.stdout[-6000:])
    # A served program in no own lane fails `b2 declared-lanes`, and with it the database, which
    # would otherwise analyse it nowhere.
    harness.replace(root / 'libs/component_demo/test/Jamfile',
                    'webcpp.lane http : answers : wasip2 wasip3 ;\n', '')
    completed = compile_database(root)
    assert completed.returncode == 1, completed.stdout[-6000:]
    assert ('webcpp.serve answers.cpp in libs/component_demo/test/Jamfile is in no own lane' in
            completed.stdout), completed.stdout[-6000:]


def test_compile_database_gives_each_target_its_aggregate(root):
    add_browser_demo(root)
    completed = compile_database(root)
    assert completed.returncode == 0, completed.stdout[-6000:]
    entries = json.loads((root / 'compile database/compile_commands.json').read_text())
    by_file: dict[Path, list[list[str]]] = {}
    for entry in entries:
        by_file.setdefault(Path(entry['file']), []).append(entry['arguments'])
    # No one target builds every public header of browser_demo: native.hpp builds only natively,
    # page.hpp only on emscripten. Each target its headers-alone units run on has an aggregate of
    # the headers it builds.
    aggregate = root / 'bin/aggregate'
    native = aggregate / 'browser_demo-native.cpp'
    emscripten = aggregate / 'browser_demo-emscripten.cpp'
    assert includes(native) == ['webcpp/browser_demo.hpp', 'webcpp/browser_demo/native.hpp'], (
        native.read_text())
    assert includes(emscripten) == ['webcpp/browser_demo.hpp', 'webcpp/browser_demo/page.hpp'], (
        emscripten.read_text())
    assert not (aggregate / 'browser_demo.cpp').exists()
    # The native one is compiled with the options of native.hpp's unit, which name the fake
    # dependency's directory. Its twin without exceptions leaves native.hpp out, since its unit
    # declares <exception-handling>on, and the database names it; a twin of its own, it includes
    # page.hpp no more than the aggregate does.
    commands = by_file[native]
    assert len(commands) == 1 and '-fno-exceptions' not in commands[0], commands
    assert '-Ilibs/browser_demo/deps/include' in commands[0], commands
    twin = aggregate / 'browser_demo-native-exception-handling-off.cpp'
    assert includes(twin) == ['webcpp/browser_demo.hpp'], twin.read_text()
    assert len(by_file[twin]) == 1 and '-fno-exceptions' in by_file[twin][0], by_file[twin]
    assert boost_sees_no_exceptions(root, by_file[twin][0]), by_file[twin]
    assert ('left out of the analysis without exceptions, their headers-alone units built with '
            f'exceptions whatever the build asks: {NATIVE}') in completed.stdout, (
        completed.stdout[-6000:])
    # The emscripten one is analysed as em++ compiles it, by wasi-sdk's clang++ with the words
    # em++ --cflags prints for the command's own options before b2's: with b2's
    # -fwasm-exceptions, the legacy encoding em++ compiles with, and none of the words of a
    # build without exceptions, which clang refuses beside -fwasm-exceptions. Its twin is the
    # same unit with exception-handling=off, after Emscripten's -fignore-exceptions.
    commands = by_file[emscripten]
    assert ['-fno-exceptions' in command for command in commands] == [False, True], commands
    for command in commands:
        assert compile_commands.wasi_sdk(command[0]), command
        assert 'wasm32-unknown-emscripten' in command, command
        assert any(word.startswith('--sysroot=') for word in command), command
    with_exceptions, without = commands
    assert '-wasm-use-legacy-eh' in with_exceptions, with_exceptions
    assert '-fignore-exceptions' not in with_exceptions, with_exceptions
    assert '-enable-emscripten-sjlj' not in with_exceptions, with_exceptions
    assert without.index('-fignore-exceptions') < without.index('-fno-exceptions'), without
    assert boost_sees_no_exceptions(root, without), without
    assert not boost_sees_no_exceptions(root, with_exceptions), with_exceptions
    # The program that only emscripten builds is analysed there, with exceptions and without.
    page = by_file[root / 'libs/browser_demo/example/page.cpp']
    assert ['-fno-exceptions' in command for command in page] == [False, True], page
    for command in page:
        assert compile_commands.wasi_sdk(command[0]), command
        # An Emscripten setting such as -sWASM_WORKERS is em++'s, which gives clang the words it
        # stands for, and clang refuses the setting itself.
        assert '-sWASM_WORKERS' not in command, command
        assert '-D__EMSCRIPTEN_SHARED_MEMORY__=1' in command, command
    # The programs both targets build are analysed natively, as before.
    for command in by_file[root / 'libs/browser_demo/test/reads_test.cpp']:
        assert 'wasm32-unknown-emscripten' not in command, command
    # demo's headers build whole natively: its one aggregate keeps its name and its two commands.
    demo = by_file[aggregate / 'demo.cpp']
    assert ['-fno-exceptions' in command for command in demo] == [False, True], demo
    # An emscripten toolset whose compiler is not Emscripten's em++, a script that runs the
    # host's clang++, fails the database, naming the file and the compiler.
    configured = user_config_text(root)
    using = re.search(r'^using emscripten : : (\S+)', configured, re.MULTILINE)
    assert using is not None, configured
    impostor = root / 'other sdk/bin/em++'
    impostor.parent.mkdir(parents=True)
    impostor.write_text('#!/bin/sh\nexec clang++ "$@"\n')
    impostor.chmod(0o755)
    harness.configure(root, configured.replace(using.group(0),
                                               f'using emscripten : : "{impostor}"', 1))
    completed = compile_database(root)
    assert completed.returncode == 1, completed.stdout[-6000:]
    for text in ('libs/browser_demo/', f'is compiled for emscripten by {impostor}',
                 "which is neither wasi-sdk's clang++ nor Emscripten's em++"):
        assert text in completed.stdout, (text, completed.stdout[-6000:])


def test_clang_tidy_reads_what_only_one_target_builds(root):
    prepare(root)
    add_browser_demo(root)
    # browser_demo is clean, each of its aggregates analysed as its target builds it.
    expect_clean(lint(root))
    # A finding in page.hpp, which only emscripten builds, read by wasi-sdk's clang 23 through
    # Emscripten's clang 24 headers, and one in native.hpp, which builds only against the fake
    # dependency.
    harness.replace(root / PAGE, '}  // namespace webcpp::browser_demo\n',
                    '/** Planted.\n\n    @return 2.\n*/\n'
                    'constexpr int PlantedPage() noexcept {\n    return 2;\n}\n\n'
                    '}  // namespace webcpp::browser_demo\n')
    harness.replace(root / NATIVE, '}  // namespace webcpp::browser_demo\n',
                    '/** Planted.\n\n    @return 3.\n*/\n'
                    'constexpr int PlantedNative() noexcept {\n    return 3;\n}\n\n'
                    '}  // namespace webcpp::browser_demo\n')
    result = lint(root)
    expect_alone(result, 'clang-tidy', [at(root, PAGE, 'PlantedPage'),
                                        at(root, NATIVE, 'PlantedNative')])
    for name in ('PlantedPage', 'PlantedNative'):
        assert f"invalid case style for function '{name}'" in result.stdout, (
            name, result.stdout[-6000:])


def test_a_dependency_s_warnings_are_not_ours(root):
    # A regression pin, which passes before and after the lint reads native.hpp: what clang-tidy
    # finds in a dependency's header, here the fake one that native.hpp includes, is not
    # reported, since .clang-tidy's HeaderFilterRegex keeps to webcpp's own headers.
    prepare(root)
    add_browser_demo(root)
    harness.replace(root / FAKE_DEPENDENCY, '}  // namespace fake_dependency\n',
                    'inline int PlantedDependency() {\n    int value;\n    value = 4;\n'
                    '    return value;\n}\n\n}  // namespace fake_dependency\n')
    result = lint(root)
    expect_clean(result)
    assert 'fake_dependency.hpp:' not in result.stdout, result.stdout[-6000:]


def test_a_compiled_boost_library_s_sources_are_not_analysed(root):
    # Boost.URL's sources, which /webcpp//boost_url compiles from Boost's tree outside the tree
    # the lint reads (.local/boost-source, or a CI runner's prefix), are Boost's: the database
    # lists the program that links them, and none of theirs.
    prepare(root)
    append(root, 'libs/demo/test/Jamfile',
           'webcpp.run parses_url : parses_url.cpp : <library>/webcpp//boost_url ;\n')
    (root / 'libs/demo/test/parses_url.cpp').write_text(
        CPP + '\n'
        '#include <boost/url/parse.hpp>\n'
        '\n'
        'int main() {\n'
        '    return boost::urls::parse_uri("http://example.com").has_value() ? 0 : 1;\n'
        '}\n')
    commit(root / 'libs/demo', 'A program that links Boost.URL')
    completed = compile_database(root)
    assert completed.returncode == 0, completed.stdout[-6000:]
    files = {entry['file'] for entry in json.loads(
        (root / 'compile database/compile_commands.json').read_text())}
    assert str(root / 'libs/demo/test/parses_url.cpp') in files, sorted(files)
    assert not [file for file in files if '/libs/url/src/' in file], sorted(files)
    # Above, b2 names Boost's sources by their physical path, which on macOS is outside root
    # (/var is /private/var), so the case also asks of_the_tree of each place by itself.
    for source, ours in (('libs/demo/test/parses_url.cpp', True),
                         ('.local/boost-source/libs/url/src/url.cpp', False),
                         (str(root / '.local/boost-source/libs/url/src/url.cpp'), False),
                         ('third_party/libs/nativejson-benchmark/src/config.h', False),
                         (str(root.parent / 'boost source/libs/url/src/url.cpp'), False)):
        assert compile_commands.of_the_tree(str(root), source) == ours, (source, ours)
    expect_clean(lint(root))


def test_clang_tidy_refuses_a_throw_on_each_target_without_exceptions(root):
    prepare(root)
    add_browser_demo(root)
    # A throw outside a template: in browser_demo.hpp, which the native twin reads; in page.hpp,
    # which the emscripten twin reads; and in native.hpp, which no twin reads, since its unit
    # declares <exception-handling>on. clang-tidy refuses the first two; the bare throw rule,
    # which reads the text, refuses all three.
    planted = ('#include <stdexcept>\n\nnamespace webcpp::browser_demo {\n\n'
               '/** Returns the level it is given, refusing a negative one.\n\n'
               '    @param level The level.\n    @return level.\n*/\n'
               'inline int planted_strict(int level) {\n    if (level < 0) {\n'
               '        throw std::domain_error("a negative level");\n    }\n'
               '    return level;\n}\n')
    for header, rules in ((BROWSER_DEMO, ['clang-tidy', 'bare throw']),
                          (PAGE, ['clang-tidy', 'bare throw']), (NATIVE, ['bare throw'])):
        text = (root / header).read_text()
        harness.replace(root / header, '\nnamespace webcpp::browser_demo {\n', '\n' + planted)
        result = lint(root)
        throw = at(root, header, 'throw std::domain_error')
        expect_failed(result, rules, [f'{throw} a bare throw'])
        disabled = "cannot use 'throw' with exceptions disabled"
        assert (disabled in result.stdout) == ('clang-tidy' in rules), (header,
                                                                        result.stdout[-6000:])
        (root / header).write_text(text)


def test_a_native_header_that_needs_no_exceptions_has_its_twin(root):
    prepare(root)
    add_browser_demo(root)
    # plain.hpp builds only natively too, against the fake dependency's directory, but compiles
    # without exceptions: a header of the native backend that wraps nothing that throws, beside
    # native.hpp, which does. A call of webcpp.headers-alone of its own, without
    # <exception-handling>on, puts it in the native twin, which the call of native.hpp leaves it
    # out of: the database names native.hpp alone as left out, and clang-tidy refuses a throw in
    # plain.hpp as it does one in browser_demo.hpp.
    plain = 'libs/browser_demo/include/webcpp/browser_demo/plain.hpp'
    write(root, 'libs/browser_demo/deps/include/fake_plain.hpp',
          CPP + '\n#ifndef FAKE_PLAIN_HPP\n#define FAKE_PLAIN_HPP\n\nnamespace fake_plain {\n\n'
          '// The successor of value.\ninline int next(int value) noexcept {\n'
          '    return value + 1;\n}\n\n}  // namespace fake_plain\n\n#endif\n')
    write(root, plain,
          CPP + '\n#ifndef WEBCPP_BROWSER_DEMO_PLAIN_HPP\n#define WEBCPP_BROWSER_DEMO_PLAIN_HPP\n\n'
          '#include <fake_plain.hpp>\n\nnamespace webcpp::browser_demo {\n\n'
          '/** Returns the level after the one it is given.\n\n'
          '    @param level The level.\n    @return The next level.\n*/\n'
          'inline int plain_next(int level) noexcept {\n'
          '    return fake_plain::next(level);\n}\n\n'
          '}  // namespace webcpp::browser_demo\n\n#endif\n')
    append(root, 'libs/browser_demo/test/Jamfile',
           'webcpp.headers-alone browser_demo : ../include : browser_demo/plain.hpp\n'
           '  : <library>/webcpp/browser_demo//native : native ;\n')
    completed = compile_database(root)
    assert completed.returncode == 0, completed.stdout[-6000:]
    twin = root / 'bin/aggregate/browser_demo-native-exception-handling-off.cpp'
    assert includes(twin) == ['webcpp/browser_demo.hpp', 'webcpp/browser_demo/plain.hpp'], (
        twin.read_text())
    assert ('left out of the analysis without exceptions, their headers-alone units built with '
            f'exceptions whatever the build asks: {NATIVE}\n') in completed.stdout, (
        completed.stdout[-6000:])
    expect_clean(lint(root))
    harness.replace(root / plain, '#include <fake_plain.hpp>\n',
                    '#include <fake_plain.hpp>\n\n#include <stdexcept>\n')
    harness.replace(root / plain, '}  // namespace webcpp::browser_demo\n',
                    '/** Returns the level it is given, refusing a negative one.\n\n'
                    '    @param level The level.\n    @return level.\n*/\n'
                    'inline int planted_strict(int level) {\n    if (level < 0) {\n'
                    '        throw std::domain_error("a negative level");\n    }\n'
                    '    return level;\n}\n\n}  // namespace webcpp::browser_demo\n')
    result = lint(root)
    expect_failed(result, ['clang-tidy', 'bare throw'],
                  [f'{at(root, plain, "throw std::domain_error")} a bare throw',
                   "cannot use 'throw' with exceptions disabled"])


def boost_sees_no_exceptions(root: Path, command: list[str]) -> bool:
    """Whether Boost.Config defines BOOST_NO_EXCEPTIONS under the options of the compile command,
    run in root, as the database's commands are."""
    output = command.index('-o')
    options = [word for word in command[:output] + command[output + 2:-1] if word != '-c']
    completed = subprocess.run([*options, '-E', '-dM', '-x', 'c++', '-'],
                               input='#include <boost/config.hpp>\n', cwd=root,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               check=False, timeout=harness.TIMEOUT)
    assert completed.returncode == 0, (options, completed.stdout[-6000:])
    return re.search(r'^#define BOOST_NO_EXCEPTIONS\b', completed.stdout, re.MULTILINE) is not None


def test_a_failed_check_of_the_database_runs_the_other_rules(root):
    prepare(root)
    # A file of the database compiled both by wasi-sdk's clang++ and by another compiler cannot be
    # analysed, which fails clang-tidy, by name; every later rule still runs, and the summary
    # names clang-tidy alone. The scratch copy's compile_commands.py writes such a database, its
    # wasi-sdk's clang++ through a link, which the lint does not read.
    (root / 'wasi-clang++').symlink_to(Path(CLANG_TIDY).parent / 'clang++')
    script = root / 'tools/lint/compile_commands.py'
    harness.replace(script, 'entries = database(root, wasi_clang)\n',
                    'entries = planted(root, wasi_clang)\n')
    harness.replace(script, 'def main(arguments: list[str]) -> int:\n',
                    'def planted(root: str, _: str | None) -> list[dict[str, object]]:\n'
                    '    """A database whose one file has a command of each kind."""\n'
                    "    source = os.path.join(root, 'tools/throw_exception.cpp')\n"
                    "    compilers = [os.path.join(root, 'wasi-clang++'), 'c++']\n"
                    "    return [{'directory': root, 'file': source, 'arguments': [compiler, "
                    "source]}\n"
                    '            for compiler in compilers]\n'
                    '\n\n'
                    'def main(arguments: list[str]) -> int:\n')
    expect_alone(lint(root), 'clang-tidy', [
        "tools/throw_exception.cpp is compiled both by wasi-sdk's clang++ and by another compiler",
        '== include boundaries ==', 'every library keeps to its declared include boundaries'])


def test_clang_format(root):
    prepare(root)
    path = 'libs/demo/test/unformatted.cpp'
    write(root, path, CPP + '\nint  unformatted( ) {return 42;}\n')
    expect_alone(lint(root), 'clang-format', [at(root, path, 'unformatted(')])


def test_clang_tidy_reads_what_b2_expects_to_build(root):
    prepare(root)
    # An ordinary test beside rejects.cpp is analysed, with the helper header it includes, and so
    # is a run-fail test, which compiles, and a public header that no test includes, through the
    # library's aggregate translation unit; a second source that does not compile on purpose is
    # not.
    helper = 'libs/demo/test/planted_helper.hpp'
    write(root, helper, CPP + '\n'
          '#ifndef WEBCPP_TEST_DEMO_PLANTED_HELPER_HPP\n'
          '#define WEBCPP_TEST_DEMO_PLANTED_HELPER_HPP\n'
          '\n'
          'namespace webcpp::test {\n'
          '\n'
          'inline int helped() {\n'
          '    int helped_value;\n'
          '    helped_value = 2;\n'
          '    return helped_value;\n'
          '}\n'
          '\n'
          '}  // namespace webcpp::test\n'
          '\n'
          '#endif\n')
    test = 'libs/demo/test/planted.cpp'
    write(root, test, CPP + '\n'
          '#include "planted_helper.hpp"\n'
          '\n'
          'int main() {\n'
          '    int value;\n'
          '    value = 0;\n'
          '    return value;\n'
          '}\n')
    header = 'libs/demo/include/webcpp/demo/planted.hpp'
    write(root, header, CPP + '\n'
          '#ifndef WEBCPP_DEMO_PLANTED_HPP\n'
          '#define WEBCPP_DEMO_PLANTED_HPP\n'
          '\n'
          'namespace webcpp::demo {\n'
          '\n'
          '/** Returns the value it leaves uninitialized at first.\n'
          '\n'
          '    @return 1.\n'
          '*/\n'
          'inline int planted() {\n'
          '    int value;\n'
          '    value = 1;\n'
          '    return value;\n'
          '}\n'
          '\n'
          '}  // namespace webcpp::demo\n'
          '\n'
          '#endif\n')
    run_fail = 'libs/demo/test/planted_fails.cpp'
    write(root, run_fail, CPP + '\n'
          'int main() {\n'
          '    int status;\n'
          '    status = 1;\n'
          '    return status;\n'
          '}\n')
    write(root, 'libs/demo/test/also_rejects.cpp', CPP + '\n'
          'int main() {\n'
          '    int value;\n'
          '    return undeclared;\n'
          '}\n')
    # Nor is a source that must stop with the error it states (webcpp.compile-diagnostic), which
    # b2 compiles as a test that passes.
    write(root, 'libs/demo/test/states_its_error.cpp', CPP + '\n'
          '// expected-error@+1 {{stated}}\n'
          '#error "stated"\n'
          '\n'
          'int main() {\n'
          '    int value;\n'
          '    return undeclared;\n'
          '}\n')
    append(root, 'libs/demo/test/Jamfile',
           'webcpp.run planted : planted.cpp ;\n'
           'webcpp.run-fail planted_fails : planted_fails.cpp ;\n'
           'webcpp.compile-fail also_rejects : also_rejects.cpp ;\n'
           'webcpp.compile-diagnostic states_its_error : states_its_error.cpp ;\n')
    expect_alone(lint(root), 'clang-tidy',
                 [at(root, test, 'int value;'), at(root, helper, 'int helped_value;'),
                  at(root, header, 'int value;'), at(root, run_fail, 'int status;')],
                 spared=('also_rejects', 'rejects.cpp', 'states_its_error'))


def test_clang_tidy_refuses_a_throw_a_build_without_exceptions_cannot_compile(root):
    prepare(root)
    # A public header that throws outside #ifndef BOOST_NO_EXCEPTIONS: once in an inline
    # function, which the aggregate compiled without exceptions refuses, and once in a template,
    # which clang refuses only where it is instantiated: in the test that calls it, compiled
    # without exceptions too. Each fails clang-tidy, naming its line, and the bare throw rule,
    # which reads the header's text, fails too.
    header = 'libs/demo/include/webcpp/demo/checked.hpp'
    write(root, header, CPP + '\n'
          '#ifndef WEBCPP_DEMO_CHECKED_HPP\n'
          '#define WEBCPP_DEMO_CHECKED_HPP\n'
          '\n'
          '#include <stdexcept>\n'
          '\n'
          'namespace webcpp::demo {\n'
          '\n'
          '/** Returns the count it is given, refusing a negative one.\n'
          '\n'
          '    @param count The count.\n'
          '    @return count.\n'
          '*/\n'
          'template <typename Count>\n'
          'Count planted_checked(Count count) {\n'
          '    if (count < 0) {\n'
          '        throw std::invalid_argument("a negative count");\n'
          '    }\n'
          '    return count;\n'
          '}\n'
          '\n'
          '/** Returns the level it is given, refusing a negative one.\n'
          '\n'
          '    @param level The level.\n'
          '    @return level.\n'
          '*/\n'
          'inline int planted_strict(int level) {\n'
          '    if (level < 0) {\n'
          '        throw std::domain_error("a negative level");\n'
          '    }\n'
          '    return level;\n'
          '}\n'
          '\n'
          '}  // namespace webcpp::demo\n'
          '\n'
          '#endif\n')
    write(root, 'libs/demo/test/checks.cpp', CPP + '\n'
          '#include <webcpp/demo/checked.hpp>\n'
          '\n'
          '#include <boost/core/lightweight_test.hpp>\n'
          '\n'
          '// NOLINTNEXTLINE(bugprone-exception-escape)\n'
          'int main() {\n'
          '    BOOST_TEST_EQ(webcpp::demo::planted_checked(2), 2);\n'
          '    BOOST_TEST_EQ(webcpp::demo::planted_strict(3), 3);\n'
          '    return boost::report_errors();\n'
          '}\n')
    append(root, 'libs/demo/test/Jamfile',
           'webcpp.run checks : checks.cpp : <library>/webcpp/demo//demo ;\n')
    expect_failed(lint(root), ['clang-tidy', 'bare throw'],
                  [at(root, header, 'throw std::invalid_argument'),
                   at(root, header, 'throw std::domain_error'),
                   "cannot use 'throw' with exceptions disabled"])


def test_clang_tidy_reads_what_only_a_build_without_exceptions_compiles(root):
    prepare(root)
    # Code that only a program built without exceptions compiles: the body of the handler, and a
    # public header's #ifdef BOOST_NO_EXCEPTIONS block, which no test reaches with exceptions on.
    header = 'libs/demo/include/webcpp/demo/without_exceptions.hpp'
    write(root, header, CPP + '\n'
          '#ifndef WEBCPP_DEMO_WITHOUT_EXCEPTIONS_HPP\n'
          '#define WEBCPP_DEMO_WITHOUT_EXCEPTIONS_HPP\n'
          '\n'
          '#include <boost/config.hpp>\n'
          '\n'
          'namespace webcpp::demo {\n'
          '\n'
          '#ifdef BOOST_NO_EXCEPTIONS\n'
          '\n'
          '/** Returns the value it leaves uninitialized at first.\n'
          '\n'
          '    @return 3.\n'
          '*/\n'
          'inline int unexceptional() {\n'
          '    int value;\n'
          '    value = 3;\n'
          '    return value;\n'
          '}\n'
          '\n'
          '#endif\n'
          '\n'
          '}  // namespace webcpp::demo\n'
          '\n'
          '#endif\n')
    handler = 'tools/throw_exception.cpp'
    harness.replace(root / handler, 'namespace boost {\n\n',
                    'namespace boost {\n'
                    '\n'
                    'int planted_status() {\n'
                    '    int status;\n'
                    '    status = 4;\n'
                    '    return status;\n'
                    '}\n'
                    '\n')
    # The same block in a header that builds only for WASI, which no WASI program reaches without
    # exceptions either, since every target builds with them.
    add_component_demo(root)
    world = 'libs/component_demo/include/webcpp/component_demo/world.hpp'
    harness.replace(root / world, '#include <string_view>\n',
                    '#include <boost/config.hpp>\n'
                    '\n'
                    '#include <string_view>\n')
    harness.replace(root / world, '}  // namespace webcpp::component_demo\n',
                    '#ifdef BOOST_NO_EXCEPTIONS\n'
                    '\n'
                    '/** Returns the value it leaves uninitialized at first.\n'
                    '\n'
                    '    @return 2.\n'
                    '*/\n'
                    'inline int unexceptional() {\n'
                    '    int value;\n'
                    '    value = 2;\n'
                    '    return value;\n'
                    '}\n'
                    '\n'
                    '#endif\n'
                    '\n'
                    '}  // namespace webcpp::component_demo\n')
    expect_alone(lint(root), 'clang-tidy',
                 [at(root, header, 'int value;'), at(root, handler, 'int status;'),
                  at(root, world, 'int value;')])


def test_blocking_io_context_call(root):
    prepare(root)
    path = 'libs/demo/test/drives.cpp'
    write(root, path, CPP + '\n'
          'void drive() {\n'
          '    boost::asio::io_context context;\n'
          '    context.run();\n'
          '}\n')
    # An io_context declared through a namespace alias is found too, and a line that says why
    # after lint-run: is accepted; one that says nothing after it is not.
    aliased = 'libs/demo/test/relays.cpp'
    write(root, aliased, CPP + '\n'
          'namespace asio = boost::asio;\n'
          '\n'
          'void relay(int timeout) {\n'
          '    asio::io_context io;\n'
          '    io.run_for(timeout);\n'
          '    asio::io_context relays;\n'
          '    relays.run_for(timeout);  // lint-run: the memory relays post to it\n'
          '    relays.run_one();         // lint-run:\n'
          '}\n')
    expect_alone(lint(root), 'io_context::run', [
        at(root, path, 'context.run()'), at(root, aliased, 'io.run_for('),
        at(root, aliased, 'relays.run_one()')], spared=(at(root, aliased, 'relays.run_for('),))


def test_fluent_chain(root):
    prepare(root)
    path = 'libs/demo/test/chains.cpp'
    write(root, path, CPP + '\n'
          'void chain(widget& object) {\n'
          '    object.first().second().third();\n'
          '}\n')
    expect_alone(lint(root), 'fluent chains', [at(root, path, 'object.first()')])


def test_returns_this(root):
    prepare(root)
    # An assignment operator may return *this after a body that calls functions, whose lines
    # hold parentheses as a signature does, however clang-format splits its signature: the rule
    # follows it from operator=( to the brace that opens its body. A function that is no
    # assignment operator may not, split or not, with a call in its body or none, nor after a
    # deleted or a one-line assignment operator; and a chain inside an assignment
    # operator's body is still the fluent chain rule's finding.
    path = 'libs/demo/test/builder.cpp'
    write(root, path, CPP + '\n'
          '#include <initializer_list>\n'
          '\n'
          'struct builder {\n'
          '    builder& add() { return *this; }\n'
          '\n'
          '    builder& operator=(const builder&) { return *this; }\n'
          '\n'
          '    builder& append_one() {\n'
          '        swap(*this);\n'
          '        return *this;  // after a one-line operator\n'
          '    }\n'
          '\n'
          '    builder& operator=(builder&& other) noexcept {\n'
          '        swap(other);\n'
          '        return *this;  // moved\n'
          '    }\n'
          '\n'
          '    builder& append() {\n'
          '        swap(*this);\n'
          '        return *this;  // appended\n'
          '    }\n'
          '\n'
          '    builder& operator=(\n'
          '        const std::initializer_list<int>& numbers_given_to_the_builder_one_by_one)'
          ' noexcept {\n'
          '        return *this;  // split, no call\n'
          '    }\n'
          '\n'
          '    builder& operator=(\n'
          '        const std::initializer_list<long>& numbers_given_to_the_builder_one_by_one)'
          ' noexcept {\n'
          '        swap(*this);\n'
          '        return *this;  // split, a call\n'
          '    }\n'
          '\n'
          '    builder& operator=(const std::initializer_list<double>& numbers) = delete;\n'
          '\n'
          '    builder& append_all(\n'
          '        const std::initializer_list<short>& numbers_given_to_the_builder_one_by_one)'
          ' noexcept {\n'
          '        swap(*this);\n'
          '        return *this;  // split, appended with a call\n'
          '    }\n'
          '\n'
          '    builder& append_none(\n'
          '        const std::initializer_list<char>& numbers_given_to_the_builder_one_by_one)'
          ' noexcept {\n'
          '        return *this;  // split, appended without a call\n'
          '    }\n'
          '\n'
          '    builder& operator=(const std::initializer_list<bool>& flags) {\n'
          '        if (flags.size() != 0) {\n'
          '            shared().self().self().swap(*this);  // a chain\n'
          '        }\n'
          '        return *this;  // after a chain\n'
          '    }\n'
          '\n'
          '    builder& self() { return *this; }\n'
          '\n'
          '    static builder& shared();\n'
          '\n'
          '    void swap(builder& /*other*/) noexcept {}\n'
          '};\n')
    expect_failed(lint(root), ['fluent chains', 'returns *this'],
                  [at(root, path, 'add()'), at(root, path, '// after a one-line operator'),
                   at(root, path, '// appended'), at(root, path, '// split, appended with a call'),
                   at(root, path, '// split, appended without a call'),
                   at(root, path, 'self() {'), at(root, path, '// a chain')],
                  spared=(at(root, path, 'operator=(const builder'), at(root, path, '// moved'),
                          at(root, path, '// split, no call'), at(root, path, '// split, a call'),
                          at(root, path, '// after a chain')))


def test_returns_this_spares_what_the_standard_specifies(root):
    prepare(root)
    # A prefix increment or decrement returns *this, as the iterator requirements make it, after a
    # body that calls functions; so does a function whose head follows a line
    # `// lint-std: <reason>`, the reason naming the standard's member it reproduces, which a Doc
    # Comment above the line still documents. A postfix increment that returns *this, a function
    # after a `// lint-std:` that gives no reason, and the function after a spared one are flagged.
    path = 'libs/demo/test/stepper.cpp'
    write(root, path, CPP + '\n'
          'struct stepper {\n'
          '    stepper& operator++() {\n'
          '        advance();\n'
          '        return *this;  // prefix increment\n'
          '    }\n'
          '\n'
          '    stepper& operator--() noexcept {\n'
          '        retreat();\n'
          '        return *this;  // prefix decrement\n'
          '    }\n'
          '\n'
          '    stepper operator++(int) {\n'
          '        advance();\n'
          '        return *this;  // postfix\n'
          '    }\n'
          '\n'
          '    /** Assigns `count`, as std::basic_regex::assign does. */\n'
          '    // lint-std: std::basic_regex::assign returns *this\n'
          '    stepper& assign(int count) {\n'
          '        position = count;\n'
          '        advance();\n'
          '        return *this;  // marked, with a reason\n'
          '    }\n'
          '\n'
          '    stepper& after_marked() {\n'
          '        advance();\n'
          '        return *this;  // after a marked function\n'
          '    }\n'
          '\n'
          '    // lint-std:\n'
          '    stepper& unexplained() {\n'
          '        advance();\n'
          '        return *this;  // marked without a reason\n'
          '    }\n'
          '\n'
          '    void advance() noexcept { ++position; }\n'
          '\n'
          '    void retreat() noexcept { --position; }\n'
          '\n'
          '    int position = 0;\n'
          '};\n')
    expect_alone(lint(root), 'returns *this',
                 [at(root, path, '// postfix'), at(root, path, '// after a marked function'),
                  at(root, path, '// marked without a reason')],
                 spared=(at(root, path, '// prefix increment'),
                         at(root, path, '// prefix decrement'),
                         at(root, path, '// marked, with a reason')))


def test_em_dash(root):
    prepare(root)
    write(root, 'libs/demo/README.md', f'# demo\n\nThe fixture {EM_DASH} a library.\n')
    harness.replace(root / 'libs/demo/include/webcpp/demo/answer.hpp', 'namespace webcpp::demo {\n',
                    f'// The answer {EM_DASH} always 42.\nnamespace webcpp::demo {{\n')
    expect_alone(lint(root), 'em dash', [
        'libs/demo/README.md:3:',
        at(root, 'libs/demo/include/webcpp/demo/answer.hpp', 'The answer'),
    ])


def test_json_literals(root):
    prepare(root)
    path = 'libs/demo/test/literals.cpp'
    write(root, path, CPP + '\n'
          'const char* const shallow = R"({\n'
          '  "a": 1\n'
          '})";\n'
          '\n'
          'const char* const misclosed = R"({\n'
          '    "a": 1\n'
          '  })";\n'
          '\n'
          'const char* const laid_out = R"({\n'
          '    "a": 1\n'
          '})";\n')
    expect_alone(lint(root), 'JSON literals', [
        at(root, path, 'shallow') + ' the members are not four spaces deeper',
        at(root, path, 'misclosed') + ' the literal does not close',
    ], spared=(at(root, path, 'laid_out'),))


def test_licence_notice(root):
    prepare(root)
    old = 'libs/demo/include/webcpp/demo/answer.hpp'
    harness.replace(root / old, CPP, commented(OLD_NOTICE, '//'))
    mit = 'tools/mit.py'
    write(root, mit, commented(MIT_NOTICE, '#') + '\n"""Planted."""\n')
    bare = 'libs/demo/test/Jamfile'
    harness.replace(root / bare, HASH + '\n', '')
    # A JavaScript file, a page and an AsciiDoc file take the notice too.
    unnoticed = {'tools/unnoticed.js': 'export const unnoticed = true;\n',
                  'tools/unnoticed.html': '<!doctype html>\n<title>Unnoticed</title>\n',
                  'tools/unnoticed.adoc': '= Unnoticed\n'}
    for path, text in unnoticed.items():
        write(root, path, text)
    # The forms the notice takes: // in C++, JavaScript and AsciiDoc; # in Python, shell, Jam
    # and YAML, after a #! line where there is one; and in HTML, a comment that opens with it.
    accepted = {
        'tools/accepted.py': '#!/usr/bin/env python3\n' + HASH + '\n"""Accepted."""\n',
        'tools/accepted.sh': '#!/usr/bin/env bash\n' + HASH,
        'tools/accepted.jam': HASH,
        'tools/accepted.yml': HASH + 'name: accepted\n',
        'tools/accepted.yaml': HASH + 'name: accepted\n',
        'tools/accepted.mjs': CPP + '\nexport const accepted = true;\n',
        'tools/accepted.js': CPP + '\nexport const accepted = true;\n',
        'tools/accepted.adoc': CPP + '\n= Accepted\n',
        'tools/accepted.html': ('<!--\n' + NOTICE + '\nWhat the page is.\n-->\n'
                                '<title>Accepted</title>\n'),
        'tools/accepted/Jamfile': HASH,
        'tools/accepted/build.jam': HASH,
    }
    for path, text in accepted.items():
        write(root, path, text)
    expect_alone(lint(root), 'licence notice', [f'{old}:1:', f'{mit}:3:', f'{bare}:1:',
                                                *(f'{path}:1:' for path in unnoticed)],
                 spared=tuple(accepted))


def test_banned_word(root):
    prepare(root)
    write(root, 'notes.txt', f'Ported from {WORD.capitalize()}.\n')
    write(root, f'tools/{WORD}.txt', 'A name that must not be.\n')
    write(root, 'libs/demo/README.md', f'# demo\n\nNot {WORD.upper()}.\n')
    commit(root / 'libs/demo', f'A README that names {WORD}')
    commit(root, 'An author who must not be', name=f'{WORD} author')
    library = git(root / 'libs/demo', 'rev-parse', '--short', 'HEAD').strip()
    superproject = git(root, 'rev-parse', '--short', 'HEAD').strip()
    expect_alone(lint(root), 'banned word', [
        'notes.txt:1:', f'tools/{WORD}.txt', 'libs/demo/README.md:3:',
        f'libs/demo: commit {library}', f'.: commit {superproject}',
    ])


def test_world_rule(root):
    prepare(root)
    header = 'libs/demo/include/webcpp/demo/answer.hpp'
    harness.replace(root / header, 'namespace webcpp::demo {\n',
                    '// Waits on std::chrono::steady_clock.\n'
                    '// namespace fs = std::filesystem;\n'
                    '// Reads a filesystem::path.\n'
                    '// Includes boost/asio/post.hpp. lint-world: it only posts handlers.\n'
                    '// Calls getentropy(buffer, size).\n'
                    '// Calls getrandom(buffer, size, 0).\n'
                    '// Calls arc4random_buf(buffer, size).\n'
                    '// Calls RAND_bytes(buffer, size).\n'
                    '// Includes <sys/random.h>.\n'
                    '// Names getentropy. lint-world: it is the library\'s purpose.\n'
                    'namespace webcpp::demo {\n')
    # A test may name the world: the rule is about the libraries' headers.
    harness.replace(root / 'libs/demo/test/pass.cpp', '#include <cstdio>\n',
                    '#include <cstdio>\n\n// Never reads std::chrono::steady_clock.\n')
    expect_alone(lint(root), 'no clock, disk or network', [
        at(root, header, 'steady_clock'),
        at(root, header, 'std::filesystem'),
        at(root, header, 'filesystem::path'),
        at(root, header, 'getentropy('),
        at(root, header, 'getrandom('),
        at(root, header, 'arc4random_buf('),
        at(root, header, 'RAND_bytes('),
        at(root, header, '<sys/random.h>'),
    ], spared=(at(root, header, 'lint-world: it only'), at(root, header, 'Names getentropy'),
               'libs/demo/test/pass.cpp'))


def test_bare_throw(root):
    prepare(root)
    # A library header raises through boost::throw_exception alone. A throw in a template that
    # nothing instantiates, which no build compiles, fails, and so does a rethrow inside the
    # region a build with exceptions compiles; what only reads as a throw does not: the
    # function, a string, a comment, a Doc Comment, a raw string, noexcept(false), and a name
    # that holds the word. A test or an example may throw: catches.cpp does.
    header = 'libs/demo/include/webcpp/demo/raising.hpp'
    write(root, header, CPP + '\n'
          '#ifndef WEBCPP_DEMO_RAISING_HPP\n'
          '#define WEBCPP_DEMO_RAISING_HPP\n'
          '\n'
          '#include <boost/config.hpp>\n'
          '#include <boost/throw_exception.hpp>\n'
          '\n'
          '#include <exception>\n'
          '#include <stdexcept>\n'
          '\n'
          '#if defined(BOOST_NO_EXCEPTIONS) && !defined(WEBCPP_DEMO_NO_EXCEPTIONS)\n'
          '#define WEBCPP_DEMO_NO_EXCEPTIONS\n'
          '#endif\n'
          '\n'
          'namespace webcpp::demo {\n'
          '\n'
          '/** Returns the count it is given, refusing a negative one.\n'
          '\n'
          '    @tparam Count A signed type.\n'
          '    @param count The count.\n'
          '    @return count.\n'
          '*/\n'
          'template <typename Count>\n'
          'Count planted_uninstantiated(Count count) {\n'
          '    if (count < 0) {\n'
          '        throw std::invalid_argument("a negative count");\n'
          '    }\n'
          '    return count;\n'
          '}\n'
          '\n'
          '#ifndef WEBCPP_DEMO_NO_EXCEPTIONS\n'
          '\n'
          '/** Runs the work it is given, and lets what it throws go on.\n'
          '\n'
          '    @tparam Work A callable.\n'
          '    @param work The work.\n'
          '*/\n'
          'template <typename Work>\n'
          'void planted_rethrow(Work work) {\n'
          '    try {\n'
          '        work();\n'
          '    } catch (...) {\n'
          '        throw;\n'
          '    }\n'
          '}\n'
          '\n'
          '#endif\n'
          '\n'
          '// A comment may say throw, and a Doc Comment may say that a function throws.\n'
          '\n'
          '/** Returns the level it is given; throws, the one way, on a negative one.\n'
          '\n'
          '    @param level The level.\n'
          '    @return level.\n'
          '*/\n'
          'inline int planted_raises(int level) noexcept(false) {\n'
          '    if (level < 0) {\n'
          '        boost::throw_exception(std::domain_error("throw"));\n'
          '    }\n'
          '    return level;\n'
          '}\n'
          '\n'
          '/** Returns the text of a throw, which is no throw.\n'
          '\n'
          '    @return The text.\n'
          '*/\n'
          'inline const char* planted_text() noexcept {\n'
          '    return R"(throw x;)";\n'
          '}\n'
          '\n'
          '/** Rethrows the exception it is given, the one way to.\n'
          '\n'
          '    @param thrown The exception.\n'
          '*/\n'
          '[[noreturn]] inline void planted_rethrow_exception(const std::exception_ptr& thrown) {\n'
          '    std::rethrow_exception(thrown);\n'
          '}\n'
          '\n'
          '}  // namespace webcpp::demo\n'
          '\n'
          '#endif\n')
    expect_alone(lint(root), 'bare throw', [
        at(root, header, 'throw std::invalid_argument') + ' a bare throw',
        at(root, header, 'throw;') + ' a bare throw;',
    ], spared=(at(root, header, 'say throw'), at(root, header, 'throws, the one way'),
               at(root, header, 'boost::throw_exception('), at(root, header, 'R"(throw'),
               at(root, header, 'noexcept(false)'), at(root, header, 'std::rethrow_exception('),
               'libs/demo/example/catches.cpp:'))


def test_raw_rules(root):
    prepare(root)
    test = 'libs/demo/test/Jamfile'
    library = '<library>/webcpp/demo//demo'
    append(root, test,
           '\n'
           'import testing ;\n'
           '\n'
           '# run, compile and exe are b2\'s own rules, which a comment may name.\n'
           f'run pass.cpp : : : {library} : raw_run ;\n'
           f'run-fail fails.cpp : : : {library} : raw_run_fail ;\n'
           f'compile pass.cpp : {library} : raw_compile ;\n'
           f'compile-fail rejects.cpp : {library} : raw_compile_fail ;\n'
           f'unit-test raw_unit_test : pass.cpp : {library} ;\n'
           f'alias raw_suite : [ run pass.cpp : : : {library} : raw_bracket ] ;\n'
           f'testing.run pass.cpp : : : {library} : raw_qualified ;\n'
           f'link pass.cpp : {library} : raw_link ;\n'
           f'link-fail fails.cpp : {library} : raw_link_fail ;\n')
    example = 'libs/demo/example/Jamfile'
    append(root, example, f'exe raw_exe : hello.cpp : {library} ;\n')
    # What Jam reads as something else than an invocation of run: a block comment, assignments,
    # a rule's definition, the shell text of actions and a case's pattern. A quoted "run" is an
    # invocation, and so is the statement a case begins. b2 never loads this Jamfile, whose
    # directory no target names.
    parsing = 'libs/demo/test/parsing/Jamfile'
    write(root, parsing, HASH + '\n'
          '#| A block comment, which b2 skips whole:\n'
          '   run in_block_comment.cpp ;\n'
          '|#\n'
          'run = assigned ;\n'
          'run += appended ;\n'
          'rule run ( sources * ) { ECHO $(sources) ; }\n'
          'actions shell\n'
          '{\n'
          '    run in_actions\n'
          '}\n'
          'switch $(variant)\n'
          '{\n'
          '    case run : ECHO pattern ;\n'
          '    case * : compile-fail after_case.cpp ;\n'
          '}\n'
          '"run" quoted.cpp ;\n')
    expect_alone(lint(root), 'raw b2 rules', [
        at(root, test, 'raw_run ;'),
        at(root, test, 'raw_run_fail'),
        at(root, test, 'raw_compile ;'),
        at(root, test, 'raw_compile_fail'),
        f"{at(root, test, 'raw_unit_test')} unit-test is b2's own rule; a test or example "
        'Jamfile declares its programs with the rules of tools/webcpp.jam, here '
        'webcpp.boost-test\n',
        at(root, test, 'raw_bracket'),
        at(root, test, 'raw_qualified'),
        f"{at(root, test, 'raw_link ;')} link is b2's own rule; a test or example Jamfile "
        'declares its programs with the rules of tools/webcpp.jam, here webcpp.link\n',
        f"{at(root, test, 'raw_link_fail')} link-fail is b2's own rule; a test or example "
        'Jamfile declares its programs with the rules of tools/webcpp.jam, here webcpp.link\n',
        f"{at(root, example, 'raw_exe')} exe is b2's own rule; a test or example Jamfile "
        'declares its programs with the rules of tools/webcpp.jam, here webcpp.example, '
        'webcpp.run or webcpp.serve\n',
        at(root, parsing, 'after_case.cpp'),
        at(root, parsing, 'quoted.cpp'),
    ], spared=(at(root, test, 'a comment may name'), at(root, test, 'webcpp.compile '),
               at(root, test, 'webcpp.run pass'), at(root, parsing, 'in_block_comment'),
               at(root, parsing, 'assigned'), at(root, parsing, 'appended'),
               at(root, parsing, 'rule run'), at(root, parsing, 'in_actions'),
               at(root, parsing, 'case run')))


def boundaries_config(root, boundaries: list[dict]) -> str:
    """Writes libs/demo/meta/include-boundaries.json with boundaries, and returns its path."""
    path = 'libs/demo/meta/include-boundaries.json'
    write(root, path, json.dumps({'boundaries': boundaries}, indent=4) + '\n')
    return path


def planted_header(root, relative: str, comment: str, include: str) -> str:
    """Writes a header at libs/demo/<relative>, under test/ or example/ so that no Jamfile
    builds it and planting an include in it never touches clang-tidy or b2; returns its path."""
    path = f'libs/demo/{relative}'
    write(root, path, CPP + f'\n// {comment}\n{include}\n')
    return path


def test_include_boundaries_angle_brackets(root):
    prepare(root)
    boundaries_config(root, [{
        'headers': ['test/boundaries/core.hpp'],
        'must-not-include': ['webcpp/forbidden'],
        'why': 'the core must not reach the forbidden module',
    }])
    header = planted_header(root, 'test/boundaries/core.hpp',
                            'Planted by lint_test.py: a forbidden include.',
                            '#include <webcpp/forbidden/thing.hpp>')
    expect_alone(lint(root), 'include boundaries', [
        f"{at(root, header, '#include <webcpp/forbidden')} the core must not reach the "
        'forbidden module',
    ])


def test_include_boundaries_quotes(root):
    prepare(root)
    boundaries_config(root, [{
        'headers': ['test/boundaries/quoted.hpp'],
        'must-not-include': ['webcpp/forbidden'],
        'why': 'quotes name a path exactly as angle brackets do',
    }])
    header = planted_header(root, 'test/boundaries/quoted.hpp',
                            'Planted by lint_test.py: the same forbidden path, in quotes.',
                            '#include "webcpp/forbidden/thing.hpp"')
    needle = at(root, header, '#include "webcpp/forbidden')
    expect_alone(lint(root), 'include boundaries', [
        f'{needle} quotes name a path exactly as angle brackets do',
    ])


def test_include_boundaries_except(root):
    prepare(root)
    boundaries_config(root, [{
        'headers': ['test/boundaries/*.hpp'],
        'except': ['test/boundaries/excepted.hpp'],
        'must-not-include': ['webcpp/forbidden'],
        'why': 'the core must not reach the forbidden module',
    }])
    core = planted_header(root, 'test/boundaries/core.hpp',
                          'Planted by lint_test.py: a forbidden include.',
                          '#include <webcpp/forbidden/thing.hpp>')
    excepted = planted_header(root, 'test/boundaries/excepted.hpp',
                              'Planted by lint_test.py: excepted, so this include passes.',
                              '#include <webcpp/forbidden/thing.hpp>')
    expect_alone(lint(root), 'include boundaries', [
        f"{at(root, core, '#include <webcpp/forbidden')} the core must not reach the forbidden "
        'module',
    ], spared=(at(root, excepted, '#include <webcpp/forbidden'),))


def test_include_boundaries_except_does_not_reach_a_deeper_path(root):
    prepare(root)
    # pathlib's PurePath.match is right-anchored: it matches when pattern agrees with path's
    # trailing segments, whatever comes before them. So nested/test/boundaries/excepted.hpp's
    # last 3 segments equal the except pattern's 3, and PurePath.match wrongly exempts it;
    # glob_matches must not do that: a glob is anchored at both ends.
    boundaries_config(root, [{
        'headers': ['test/boundaries/*.hpp', 'nested/test/boundaries/*.hpp'],
        'except': ['test/boundaries/excepted.hpp'],
        'must-not-include': ['webcpp/forbidden'],
        'why': 'the core must not reach the forbidden module',
    }])
    excepted = planted_header(root, 'test/boundaries/excepted.hpp',
                              'Planted by lint_test.py: excepted, so this include passes.',
                              '#include <webcpp/forbidden/thing.hpp>')
    nested = planted_header(root, 'nested/test/boundaries/excepted.hpp',
                            'Planted by lint_test.py: a deeper file whose tail matches except; '
                            'it must not be exempted.',
                            '#include <webcpp/forbidden/thing.hpp>')
    expect_alone(lint(root), 'include boundaries', [
        f"{at(root, nested, '#include <webcpp/forbidden')} the core must not reach the "
        'forbidden module',
    ], spared=(at(root, excepted, '#include <webcpp/forbidden'),))


def test_include_boundaries_headers_glob_does_not_reach_a_deeper_path(root):
    prepare(root)
    # Likewise for headers: nested/test/boundaries/core.hpp's last 3 segments equal the headers
    # glob too, but it must not be read as covered by it, even though it holds a forbidden
    # include of its own.
    boundaries_config(root, [{
        'headers': ['test/boundaries/core.hpp'],
        'must-not-include': ['webcpp/forbidden'],
        'why': 'the core must not reach the forbidden module',
    }])
    planted_header(root, 'test/boundaries/core.hpp', 'Planted by lint_test.py: nothing forbidden'
                   ' here.', '// no include at all')
    planted_header(root, 'nested/test/boundaries/core.hpp',
                   'Planted by lint_test.py: a deeper file whose tail matches headers; it is '
                   'not covered.',
                   '#include <webcpp/forbidden/thing.hpp>')
    expect_clean(lint(root))


def test_include_boundaries_prefix_catches_bare_header(root):
    prepare(root)
    boundaries_config(root, [{
        'headers': ['test/boundaries/no_xactor.hpp'],
        'must-not-include': ['webcpp/xactor'],
        'why': 'webcpp/xactor is a prefix of webcpp/xactor.hpp, not only of webcpp/xactor/...',
    }])
    header = planted_header(root, 'test/boundaries/no_xactor.hpp',
                            'Planted by lint_test.py: the prefix also catches the bare header.',
                            '#include <webcpp/xactor.hpp>')
    expect_alone(lint(root), 'include boundaries', [
        f"{at(root, header, '#include <webcpp/xactor.hpp')} webcpp/xactor is a prefix of "
        'webcpp/xactor.hpp, not only of webcpp/xactor/...',
    ])


def test_include_boundaries_non_string_list_element(root):
    prepare(root)
    config = boundaries_config(root, [{
        'headers': ['test/boundaries/core.hpp'],
        'must-not-include': [123, 'webcpp/forbidden'],
        'why': 'reason',
    }])
    planted_header(root, 'test/boundaries/core.hpp',
                   'Planted by lint_test.py: never read, the boundary itself is malformed.',
                   '#include <webcpp/forbidden/thing.hpp>')
    expect_alone(lint(root), 'include boundaries', [
        f'{config}:1: "headers", "except" and "must-not-include" must be lists of strings, and '
        '"why" a non-empty string',
    ])


def test_include_boundaries_missing_key(root):
    prepare(root)
    config = boundaries_config(root, [{
        'headers': ['test/boundaries/core.hpp'],
        'must-not-include': ['webcpp/forbidden'],
    }])
    expect_alone(lint(root), 'include boundaries', [f"{config}:1: a boundary is missing 'why'"])


def test_include_boundaries_glob_matches_nothing(root):
    prepare(root)
    config = boundaries_config(root, [{
        'headers': ['test/boundaries/no_such_*.hpp'],
        'must-not-include': ['webcpp/forbidden'],
        'why': 'unreachable',
    }])
    expect_alone(lint(root), 'include boundaries', [
        f"{config}:1: the headers glob 'test/boundaries/no_such_*.hpp' matches no file of "
        'libs/demo/',
    ])


def test_include_boundaries_unknown_key(root):
    prepare(root)
    config = boundaries_config(root, [{
        'headers': ['test/boundaries/core.hpp'],
        'must-not-include': ['webcpp/forbidden'],
        'why': 'reason',
        'typo': True,
    }])
    expect_alone(lint(root), 'include boundaries', [
        f"{config}:1: a boundary names the key 'typo', which is none of ['except', 'headers', "
        "'must-not-include', 'why']",
    ])


def test_include_boundaries_malformed_json(root):
    prepare(root)
    config = 'libs/demo/meta/include-boundaries.json'
    write(root, config, '{ not json ]\n')
    expect_alone(lint(root), 'include boundaries', [f'{config}:1: not valid JSON'])


def test_doc_comments(root):
    prepare(root)
    header = 'libs/demo/include/webcpp/demo/answer.hpp'
    harness.replace(root / header, '    @return 42.\n',
                    '    @return 42.\n'
                    '    @sa webcpp::demo\n'
                    '    @deprecated Ask another fixture.\n'
                    '    Mail its author at someone@example.org.\n'
                    '    An @ alone.\n'
                    '    A literal \\@ is escaped, and @param[in] takes a direction.\n'
                    '    @code\n'
                    '    auto mail = "someone@example.org";\n'
                    '    @endcode\n'
                    '    @see answer\n')
    harness.replace(root / header, 'constexpr int answer()',
                    '/// @todo Answer something else.\n'
                    '// A plain comment may name someone@example.org.\n'
                    'constexpr int answer()')
    # Literals and plain comments are not Doc Comments, \n in them included. An unterminated
    # character literal (the apostrophe of an #error) and a string spliced across two lines
    # leave the lines of what follows them right.
    source = 'libs/demo/test/strings.cpp'
    write(root, source, CPP + '\n'
          '// A plain comment may end a line with \\n.\n'
          'const char* const text = "/** @todo in a string, not a Doc Comment */";\n'
          'const char* const newline = "one line\\n";\n'
          "const char newline_character = '\\n';\n"
          '\n'
          '#if 0\n'
          "#error This header can't be used here\n"
          '#endif\n'
          '\n'
          'const char* const spliced =\n'
          '    "one \\\n'
          'two";\n'
          '\n'
          '/** A declaration after the literals, whose \\sa is found on its own line.\n'
          '\n'
          '    @return nothing.\n'
          '*/\n'
          'int after_the_literals();\n')
    expect_alone(lint(root), 'Doc Comments', [
        at(root, header, '@sa') + ' @sa',
        at(root, header, '@deprecated') + ' @deprecated',
        at(root, header, 'Mail its author') + ' @example',
        at(root, header, 'An @ alone') + ' a bare @',
        at(root, header, '/// @todo') + ' @todo',
        at(root, source, 'whose \\sa') + ' \\sa',
    ], spared=(at(root, header, 'is escaped'), at(root, header, 'auto mail'),
               at(root, header, '@see'), at(root, header, 'plain comment'),
               at(root, source, 'plain comment'), at(root, source, '/** @todo'),
               at(root, source, 'one line'), at(root, source, 'newline_character'),
               at(root, source, '#error'), at(root, source, 'two";')))


def test_doc_comment_references(root):
    prepare(root)
    # A reference that a colon follows, in either form of the command. The punctuation MrDocs keeps
    # after a reference, a possessive among it, and code, which is verbatim, are spared.
    header = 'libs/demo/include/webcpp/demo/answer.hpp'
    harness.replace(root / header, '    @return 42.\n',
                    '    @return 42.\n'
                    '    @note Unlike @ref twice: it takes nothing.\n'
                    '    @note What \\ref twice: gives.\n'
                    "    @note What @ref twice's caller gets, and what \\ref twice\u2019s does.\n"
                    '    @note @ref twice, @ref twice. @ref twice; (@ref twice) and @ref twice!\n'
                    '    @code\n'
                    '    auto a = twice(1); // @ref twice: in code\n'
                    '    @endcode\n')
    expect_alone(lint(root), 'Doc Comments', [
        at(root, header, 'Unlike') + ' @ref twice: MrDocs drops the colon',
        at(root, header, 'What \\ref') + ' \\ref twice: MrDocs drops the colon',
    ], spared=(at(root, header, 'caller gets'), at(root, header, '@ref twice,'),
               at(root, header, 'auto a')))


def test_doc_comment_code_spans(root):
    prepare(root)
    # MrDocs reads __X__ inside a code span of a Doc Comment as bold, and the page shows X: each
    # such span fails at its line, in a /** */ comment and in a /// run. An escaped one, \__X__,
    # a single underscore pair, prose, verbatim code and a plain comment are spared.
    header = 'libs/demo/include/webcpp/demo/answer.hpp'
    harness.replace(root / header, '    @return 42.\n',
                    '    @return 42.\n'
                    '    @note Defined under `__wasip2__` alone.\n'
                    '    @note Read with `defined(__EMSCRIPTEN__) && x`.\n'
                    '    @note Escaped, `\\__wasip3__` stays whole.\n'
                    '    @note A `__prefix` or a `suffix__` alone, and `a_b_c`.\n'
                    '    @note In prose, __bold__ is not a code span.\n'
                    '    @code\n'
                    '    #ifdef __wasm__ // `__wasm__` in code\n'
                    '    @endcode\n')
    harness.replace(root / header, 'constexpr int answer()',
                    '/// Built for `__wasm__`.\n'
                    '// A plain comment names `__wasm__`.\n'
                    'constexpr int answer()')
    expect_alone(lint(root), 'Doc Comment code spans', [
        at(root, header, 'under `__wasip2__`') + ' `__wasip2__`',
        at(root, header, 'defined(__EMSCRIPTEN__)') + ' `defined(__EMSCRIPTEN__) && x`',
        at(root, header, '/// Built for') + ' `__wasm__`',
        'MrDocs reads __...__ in a code span as bold',
    ], spared=(at(root, header, 'Escaped'), at(root, header, '`__prefix`'),
               at(root, header, 'In prose'), at(root, header, '#ifdef __wasm__'),
               at(root, header, 'plain comment')))


CHANGELOG = (CPP + '\n[appendix]\n[#demo-changelog]\n== Changelog\n\nWhat changed.\n\n'
             '[#demo-changelog-unreleased]\n=== Unreleased\n\n// tag::unreleased[]\n'
             '* Added a line that\nwraps.\n{line}\n// end::unreleased[]\n')


def test_changelog(root):
    prepare(root)
    # A library's changelog keeps AGENTS.md chapter 11's form: a wrapped line is one line; one
    # that starts with no verb of the list fails, at its line.
    write(root, 'libs/demo/doc/changelog.adoc', CHANGELOG.format(line='* Fixed a crash.'))
    commit(root / 'libs/demo', 'A changelog')
    expect_clean(lint(root))
    text = CHANGELOG.format(line='* Made a mistake.')
    write(root, 'libs/demo/doc/changelog.adoc', text)
    number = text.split('\n').index('* Made a mistake.') + 1
    expect_alone(lint(root), 'changelog form',
                 [f'libs/demo/doc/changelog.adoc:{number}: a line starts with'])


def test_pyright(root):
    prepare(root)
    # A warning fails as an error does. lint_test.py itself proves the import paths: it imports
    # harness from tools/test, which only pyrightconfig.json's extraPaths make Pyright find.
    path = 'tools/planted.py'
    write(root, path, HASH + '\n"""Planted."""\n\nVALUE = 1\nVALUE + 1\n')
    # What is never used is an error: an import, a local variable and a private function.
    unused = 'tools/unused.py'
    write(root, unused, HASH + '\n'
          '"""Planted."""\n'
          '\n'
          'import shlex\n'
          '\n'
          '\n'
          'def _never_called():\n'
          '    """Is never called."""\n'
          '\n'
          '\n'
          'def assigns():\n'
          '    """Assigns a value it never reads."""\n'
          '    value = 1\n')
    expect_alone(lint(root), 'Pyright', [
        at(root, path, 'VALUE + 1')[:-1] + ':1 - warning',
        at(root, unused, 'import shlex')[:-1] + ':8 - error',
        at(root, unused, 'def _never_called')[:-1] + ':5 - error',
        at(root, unused, 'value = 1')[:-1] + ':5 - error',
    ])


def test_python_line_length(root):
    prepare(root)
    path = 'tools/long_lines.py'
    write(root, path, HASH + '\n"""Planted."""\n\n'
          + '# ' + 'x' * 98 + '\n'
          + '# ' + 'y' * 99 + '\n')
    expect_alone(lint(root), 'Python line length', [at(root, path, 'yyy')],
                 spared=(at(root, path, 'xxx'),))


def test_python_blank_lines(root):
    prepare(root)
    # Two blank lines come before a top-level def or class, its decorators and the comments just
    # above it; a def in a string, a nested one and the first statement of a file need none.
    path = 'tools/crowded.py'
    write(root, path, HASH + '\n"""Planted."""\n\n'
          'import functools\n\n\n'
          'def spaced():\n    """Is spaced."""\n\n'
          'def crowded():\n    """Is crowded."""\n\n\n'
          'TEXT = """\ndef in_a_string():\n"""\n'
          '# Commented.\n@functools.cache\ndef decorated():\n    """Is decorated."""\n\n'
          '    def nested():\n        """Is nested."""\n\n'
          '    return nested\n\n\n'
          'class Spaced:\n    """Is spaced."""\n')
    expect_alone(lint(root), 'Python blank lines',
                 [f'{at(root, path, "def crowded")} 1 blank line before a top-level def or class, '
                  'where 2 are', f'{at(root, path, "# Commented.")} 0 blank lines'],
                 spared=(at(root, path, 'def spaced'), at(root, path, 'def in_a_string'),
                         at(root, path, 'class Spaced'), at(root, path, 'def nested')))


def test_jam_comment_width(root):
    prepare(root)
    # A comment of a Jam file keeps to 80 columns, as Jam comments are wrapped; a line of code
    # does not.
    path = 'libs/demo/test/Jamfile'
    append(root, path, '# ' + 'x' * 78 + '\n'
                       + '# ' + 'y' * 79 + '\n'
                       + '    # ' + 'z' * 75 + '\n'
                       + 'alias long : ' + 'q' * 80 + ' ;\nexplicit long ;\n')
    expect_alone(lint(root), 'Jam comment width',
                 [f'{at(root, path, "yyy")} 81 columns, over the limit of 80 for a comment',
                  at(root, path, 'zzz')],
                 spared=(at(root, path, 'xxx'), at(root, path, 'qqq')))


def test_path_exists_takes_a_native_path(root):
    prepare(root)
    # path.exists, b2's builtin, asks the system about the path as it is written: b2's own form,
    # /D:/a/... on Windows, names no file there, so every call gives it [ path.native ... ]. b2
    # never loads this file, which no Jamfile imports.
    path = 'libs/demo/test/exists.jam'
    write(root, path, HASH + '\n'
          'if [ path.exists $(here)/b2_form ] { }\n'
          'if ! [ path.exists $(found[2])/also_b2_form ] { }\n'
          'if [ path.exists [ path.native $(here)/native ] ] { }\n'
          '# A comment may name [ path.exists $(x) ].\n')
    expect_alone(lint(root), 'path.exists native',
                 [f'{at(root, path, "/b2_form ]")} path.exists is given a path in b2\'s form',
                  at(root, path, 'also_b2_form')],
                 spared=(at(root, path, '/native ]'), at(root, path, 'may name')))


def test_shards_split_clang_tidy(root):
    prepare(root)
    total = TIDY_CLEAN.search(lint(root).stdout)
    assert total, 'no clang-tidy count'
    counted = 0
    for shard in ('1/2', '2/2'):
        result = lint(root, '--shard', shard)
        expect_clean(result)
        found = TIDY_SHARD.search(result.stdout)
        assert found and found.group(2) == total.group(1) and found.group(3) == shard, (
            result.stdout[-6000:])
        counted += int(found.group(1))
    assert counted == int(total.group(1)), (counted, total.group(0))
    for arguments, message in ((('--shard', '3/2'), '--shard 3/2: K is greater than N'),
                               (('--shard', 'one'), '--shard takes K/N'),
                               (('--fast',), 'unknown argument --fast')):
        result = lint(root, *arguments)
        assert result.returncode == 2 and message in result.stdout, (arguments,
                                                                    result.stdout[-6000:])


def test_a_library_webcpp_does_not_build_missing_is_named(root):
    # The lint's dry runs require the libraries webcpp does not build
    # (webcpp-require-external=on), as the CI's lanes do: one that is missing stops the compilation
    # database, naming the library that needs it and the one that was not found, rather than leave
    # the first out and fail later on a header no target compiles.
    prepare(root)
    write(root, 'libs/needs_ext/build.jam',
          'project /webcpp/needs_ext ;\n\nimport webcpp ;\n\n'
          'local fake-root = [ webcpp.external needs_ext : libfake : FAKE_ROOT : fake : fake.h\n'
          '    : native ] ;\n\n'
          'rule fake-found ( properties * )\n{\n'
          '    return [ webcpp.external-found needs_ext : libfake : $(properties) ] ;\n}\n\n'
          'alias needs_ext : : <conditional>@fake-found : : <include>include '
          '<include>$(fake-root)/include ;\n')
    write(root, 'libs/needs_ext/test/Jamfile',
          'project : requirements <library>/webcpp/needs_ext//needs_ext ;\n\n'
          'import webcpp ;\n\nwebcpp.headers-alone needs_ext : ../include ;\n')
    write(root, 'libs/needs_ext/include/webcpp/needs_ext.hpp',
          CPP + '\n#ifndef WEBCPP_NEEDS_EXT_HPP\n#define WEBCPP_NEEDS_EXT_HPP\n\n'
          '#include <fake.h>\n\n#endif\n')
    completed = compile_database(root)
    assert completed.returncode != 0, completed.stdout[-6000:]
    assert ('needs_ext needs libfake, which was not found, and the build requires it '
            '(webcpp-require-external=on)') in completed.stdout, completed.stdout[-6000:]


def test_third_party_code_is_never_read(root):
    # Third-party code keeps its own style, licence and notices: a file under third_party/libs/
    # that breaks the lint's rules, and the suite's own files, plain files here rather than a
    # submodule, leave the lint clean; what third_party/ holds outside libs/ is still read.
    prepare(root)
    harness.third_party_of_its_own(root, 'JSON-Schema-Test-Suite')
    planted = root / 'third_party/libs/planted'
    planted.mkdir(parents=True)
    (planted / 'planted.cpp').write_text('int  main( ) {throw 1;}\n')
    (planted / 'planted.py').write_text('x=1\n' + '#' * 120 + '\n')
    (planted / 'notes.txt').write_text(f'{EM_DASH} {WORD}\n')
    commit(root, 'Third-party code')
    expect_clean(lint(root))
    write(root, 'third_party/notes.txt', f'webcpp{EM_DASH}s own\n')
    commit(root, 'A file of webcpp under third_party')
    expect_alone(lint(root), 'em dash', ['third_party/notes.txt:1:'],
                 spared=('third_party/libs/',))


CASES = [
    test_clean_tree_passes,
    test_no_library_passes,
    test_a_user_config_the_environment_names_is_read,
    test_compile_database_lists_what_b2_builds,
    test_compile_database_reads_what_only_wasi_builds,
    test_an_aggregate_no_units_options_compile_names_each,
    test_wasi_sdk_is_told_by_the_compiler_itself,
    test_wasm_compiler_not_from_wasi_sdk_fails_by_name,
    test_a_failed_check_of_the_database_runs_the_other_rules,
    test_clang_format,
    test_clang_tidy_reads_what_b2_expects_to_build,
    test_clang_tidy_refuses_a_throw_a_build_without_exceptions_cannot_compile,
    test_clang_tidy_reads_what_only_a_build_without_exceptions_compiles,
    test_clang_tidy_reads_what_only_wasi_builds,
    test_clang_tidy_reads_what_an_own_lane_builds,
    test_compile_database_gives_each_target_its_aggregate,
    test_clang_tidy_reads_what_only_one_target_builds,
    test_a_dependency_s_warnings_are_not_ours,
    test_a_compiled_boost_library_s_sources_are_not_analysed,
    test_clang_tidy_refuses_a_throw_on_each_target_without_exceptions,
    test_a_native_header_that_needs_no_exceptions_has_its_twin,
    test_a_library_webcpp_does_not_build_missing_is_named,
    test_blocking_io_context_call,
    test_fluent_chain,
    test_returns_this,
    test_returns_this_spares_what_the_standard_specifies,
    test_em_dash,
    test_json_literals,
    test_licence_notice,
    test_banned_word,
    test_third_party_code_is_never_read,
    test_world_rule,
    test_bare_throw,
    test_raw_rules,
    test_include_boundaries_angle_brackets,
    test_include_boundaries_quotes,
    test_include_boundaries_except,
    test_include_boundaries_except_does_not_reach_a_deeper_path,
    test_include_boundaries_headers_glob_does_not_reach_a_deeper_path,
    test_include_boundaries_prefix_catches_bare_header,
    test_include_boundaries_glob_matches_nothing,
    test_include_boundaries_unknown_key,
    test_include_boundaries_missing_key,
    test_include_boundaries_non_string_list_element,
    test_include_boundaries_malformed_json,
    test_doc_comments,
    test_doc_comment_references,
    test_doc_comment_code_spans,
    test_changelog,
    test_pyright,
    test_python_line_length,
    test_python_blank_lines,
    test_jam_comment_width,
    test_path_exists_takes_a_native_path,
    test_shards_split_clang_tidy,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('lint_test', CASES, sys.argv[1:]))
