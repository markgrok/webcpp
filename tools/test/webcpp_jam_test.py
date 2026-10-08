#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/webcpp.jam: a program is built only for the targets its Jamfile declares, natively
also without exceptions and RTTI; wasip2 builds without exceptions and wasip3 with them; an example
is compared with its expected output; every public header compiles alone; `b2 declared-targets`
lists what each library declares; a Boost.Test suite is built and run natively only, its framework
always with exceptions; Boost.JSON's definitions link on every target; and every program sees
C++20, a native one without exceptions also seeing no RTTI through Boost.Config. Each case builds
a scratch superproject with the fixture library demo. Run with the names of some cases to run only
those."""

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
               'native_only_compiles', 'alone-demo', 'alone-demo-answer', 'suite', 'suite-noexcept',
               'parses_json', 'parses_json-noexcept'}

WASM_DEMO = {'pass', 'fails', 'rejects', 'alone-demo', 'alone-demo-answer', 'parses_json'}

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


def compile_lines(root, *request):
    """The lines of b2's dry run of request, from scratch, that compile a .cpp file, by the file's
    name: suite_test.cpp for .../libs/demo/test/suite_test.cpp."""
    result = harness.run_b2(root, '-n', '-a', *request)
    harness.expect(result, True)
    lines = {}
    for line in result.stdout.splitlines():
        found = re.search(r'([^/"]+\.cpp)"\s*$', line)
        if ' -c ' in line and found:
            lines.setdefault(found.group(1), []).append(line)
    return lines


def test_boost_test_passes_natively_with_noexcept(root):
    result = harness.run_b2(root, 'libs/demo/test//suite', 'libs/demo/test//suite-noexcept')
    harness.expect(result, True)
    assert passed(result) == {'suite', 'suite-noexcept'}, (passed(result), result.stdout[-4000:])
    # The suite's own sources are built as a webcpp.run's are: the variant -noexcept without
    # exceptions and without RTTI.
    assert built_with(exceptions=True, rtti=True) in output_of(root, 'suite.output')
    assert built_with(exceptions=False, rtti=False) in output_of(root, 'suite-noexcept.output')
    # The framework is an object of its own, which names the module and is compiled with
    # exceptions in both variants: without them, a failed BOOST_TEST_REQUIRE never ends the run,
    # and GCC rejects Boost.Test's unguarded try. The variant -noexcept compiles it without RTTI.
    lines = compile_lines(root, 'libs/demo/test//suite', 'libs/demo/test//suite-noexcept')
    framework = lines['boost_test_runner.cpp']
    assert len(framework) == 2, framework
    for line in framework:
        assert '-DBOOST_TEST_MODULE=suite' in line, line
        assert '-fno-exceptions' not in line and 'BOOST_NO_EXCEPTIONS' not in line, line
    assert sum('-fno-rtti' in line for line in framework) == 1, framework
    sources = lines['suite_test.cpp']
    assert len(sources) == 2, sources
    assert sum('-fno-exceptions' in line and '-fno-rtti' in line
               and '-DBOOST_NO_EXCEPTIONS' in line for line in sources) == 1, sources
    assert not any('BOOST_TEST_MODULE' in line for line in sources), sources


RED = ('import webcpp ;\n'
       '\n'
       'webcpp.boost-test red-checks : checks_test.cpp ;\n'
       'webcpp.boost-test red-requires : requires_test.cpp ;\n')

RED_SOURCES = {
    'checks_test.cpp': ('#include <boost/test/unit_test.hpp>\n'
                        '\n'
                        'BOOST_AUTO_TEST_CASE(checks_and_goes_on) {\n'
                        '    BOOST_TEST(1 + 1 == 3);\n'
                        '    BOOST_TEST(1 + 1 == 4);\n'
                        '}\n'),
    'requires_test.cpp': ('#include <boost/test/unit_test.hpp>\n'
                          '\n'
                          'BOOST_AUTO_TEST_CASE(requires_and_stops) {\n'
                          '    BOOST_TEST_REQUIRE(2 + 2 == 5);\n'
                          '    BOOST_TEST(2 + 2 == 6);\n'
                          '}\n'),
}


# Each red suite: its case, the checks its output names, and a check after a failed requirement,
# which must not run.
RED_EXPECTED = {
    'red-checks': ('checks_and_goes_on', ('1 + 1 == 3', '1 + 1 == 4'), None),
    'red-requires': ('requires_and_stops', ('2 + 2 == 5',), '2 + 2 == 6'),
}


def test_boost_test_failure_is_red_and_named(root):
    # A failed check, after which its case goes on, and a failed requirement, which ends its
    # case: each ends the run red in both variants, never a hang and never a pass, and each
    # variant's own output names the case, every failed check and the module, whose name has - as
    # _. Boost.Test writes a terminal's colours even to a file, unless told not to.
    harness.add_library(root, 'red', RED, RED_SOURCES)
    result = harness.run_b2(root, 'libs/red/test')
    harness.expect(result, False)
    assert not passed(result), result.stdout[-4000:]
    for suite, (case, checks, unreached) in RED_EXPECTED.items():
        module = suite.replace('-', '_')
        for name in (suite, f'{suite}-noexcept'):
            assert re.search(rf'^\.\.\.failed .*/{name}\.test/.*/{name}\.run\.\.\.$',
                             result.stdout, re.MULTILINE), (name, result.stdout[-6000:])
            output = output_of(root, f'{name}.output')
            lines = output.splitlines()
            for check in checks:
                assert any(f'in "{case}": ' in line and f'check {check} has failed' in line
                           for line in lines), (name, check, output)
            assert f'detected in the test module "{module}"' in output, (name, output)
            assert unreached is None or unreached not in output, (name, output)
            assert re.search(r'^EXIT STATUS: [1-9]', output, re.MULTILINE), (name, output)
            assert '\x1b' not in output, (name, output)


SUITES = ('import webcpp ;\n'
          '\n'
          'webcpp.targets native wasip2 wasip3 ;\n'
          '\n'
          'webcpp.boost-test suite : suite_test.cpp ;\n')

SUITE_SOURCE = ('#ifdef __wasi__\n'
                '#error "a Boost.Test suite is built for native only"\n'
                '#endif\n'
                '\n'
                '#include <boost/test/unit_test.hpp>\n'
                '\n'
                'BOOST_AUTO_TEST_CASE(passes) {\n'
                '    BOOST_TEST(1 + 1 == 2);\n'
                '}\n')


def test_boost_test_never_built_for_wasm(root):
    # Its Jamfile declares wasm targets, and the suite is still built for native only: the source
    # stops with #error for WASI, so a suite the filter should have skipped fails loudly.
    harness.add_library(root, 'suites', SUITES, {'suite_test.cpp': SUITE_SOURCE})
    for target in (WASIP2, WASIP3):
        result = harness.run_b2(root, *target, 'libs/suites/test', 'libs/demo/test//suite')
        harness.expect(result, True)
        assert not passed(result), (target, result.stdout[-4000:])
        assert not (root / 'bin/libs/suites').exists(), target
        assert 'boost_test_runner' not in result.stdout, (target, result.stdout[-4000:])
    result = harness.run_b2(root, 'libs/suites/test')
    harness.expect(result, True)
    assert passed(result) == {'suite', 'suite-noexcept'}, (passed(result), result.stdout[-4000:])
    # It is recorded for native alone, whatever its Jamfile declares.
    result = harness.run_b2(root, '-d0', 'declared-targets')
    harness.expect(result, True)
    lines = [line for line in result.stdout.splitlines() if line.startswith('suites ')]
    assert lines == ['suites native'], result.stdout


def boost_json_archives(root):
    """The archives of /webcpp//boost_json that b2 wrote under the scratch superproject's bin/,
    one per variant built: libboost_json.a, or boost_json.lib with MSVC."""
    return sorted(path for path in (root / 'bin').rglob('*boost_json.*')
                  if path.suffix in ('.a', '.lib'))


def test_boost_json_on_every_target(root):
    programs = ('libs/demo/test//parses_json', 'libs/demo/test//parses_json-noexcept')
    result = harness.run_b2(root, *programs)
    harness.expect(result, True)
    assert passed(result) == {'parses_json', 'parses_json-noexcept'}, (passed(result),
                                                                       result.stdout[-4000:])
    # The definitions are a library of their own, compiled once per variant: natively two, and
    # one for each wasm target, in its toolset's directory (clang-darwin-wasip2 on macOS).
    assert len(boost_json_archives(root)) == 2, (boost_json_archives(root), result.stdout[-4000:])
    for count, (wasm, target) in enumerate((('wasip2', WASIP2), ('wasip3', WASIP3)), start=3):
        result = harness.run_b2(root, *target, programs[0])
        harness.expect(result, True)
        assert passed(result) == {'parses_json'}, (target, passed(result), result.stdout[-4000:])
        archives = boost_json_archives(root)
        assert len(archives) == count, (target, archives)
        assert len([path for path in archives
                    if any(part.endswith(f'-{wasm}') for part in path.parts)]) == 1, archives
    # Without the library, a program that parses JSON does not link.
    harness.replace(root / 'libs/demo/test/Jamfile', ' <library>/webcpp//boost_json', '')
    result = harness.run_b2(root, '-a', programs[0])
    harness.expect(result, False)
    assert re.search(r'^\.\.\.failed .*parses_json', result.stdout, re.MULTILINE), (
        result.stdout[-4000:])


TOOLCHAIN_JAMFILE = ('import webcpp ;\n'
                     '\n'
                     'webcpp.targets native wasip2 wasip3 ;\n'
                     '\n'
                     'webcpp.run toolchain : toolchain.cpp ;\n')

TOOLCHAIN_SOURCE = (
    '#include <boost/config.hpp>\n'
    '\n'
    '#include <cstdio>\n'
    '\n'
    '#if defined(_MSVC_LANG)\n'
    'static_assert(_MSVC_LANG >= 202002L, "the build does not compile as C++20");\n'
    '#else\n'
    'static_assert(__cplusplus >= 202002L, "the build does not compile as C++20");\n'
    '#endif\n'
    '\n'
    '// Native, without exceptions, is also without RTTI (tools/webcpp.jam\'s .noexcept pairs\n'
    '// <exception-handling>off with <rtti>off). wasip2 turns exceptions off at the project\n'
    '// level, through its own <exception-handling>off, without doing the same to RTTI, so the\n'
    '// check below excludes it.\n'
    '#if defined(BOOST_NO_EXCEPTIONS) && !defined(__wasi__) && !defined(BOOST_NO_RTTI)\n'
    '#error "a build without exceptions does not also disable RTTI"\n'
    '#endif\n'
    '\n'
    'int main() {\n'
    '#ifdef BOOST_NO_EXCEPTIONS\n'
    '    std::puts("no exceptions");\n'
    '#else\n'
    '    std::puts("exceptions");\n'
    '#endif\n'
    '    return 0;\n'
    '}\n')


def test_toolchain_sees_cxx20_and_ties_rtti_to_exceptions(root):
    # Restores the promise of xstate-cpp's retired toolchain_test.cpp: every program sees C++20,
    # and a build without exceptions also sees no RTTI, both through Boost.Config's own macros,
    # not the raw compiler ones built_with reads. wasip2 is declared too: -noexcept is native
    # only (tools/webcpp.jam), so the one program built there is the plain one, and it is the
    # no-exceptions one, since wasip2 turns exceptions off at the project level.
    harness.add_library(root, 'toolchain', TOOLCHAIN_JAMFILE, {'toolchain.cpp': TOOLCHAIN_SOURCE})
    result = harness.run_b2(root, 'libs/toolchain/test')
    harness.expect(result, True)
    assert passed(result) == {'toolchain', 'toolchain-noexcept'}, (passed(result),
                                                                    result.stdout[-4000:])
    assert output_of(root, 'toolchain.output').startswith('exceptions\n')
    assert output_of(root, 'toolchain-noexcept.output').startswith('no exceptions\n')
    shutil.rmtree(root / 'bin')
    result = harness.run_b2(root, *WASIP2, 'libs/toolchain/test')
    harness.expect(result, True)
    assert passed(result) == {'toolchain'}, (passed(result), result.stdout[-4000:])
    assert output_of(root, 'toolchain.output').startswith('no exceptions\n')


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
    test_boost_test_passes_natively_with_noexcept,
    test_boost_test_failure_is_red_and_named,
    test_boost_test_never_built_for_wasm,
    test_boost_json_on_every_target,
    test_toolchain_sees_cxx20_and_ties_rtti_to_exceptions,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('webcpp_jam_test', CASES, sys.argv[1:]))
