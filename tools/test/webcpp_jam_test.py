#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/webcpp.jam: a program is built only for the targets its Jamfile declares, natively
also without exceptions and RTTI; wasip2 builds without exceptions and wasip3 with them; an example
is compared with its expected output; every public header compiles alone; and `b2 declared-targets`
lists what each library declares. Each case builds a scratch superproject with the fixture library
demo. Run with the names of some cases to run only those."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys

import harness

WASIP2 = ('toolset=clang-wasip2', 'testing.launcher=wasmtime')
WASIP3 = ('toolset=clang-wasip3', 'testing.launcher=wasmtime')
EMSCRIPTEN = ('toolset=emscripten',)

PASSED = re.compile(r'^\*\*passed\*\* (.*)$', re.MULTILINE)


def passed(result):
    """The tests b2 reports as passed, by name: pass for .../pass.test/.../pass.test."""
    return {path.rsplit('/', 1)[-1].removesuffix('.test') for path in PASSED.findall(result.stdout)}


def output_of(root, name):
    """The text of the one file named name that b2 wrote under the scratch superproject's bin/."""
    found = sorted((root / 'bin').rglob(name))
    assert len(found) == 1, (name, found)
    return found[0].read_text()


def built_with(exceptions, rtti):
    """The first lines of pass's output: whether its compiler defined __cpp_exceptions and
    __cpp_rtti, which -fno-exceptions and -fno-rtti leave undefined."""
    return (f'__cpp_exceptions: {"defined" if exceptions else "undefined"}\n'
            f'__cpp_rtti: {"defined" if rtti else "undefined"}\n')


def stand_in_emscripten(root):
    """Configures the scratch superproject root with b2's toolset emscripten, whose emcc is a
    stand-in that runs clang++: enough to see what b2 builds for emscripten without Emscripten."""
    emcc = root / 'stand-in emcc/emcc'
    emcc.parent.mkdir()
    emcc.write_text('#!/bin/sh\nexec clang++ "$@"\n')
    emcc.chmod(0o755)
    config = root / '.local/user-config.jam'
    config.write_text(config.read_text() + f'using emscripten : : "{emcc}" ;\n')


NATIVE_DEMO = {'pass', 'pass-noexcept', 'fails', 'rejects', 'native_only', 'native_only-noexcept',
               'native_only_compiles', 'alone-demo', 'alone-demo-answer'}

WASM_DEMO = {'pass', 'fails', 'rejects', 'alone-demo', 'alone-demo-answer'}

PLAIN = ('import webcpp ;\n'
         '\n'
         'webcpp.run plain : plain.cpp ;\n')

PLAIN_SOURCE = 'int main() { return 0; }\n'


def test_native_builds_declared_and_noexcept_variant(root):
    result = harness.run_b2(root, 'libs/demo/test', 'libs/demo/example')
    harness.expect(result, True)
    assert passed(result) == NATIVE_DEMO, (passed(result), result.stdout[-4000:])
    # The variant -noexcept is built without exceptions and without RTTI, and links the handler
    # of tools/throw_exception.cpp, which its throw site needs.
    assert output_of(root, 'pass.output').startswith(built_with(exceptions=True, rtti=True))
    assert output_of(root, 'pass-noexcept.output').startswith(
        built_with(exceptions=False, rtti=False))
    assert output_of(root, 'hello.output') == 'The answer is 42.\n'
    assert output_of(root, 'catches.output') == 'caught: boom\n'


def test_wasip2_skips_native_only_and_has_no_exceptions(root):
    result = harness.run_b2(root, *WASIP2, 'libs/demo/test', 'libs/demo/example')
    harness.expect(result, True)
    # native_only, which does not compile for WASI, and the variants -noexcept, which are native,
    # are not built; nor is catches, an example that throws.
    assert passed(result) == WASM_DEMO, (passed(result), result.stdout[-4000:])
    assert 'native_only' not in result.stdout, result.stdout[-4000:]
    assert not list((root / 'bin').rglob('catches*')), result.stdout[-4000:]
    assert output_of(root, 'pass.output').startswith(built_with(exceptions=False, rtti=True))
    assert output_of(root, 'hello.output') == 'The answer is 42.\n'
    # The handler of tools/throw_exception.cpp prints what was thrown, and ends the program.
    harness.add_library(
        root, 'aborts',
        'import webcpp ;\n'
        '\n'
        'webcpp.run-fail aborts : aborts.cpp : : wasip2 ;\n',
        {'aborts.cpp': '#include <boost/throw_exception.hpp>\n'
                       '#include <stdexcept>\n'
                       'int main() { boost::throw_exception(std::runtime_error("planted")); }\n'})
    result = harness.run_b2(root, *WASIP2, 'libs/aborts/test')
    harness.expect(result, True)
    assert passed(result) == {'aborts'}, (passed(result), result.stdout[-4000:])
    assert 'throw_exception: planted' in output_of(root, 'aborts.output')
    # A program that throws does not compile for wasip2.
    harness.replace(root / 'libs/demo/example/Jamfile', ': : native wasip3 ;',
                    ': : native wasip2 wasip3 ;')
    harness.expect(harness.run_b2(root, *WASIP2, 'libs/demo/example'), False,
                   "cannot use 'throw' with exceptions disabled")


def test_wasip3_catches_a_throw(root):
    result = harness.run_b2(root, *WASIP3, 'libs/demo/test', 'libs/demo/example')
    harness.expect(result, True)
    assert passed(result) == WASM_DEMO, (passed(result), result.stdout[-4000:])
    assert output_of(root, 'pass.output').startswith(built_with(exceptions=True, rtti=True))
    assert output_of(root, 'catches.output') == 'caught: boom\n'
    # The Jamroot's -mllvm -wasm-use-legacy-eh=false is needed: without it, clang encodes the
    # throw with the legacy instructions, which wasmtime refuses to run.
    shutil.rmtree(root / 'bin')
    harness.replace(root / 'Jamroot', ' -mllvm -wasm-use-legacy-eh=false', '')
    result = harness.run_b2(root, *WASIP3, 'libs/demo/example')
    harness.expect(result, False, '-caught: boom')
    assert re.search(r'^\.\.\.failed .*catches\.output', result.stdout, re.MULTILINE), (
        result.stdout[-4000:])
    program = sorted((root / 'bin').rglob('catches.wasm'))
    assert len(program) == 1, program
    refused = subprocess.run(['wasmtime', program[0]], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, check=False)
    assert refused.returncode != 0, refused.stdout
    assert 'legacy_exceptions feature required' in refused.stdout, refused.stdout


def test_compile_builds_only_where_declared(root):
    # native_only_compiles compiles native_only.cpp, which stops with #error when built for WASI.
    # Declared native, it passes natively and is skipped on wasip2.
    target = 'libs/demo/test//native_only_compiles'
    result = harness.run_b2(root, target)
    harness.expect(result, True)
    assert passed(result) == {'native_only_compiles'}, (passed(result), result.stdout[-4000:])
    result = harness.run_b2(root, *WASIP2, target)
    harness.expect(result, True)
    assert not passed(result), result.stdout[-4000:]
    assert 'native_only' not in result.stdout, result.stdout[-4000:]
    # Declared for wasip2 too, it is compiled there, and a source that does not compile fails it.
    line = 'webcpp.compile native_only_compiles : native_only.cpp : <library>/webcpp/demo//demo'
    harness.replace(root / 'libs/demo/test/Jamfile', f'{line} : native ;',
                    f'{line} : native wasip2 ;')
    result = harness.run_b2(root, *WASIP2, target)
    harness.expect(result, False, 'native_only is declared for native only')
    assert re.search(r'^\.\.\.failed .*native_only_compiles', result.stdout, re.MULTILINE), (
        result.stdout[-4000:])


def test_filter_maps_each_toolset_to_its_target(root):
    # webcpp.filter called directly, with a toolset's properties and a program's targets: it
    # returns <build>no when the toolset builds for none of them. Only clang's version names a
    # target; a clang without one, and gcc whatever its version, build for native.
    table = [
        ('<toolset>clang <toolset-clang:version>wasip2', 'wasip2', 'built'),
        ('<toolset>clang <toolset-clang:version>wasip3', 'wasip3', 'built'),
        ('<toolset>clang <toolset-clang:version>wasip2', 'native wasip3', 'skipped'),
        ('<toolset>clang <toolset-clang:version>21', 'native', 'built'),
        ('<toolset>clang <toolset-clang:version>21', 'wasip2 wasip3', 'skipped'),
        ('<toolset>clang', 'native', 'built'),
        ('<toolset>clang', 'wasip2 wasip3', 'skipped'),
        ('<toolset>gcc <toolset-gcc:version>wasip2', 'native', 'built'),
        ('<toolset>gcc <toolset-gcc:version>wasip2', 'wasip2', 'skipped'),
        ('<toolset>emscripten', 'emscripten', 'built'),
        ('<toolset>emscripten', 'native', 'skipped'),
        ('<toolset>msvc', 'native', 'built'),
        ('<toolset>msvc', 'emscripten', 'skipped'),
    ]
    jamfile = 'import webcpp ;\n\n'
    for properties, targets, _ in table:
        program = ' '.join(f'<webcpp-targets>{target}' for target in targets.split())
        jamfile += f'ECHO "filter:" [ webcpp.filter {properties} {program} ] ;\n'
    harness.add_library(root, 'probe', jamfile, {})
    result = harness.run_b2(root, 'libs/probe/test')
    harness.expect(result, True)
    found = [line.removeprefix('filter:').strip() for line in result.stdout.splitlines()
             if line.startswith('filter:')]
    expected = ['<build>no' if outcome == 'skipped' else '' for _, _, outcome in table]
    assert found == expected, [(row, verdict)
                               for row, verdict, want in zip(table, found, expected)
                               if verdict != want]


def test_undeclared_jamfile_is_native_only(root):
    stand_in_emscripten(root)
    harness.add_library(root, 'plain', PLAIN, {'plain.cpp': PLAIN_SOURCE})
    for target in (WASIP2, WASIP3, EMSCRIPTEN):
        result = harness.run_b2(root, *target, 'libs/plain/test')
        harness.expect(result, True)
        assert not passed(result), (target, result.stdout[-4000:])
        assert not (root / 'bin/libs/plain').exists(), target
    result = harness.run_b2(root, 'libs/plain/test')
    harness.expect(result, True)
    assert passed(result) == {'plain', 'plain-noexcept'}, (passed(result), result.stdout[-4000:])


def test_emscripten_builds_only_what_declares_it(root):
    # The stand-in emcc compiles, so a compile-fail test passes exactly when b2 built it.
    stand_in_emscripten(root)
    harness.add_library(root, 'web',
                        'import webcpp ;\n'
                        '\n'
                        'webcpp.compile-fail web : rejects.cpp : : emscripten ;\n'
                        'webcpp.compile-fail here : rejects.cpp : : native ;\n',
                        {'rejects.cpp': 'static_assert(false);\n'})
    result = harness.run_b2(root, *EMSCRIPTEN, 'libs/web/test', 'libs/demo/test')
    harness.expect(result, True)
    assert passed(result) == {'web'}, (passed(result), result.stdout[-4000:])
    result = harness.run_b2(root, 'libs/web/test')
    harness.expect(result, True)
    assert passed(result) == {'here'}, (passed(result), result.stdout[-4000:])


def test_declared_targets_lists_pairs(root):
    result = harness.run_b2(root, '-d0', 'declared-targets')
    harness.expect(result, True)
    assert result.stdout == 'demo native\ndemo wasip2\ndemo wasip3\n', result.stdout
    # Sorted and unique across libraries; a program's own targets count.
    harness.add_library(root, 'plain', PLAIN + 'webcpp.run other : plain.cpp : : wasip3 ;\n',
                        {'plain.cpp': PLAIN_SOURCE})
    harness.add_library(root, 'alpha', PLAIN, {'plain.cpp': PLAIN_SOURCE})
    result = harness.run_b2(root, '-d0', 'declared-targets')
    harness.expect(result, True)
    assert result.stdout == ('alpha native\ndemo native\ndemo wasip2\ndemo wasip3\n'
                             'plain native\nplain wasip3\n'), result.stdout
    # It reads only Jamfiles: CI plans its lanes on a machine without Boost.
    harness.configure(root, harness.without_boost())
    result = harness.run_b2(root, '-d0', 'declared-targets', env_extra={'BOOST_ROOT': None})
    harness.expect(result, True)
    assert result.stdout == ('alpha native\ndemo native\ndemo wasip2\ndemo wasip3\n'
                             'plain native\nplain wasip3\n'), result.stdout


def test_a_wrong_declaration_is_refused(root):
    for declarations, message in (
        ('webcpp.targets native wasi ;\n',
         'webcpp.targets: wasi is not a target; the targets are native emscripten wasip2 wasip3'),
        ('webcpp.run pass : pass.cpp : : native wasm ;\n',
         "a program's targets: wasm is not a target"),
        ('webcpp.run pass : pass.cpp ;\nwebcpp.targets native ;\n',
         'webcpp.targets must come before the first program of its Jamfile'),
        ('webcpp.targets native ;\nwebcpp.targets wasip2 ;\n',
         'webcpp.targets is called twice in the same Jamfile'),
        # A wrong include root would otherwise check no header at all, and pass.
        ('webcpp.headers-alone demo : include ;\n',
         'webcpp.headers-alone: include holds neither webcpp/demo.hpp nor a header under'),
    ):
        (root / 'libs/demo/test/Jamfile').write_text('import webcpp ;\n\n' + declarations)
        result = harness.run_b2(root, 'libs/demo/test')
        harness.expect(result, False, message)
        # It names the line of the Jamfile.
        assert 'libs/demo/test/Jamfile:' in result.stdout, result.stdout[-4000:]


def test_example_mismatch_fails_naming_the_program(root):
    (root / 'libs/demo/example/hello.expected').write_text('The answer is 41.\n')
    result = harness.run_b2(root, 'libs/demo/example')
    harness.expect(result, False, '-The answer is 41.', '+The answer is 42.')
    assert re.search(r'^\.\.\.failed .*hello\.output', result.stdout, re.MULTILINE), (
        result.stdout[-4000:])
    assert not list((root / 'bin').rglob('hello.output')), result.stdout[-4000:]


def test_headers_alone_catches_a_missing_include(root):
    # broken.hpp uses std::string without <string>. demo.hpp includes <string> first, so every
    # program that includes demo.hpp compiles; only broken.hpp compiled alone does not.
    (root / 'libs/demo/include/webcpp/demo/broken.hpp').write_text(
        '#ifndef WEBCPP_DEMO_BROKEN_HPP\n'
        '#define WEBCPP_DEMO_BROKEN_HPP\n'
        'namespace webcpp::demo {\n'
        'inline std::string broken() { return "broken"; }\n'
        '}\n'
        '#endif\n')
    harness.replace(root / 'libs/demo/include/webcpp/demo.hpp',
                    '#include <webcpp/demo/answer.hpp>\n',
                    '#include <string>\n\n'
                    '#include <webcpp/demo/answer.hpp>\n'
                    '#include <webcpp/demo/broken.hpp>\n')
    result = harness.run_b2(root, 'libs/demo/test')
    harness.expect(result, False, 'broken.hpp')
    assert re.search(r'^\.\.\.failed .*alone-demo-broken', result.stdout, re.MULTILINE), (
        result.stdout[-4000:])
    assert passed(result) == NATIVE_DEMO, (passed(result), result.stdout[-4000:])


CASES = [
    test_native_builds_declared_and_noexcept_variant,
    test_wasip2_skips_native_only_and_has_no_exceptions,
    test_wasip3_catches_a_throw,
    test_compile_builds_only_where_declared,
    test_filter_maps_each_toolset_to_its_target,
    test_undeclared_jamfile_is_native_only,
    test_emscripten_builds_only_what_declares_it,
    test_declared_targets_lists_pairs,
    test_a_wrong_declaration_is_refused,
    test_example_mismatch_fails_naming_the_program,
    test_headers_alone_catches_a_missing_include,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('webcpp_jam_test', CASES, sys.argv[1:]))
