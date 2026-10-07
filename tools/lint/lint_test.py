#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/lint/lint.sh: a clean superproject passes, with the fixture library and without
any library; each rule, planted alone, fails alone and names the file and the line; and
tools/lint/compile_commands.py lists what b2 builds, without what b2 expects to fail, plus one
aggregate translation unit per library. Each case lints a scratch superproject whose libs/demo
is the fixture library demo, a repository of its own as a library's submodule is. Run with the
names of some cases to run only those."""

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
    """The node_modules of tools/lint, which npm ci installs once, here, for every case."""
    modules = harness.ROOT / 'tools/lint/node_modules'
    if not (modules / '.bin/pyright').exists():
        subprocess.run(['npm', 'ci', '--no-audit', '--no-fund'], cwd=modules.parent, check=True)
    return modules


def prepare(root: Path) -> None:
    """Makes the scratch superproject root and its libs/demo two repositories, as a checkout and
    its submodule are, and gives it the Pyright of this checkout."""
    for directory in (root / 'libs/demo', root):
        git(directory, 'init', '-q', '-b', 'main')
        commit(directory, 'The scratch copy')
    (root / 'tools/lint/node_modules').symlink_to(pyright_installed())


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
    output = result.stdout
    assert result.returncode == 1, (result.returncode, output[-6000:])
    assert FAILED.findall(output) == [rule], (rule, FAILED.findall(output), output[-6000:])
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
                                             'libs/demo/example/hello.cpp',
                                             'libs/demo/example/catches.cpp',
                                             'tools/throw_exception.cpp')}
    assert files == expected | {aggregate}, sorted(map(str, files))
    for entry in entries:
        assert entry['directory'] == str(root), entry
    # Each configuration once: pass.cpp as written and without exceptions; native_only.cpp too,
    # though the test native_only_compiles compiles it a third time, like the first.
    sources = [Path(entry['file']) for entry in entries]
    assert sources.count(root / 'libs/demo/test/pass.cpp') == 2, sources
    assert sources.count(root / 'libs/demo/test/native_only.cpp') == 2, sources
    # The aggregate includes every public header, and is compiled as headers-alone compiles one.
    assert aggregate.read_text().splitlines()[-2:] == ['#include <webcpp/demo.hpp>',
                                                       '#include <webcpp/demo/answer.hpp>'], (
        aggregate.read_text())
    command = next(entry['arguments'] for entry in entries if Path(entry['file']) == aggregate)
    assert '-Ilibs/demo/include' in command and command[-1] == str(aggregate), command
    # A library whose public headers headers-alone does not compile has no command to give its
    # aggregate, and is named.
    harness.replace(root / 'libs/demo/test/Jamfile', 'webcpp.headers-alone demo : ../include ;\n',
                    '')
    completed = subprocess.run([sys.executable, str(script), str(root), str(out)],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               check=False, timeout=harness.TIMEOUT)
    assert completed.returncode == 1, completed.stdout[-6000:]
    assert 'libs/demo' in completed.stdout and 'headers-alone' in completed.stdout, (
        completed.stdout[-6000:])


def test_clang_format(root):
    prepare(root)
    path = 'libs/demo/test/unformatted.cpp'
    write(root, path, CPP + '\nint  unformatted( ) {return 42;}\n')
    expect_alone(lint(root), 'clang-format', [at(root, path, 'unformatted(')])


def test_clang_tidy_reads_what_b2_expects_to_build(root):
    prepare(root)
    # An ordinary test beside rejects.cpp is analysed, and so is a run-fail test, which compiles,
    # and a public header that no test includes, through the library's aggregate translation
    # unit; a second source that does not compile on purpose is not.
    test = 'libs/demo/test/planted.cpp'
    write(root, test, CPP + '\n'
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
    append(root, 'libs/demo/test/Jamfile',
           'webcpp.run planted : planted.cpp ;\n'
           'webcpp.run-fail planted_fails : planted_fails.cpp ;\n'
           'webcpp.compile-fail also_rejects : also_rejects.cpp ;\n')
    expect_alone(lint(root), 'clang-tidy',
                 [at(root, test, 'int value;'), at(root, header, 'int value;'),
                  at(root, run_fail, 'int status;')],
                 spared=('also_rejects', 'rejects.cpp'))


def test_blocking_io_context_call(root):
    prepare(root)
    path = 'libs/demo/test/drives.cpp'
    write(root, path, CPP + '\n'
          'void drive() {\n'
          '    boost::asio::io_context context;\n'
          '    context.run();\n'
          '}\n')
    expect_alone(lint(root), 'io_context::run', [at(root, path, 'context.run()')])


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
    path = 'libs/demo/test/builder.cpp'
    write(root, path, CPP + '\n'
          'struct builder {\n'
          '    builder& add() { return *this; }\n'
          '\n'
          '    builder& operator=(const builder&) { return *this; }\n'
          '};\n')
    expect_alone(lint(root), 'returns *this', [at(root, path, 'add()')],
                 spared=(at(root, path, 'operator='),))


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
    # The forms the notice takes: // in C++ and JavaScript; # in Python, shell, Jam and YAML,
    # after a #! line where there is one.
    accepted = {
        'tools/accepted.py': '#!/usr/bin/env python3\n' + HASH + '\n"""Accepted."""\n',
        'tools/accepted.sh': '#!/usr/bin/env bash\n' + HASH,
        'tools/accepted.jam': HASH,
        'tools/accepted.yml': HASH + 'name: accepted\n',
        'tools/accepted.yaml': HASH + 'name: accepted\n',
        'tools/accepted.mjs': CPP + '\nexport const accepted = true;\n',
        'tools/accepted/Jamfile': HASH,
        'tools/accepted/build.jam': HASH,
    }
    for path, text in accepted.items():
        write(root, path, text)
    expect_alone(lint(root), 'licence notice', [f'{old}:1:', f'{mit}:3:', f'{bare}:1:'],
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
                    'namespace webcpp::demo {\n')
    # A test may name the world: the rule is about the libraries' headers.
    harness.replace(root / 'libs/demo/test/pass.cpp', '#include <cstdio>\n',
                    '#include <cstdio>\n\n// Never reads std::chrono::steady_clock.\n')
    expect_alone(lint(root), 'no clock, disk or network', [
        at(root, header, 'steady_clock'),
        at(root, header, 'std::filesystem'),
        at(root, header, 'filesystem::path'),
    ], spared=(at(root, header, 'lint-world:'), 'libs/demo/test/pass.cpp'))


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
           f'testing.run pass.cpp : : : {library} : raw_qualified ;\n')
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
        at(root, test, 'raw_unit_test'),
        at(root, test, 'raw_bracket'),
        at(root, test, 'raw_qualified'),
        at(root, example, 'raw_exe'),
        at(root, parsing, 'after_case.cpp'),
        at(root, parsing, 'quoted.cpp'),
    ], spared=(at(root, test, 'a comment may name'), at(root, test, 'webcpp.compile '),
               at(root, test, 'webcpp.run pass'), at(root, parsing, 'in_block_comment'),
               at(root, parsing, 'assigned'), at(root, parsing, 'appended'),
               at(root, parsing, 'rule run'), at(root, parsing, 'in_actions'),
               at(root, parsing, 'case run')))


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


CASES = [
    test_clean_tree_passes,
    test_no_library_passes,
    test_compile_database_lists_what_b2_builds,
    test_clang_format,
    test_clang_tidy_reads_what_b2_expects_to_build,
    test_blocking_io_context_call,
    test_fluent_chain,
    test_returns_this,
    test_em_dash,
    test_json_literals,
    test_licence_notice,
    test_banned_word,
    test_world_rule,
    test_raw_rules,
    test_doc_comments,
    test_pyright,
    test_python_line_length,
    test_shards_split_clang_tidy,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('lint_test', CASES, sys.argv[1:]))
