#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/component/component.jam: webcpp.wit-bindings generates a world's C bindings with
wit-bindgen for wasip2 and wasip3, where a translation unit that includes them compiles and a
component that uses them links; natively it adds nothing and asks for no tool, unless its -headers
target is named; a missing wit-bindgen, WIT or world file stops the build naming it and where it was
looked for; a dry run generates the header; the bindings are written again only when what they are
made from changes, or one of them is missing; a name declared twice in a library is refused; and an
argument holding a $ or a ' reaches wit-bindgen as it is written. webcpp.serve builds an HTTP
component, serves it with wasmtime and checks its answers, as a test of b2's that --dump-tests lists
and the report reads, in two lanes at once; a wrong transcript is a run failure in the report;
native and emscripten are refused, and a native lane builds no served test and asks for no tool; a
missing wasmtime fails the served test naming it, only when it runs, and a dry run needs none; no
wasmtime is left by a test that passes, one that fails, a b2 that is interrupted, or one that
kills the action that serves it (b2 -l). Each case
builds a scratch superproject with the fixture library component_demo, given this checkout's
wit-bindgen and WIT. Run with the names of some cases to run only those."""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import harness
from oracle_jam_test import without

LIBRARY = 'libs/component_demo'
TEST = f'{LIBRARY}/test'
WASIP2 = 'toolset=clang-wasip2'
WASIP3 = 'toolset=clang-wasip3'

# What `b2 declared-targets` says for the fixture.
DECLARED = 'component_demo native\ncomponent_demo wasip2\ncomponent_demo wasip3\n'

# The first eight bytes of a WebAssembly component, which a core module's version field differs
# from: the magic, then version 0x0d and layer 1.
COMPONENT = b'\0asm\x0d\x00\x01\x00'

PASSED = re.compile(r'^\*\*passed\*\* (.*)$', re.MULTILINE)

# The fixture's headers compiled alone: natively its own, and on wasip2 and wasip3 the header of
# the world's bindings too.
ALONE_NATIVE = {'alone-component_demo'}
ALONE_WASI = {'alone-component_demo', 'alone-component_demo-world'}


def passed(result):
    """The tests b2 reports as passed, by name."""
    return {path.rsplit('/', 1)[-1].removesuffix('.test') for path in PASSED.findall(result.stdout)}


def generated(root, version):
    """The directory of the fixture's bindings for version, p2 or p3."""
    return root / f'bin/generated/component_demo/demo-bindings-{version}'


def identity(path):
    """What changes when path is written again: its inode, which the rename of a new directory
    changes, and its modification time, to the nanosecond."""
    status = path.stat()
    return status.st_ino, status.st_mtime_ns


def test_bindings_generated_for_wasip2_and_wasip3(root):
    harness.link_wasi_tools(root)
    for toolset, version in ((WASIP2, 'p2'), (WASIP3, 'p3')):
        result = harness.run_b2(root, '-a', toolset, TEST)
        harness.expect(result, True)
        assert passed(result) == {'bindings', 'answers', *ALONE_WASI}, result.stdout[-4000:]
        directory = generated(root, version)
        for name in ('demo_world.h', 'demo_world.c', 'demo_world_component_type.o',
                     f'wit/world-{version}.wit', 'wit/deps/http.wit'):
            assert (directory / name).is_file(), (name, sorted(directory.rglob('*')))
        # The other version's are not generated.
        other = 'p3' if version == 'p2' else 'p2'
        assert not generated(root, other).exists(), version
        shutil.rmtree(root / 'bin')
    # wasip3's are generated with wit-bindgen's --async.
    inputs = generated(root, 'p3') / 'inputs'
    harness.expect(harness.run_b2(root, '-a', WASIP3, TEST), True)
    assert '"--async" "wasi:http/handler@0.3.0#handle"' in inputs.read_text(), inputs.read_text()


def test_bindings_link_into_a_component(root):
    harness.link_wasi_tools(root)
    # A reactor on each version, linked with the target of the bindings: without their C, the
    # world's export is missing, and without the world's type, the C's reference to it is.
    link = root / LIBRARY / 'link'
    link.mkdir()
    (link / 'Jamfile').write_text(
        'exe reactor_p2 : reactor_p2.cpp /webcpp/component_demo//demo-bindings\n'
        '  : <linkflags>-mexec-model=reactor <toolset>clang-wasip3:<build>no ;\n'
        'exe reactor_p3 : reactor_p3.cpp /webcpp/component_demo//demo-bindings\n'
        '  : <linkflags>-mexec-model=reactor <toolset>clang-wasip2:<build>no ;\n')
    (link / 'reactor_p2.cpp').write_text(
        '#include <demo_world.h>\n'
        '\n'
        'void exports_wasi_http_incoming_handler_handle(\n'
        '    exports_wasi_http_incoming_handler_own_incoming_request_t request,\n'
        '    exports_wasi_http_incoming_handler_own_response_outparam_t) {\n'
        '    wasi_http_types_incoming_request_drop_own(request);\n'
        '}\n')
    (link / 'reactor_p3.cpp').write_text(
        '#include <demo_world.h>\n'
        '\n'
        'demo_world_callback_code_t exports_wasi_http_handler_handle(\n'
        '    exports_wasi_http_handler_own_request_t request) {\n'
        '    wasi_http_types_request_drop_own(request);\n'
        '    return DEMO_WORLD_CALLBACK_CODE_EXIT;\n'
        '}\n'
        '\n'
        'demo_world_callback_code_t exports_wasi_http_handler_handle_callback(\n'
        '    demo_world_event_t*) {\n'
        '    return DEMO_WORLD_CALLBACK_CODE_EXIT;\n'
        '}\n')
    for toolset, version in ((WASIP2, 'p2'), (WASIP3, 'p3')):
        result = harness.run_b2(root, '-a', '-d+2', toolset, f'{LIBRARY}/link')
        harness.expect(result, True)
        components = sorted((root / 'bin').rglob(f'reactor_{version}.wasm'))
        assert len(components) == 1, (components, result.stdout[-4000:])
        assert components[0].read_bytes()[:8] == COMPONENT, components[0]
        # The bindings' C is compiled with its warnings off, and with -pthread on wasip3.
        compile_line = next(line for line in result.stdout.splitlines()
                            if ' -x c ' in line and 'demo_world.c' in line)
        assert ' -w ' in compile_line, compile_line
        assert (' -pthread ' in compile_line) == (version == 'p3'), compile_line


def test_native_build_needs_no_wit_bindgen(root):
    harness.link_wasi_tools(root)
    nowhere = ('-sWIT_BINDGEN=/nonexistent', '-sWASI_WIT_P2=/nonexistent',
               '-sWASI_WIT_P3=/nonexistent')
    result = harness.run_b2(root, '-a', *nowhere, TEST)
    harness.expect(result, True)
    assert passed(result) == {'native_alone', *ALONE_NATIVE}, result.stdout[-4000:]
    assert not (root / 'bin/generated').exists()
    # Nor on a machine without them: none in .local, none on PATH. A native b2 test and b2
    # declared-targets read the library's build.jam, which declares the bindings.
    for name in ('wit-bindgen', 'wasi-wit'):
        (root / '.local' / name).unlink()
    environment = without(root, 'wit-bindgen')
    result = harness.run_b2(root, '-a', 'test', env_extra=environment)
    harness.expect(result, True)
    assert passed(result) == {'native_alone', *ALONE_NATIVE}, result.stdout[-4000:]
    result = harness.run_b2(root, '-d0', 'declared-targets', env_extra=environment)
    harness.expect(result, True)
    assert result.stdout == DECLARED, result.stdout
    assert not (root / 'bin/generated').exists()


def test_missing_wit_bindgen_names_it(root):
    harness.link_wasi_tools(root)
    installed = f'{root.resolve()}/.local/wit-bindgen/wit-bindgen'
    result = harness.run_b2(root, '-a', '-sWIT_BINDGEN=/nonexistent', WASIP2, TEST)
    harness.expect(result, False, 'wit-bindgen, which generates the bindings of',
                   'demo-bindings-p2 in libs/component_demo/build.jam',
                   '-sWIT_BINDGEN=/nonexistent is not a file', '-sWIT_BINDGEN=<path>', installed,
                   'on PATH')
    # Nowhere: no -sWIT_BINDGEN, none in .local and none on PATH.
    tool = (root / '.local/wit-bindgen').resolve() / 'wit-bindgen'
    (root / '.local/wit-bindgen').unlink()
    environment = without(root, 'wit-bindgen')
    result = harness.run_b2(root, '-a', WASIP3, TEST, env_extra=environment)
    harness.expect(result, False, 'demo-bindings-p3 in libs/component_demo/build.jam',
                   'no -sWIT_BINDGEN=<path> was given', f'there is none at {installed}',
                   'none on PATH')
    # On PATH, it is found there; at -sWIT_BINDGEN, there.
    on_path = root / 'on path'
    on_path.mkdir()
    (on_path / 'wit-bindgen').symlink_to(tool)
    environment = {'PATH': f'{on_path}:{environment["PATH"]}'}
    harness.expect(harness.run_b2(root, '-a', WASIP2, TEST, env_extra=environment), True)
    shutil.rmtree(root / 'bin')
    harness.expect(harness.run_b2(root, '-a', f'-sWIT_BINDGEN={tool}', WASIP2, TEST), True)


def test_missing_wit_names_it(root):
    harness.link_wasi_tools(root)
    for toolset, version in ((WASIP2, 'P2'), (WASIP3, 'P3')):
        result = harness.run_b2(root, '-a', f'-sWASI_WIT_{version}=/nonexistent', toolset, TEST)
        harness.expect(result, False, f'The WIT of {version.lower()}',
                       f'-sWASI_WIT_{version}=/nonexistent is not a directory',
                       f'{root.resolve()}/.local/wasi-wit/{version.lower()}')
    # Nowhere: no -sWASI_WIT_P2 and none in .local; then given, it is read there.
    wit = (root / '.local/wasi-wit').resolve()
    (root / '.local/wasi-wit').unlink()
    result = harness.run_b2(root, '-a', WASIP2, TEST)
    harness.expect(result, False, 'no -sWASI_WIT_P2=<dir> was given',
                   f'there is none at {root.resolve()}/.local/wasi-wit/p2')
    harness.expect(harness.run_b2(root, '-a', f'-sWASI_WIT_P2={wit}/p2', WASIP2, TEST), True)


def test_missing_world_file_names_it(root):
    harness.link_wasi_tools(root)
    (root / LIBRARY / 'wit/world-p2.wit').unlink()
    result = harness.run_b2(root, '-a', WASIP2, TEST)
    harness.expect(result, False, 'demo-bindings-p2 in libs/component_demo/build.jam',
                   f'its world file, {(root / LIBRARY).resolve()}/wit/world-p2.wit, does not '
                   'exist')
    # The other version, and a native build, do not read it.
    harness.expect(harness.run_b2(root, '-a', WASIP3, TEST), True)
    harness.expect(harness.run_b2(root, '-a', TEST), True)


def test_wit_bindgen_failure_names_it(root):
    harness.link_wasi_tools(root)
    world = root / LIBRARY / 'wit/world-p2.wit'
    world.write_text(world.read_text().replace('world demo {', 'world demo { oops'))
    result = harness.run_b2(root, '-a', WASIP2, TEST)
    harness.expect(result, False, 'demo-bindings-p2 in libs/component_demo/build.jam',
                   'wit-bindgen could not write the bindings of',
                   'expected `import`, `export`, `include`, `use`, or type definition')
    # Nothing half-written is left where the bindings go, nor beside it.
    assert not (root / 'bin/generated/component_demo').exists() or not list(
        (root / 'bin/generated/component_demo').iterdir())


def test_unknown_version_is_refused(root):
    build = root / LIBRARY / 'build.jam'
    harness.replace(build, 'demo_world : p2 ;', 'demo_world : p4 ;')
    result = harness.run_b2(root, '-d0', 'declared-targets')
    harness.expect(result, False, 'webcpp.wit-bindings demo-bindings-p2: p4 is not a WASI version',
                   'libs/component_demo/build.jam', 'the versions are p2 p3')


def test_dry_run_generates_the_header(root):
    harness.link_wasi_tools(root)
    for toolset, version in ((WASIP2, 'p2'), (WASIP3, 'p3')):
        result = harness.run_b2(root, '-n', '-a', toolset, TEST)
        harness.expect(result, True)
        assert (generated(root, version) / 'demo_world.h').is_file(), version
        # Nothing was compiled.
        assert not list((root / 'bin/libs').rglob('*.o')), version


def test_headers_target_generates_on_any_toolset(root):
    harness.link_wasi_tools(root)
    # A native build, such as the API reference's, parses the header of either version.
    native = root / LIBRARY / 'native'
    native.mkdir()
    (native / 'Jamfile').write_text(''.join(
        f'obj parses_{version} : parses.cpp\n'
        f'  : <library>/webcpp/component_demo//demo-bindings-{version}-headers ;\n'
        for version in ('p2', 'p3')))
    (native / 'parses.cpp').write_text('#include <demo_world.h>\n'
                                       '\n'
                                       'static_assert(sizeof(demo_world_string_t) > 0);\n')
    result = harness.run_b2(root, '-a', f'{LIBRARY}/native')
    harness.expect(result, True)
    for version in ('p2', 'p3'):
        assert (generated(root, version) / 'demo_world.h').is_file(), version
        assert sorted((root / 'bin').rglob(f'parses_{version}.o')), result.stdout[-4000:]
    # Without the tools, it names them.
    (root / '.local/wit-bindgen').unlink()
    result = harness.run_b2(root, '-a', f'{LIBRARY}/native',
                            env_extra=without(root, 'wit-bindgen'))
    harness.expect(result, False, 'wit-bindgen, which generates the bindings of')


def test_unchanged_inputs_keep_the_bindings(root):
    harness.link_wasi_tools(root)
    header = generated(root, 'p2') / 'demo_world.h'

    def build(*arguments):
        harness.expect(harness.run_b2(root, '-a', *arguments, WASIP2, TEST), True)
        return identity(header)

    first = build()
    assert build() == first
    # An edited world file writes them again.
    world = root / LIBRARY / 'wit/world-p2.wit'
    world.write_text(world.read_text() + '// An edit.\n')
    second = build()
    assert second != first
    assert build() == second
    # So does another argument of wit-bindgen.
    harness.replace(root / LIBRARY / 'build.jam', 'demo_world : p2 ;',
                    'demo_world : p2 : --type-section-suffix _edit ;')
    third = build()
    assert third != second
    # And a WIT whose files changed, here a copy of it given with -sWASI_WIT_P2.
    wit = root / 'wit copy'
    shutil.copytree((root / '.local/wasi-wit/p2').resolve(), wit)
    fourth = build(f'-sWASI_WIT_P2={wit}')
    assert fourth != third
    assert build(f'-sWASI_WIT_P2={wit}') == fourth
    (wit / 'random.wit').write_text((wit / 'random.wit').read_text() + '\n')
    assert build(f'-sWASI_WIT_P2={wit}') != fourth
    # A file of theirs that is missing, its stamp still there, writes them again.
    for name in ('demo_world.h', 'demo_world.c', 'demo_world_component_type.o'):
        before = build(f'-sWASI_WIT_P2={wit}')
        (header.parent / name).unlink()
        assert build(f'-sWASI_WIT_P2={wit}') != before, name
        assert (header.parent / name).is_file(), name
    # No temporary directory is left beside them.
    assert sorted(path.name for path in header.parent.parent.iterdir()) == ['demo-bindings-p2']


def test_a_name_declared_twice_is_refused(root):
    # Two declarations of one name in a library would share a directory of bindings.
    harness.replace(root / TEST / 'Jamfile', 'webcpp.targets native wasip2 wasip3 ;',
                    'webcpp.targets native wasip2 wasip3 ;\n'
                    'webcpp.wit-bindings demo-bindings-p2 : ../wit/world-p2.wit : demo : demo_world'
                    ' : p2 ;')
    result = harness.run_b2(root, '-d0', 'declared-targets')
    harness.expect(result, False, 'webcpp.wit-bindings demo-bindings-p2 is declared twice in the '
                   'library component_demo: in libs/component_demo/build.jam and in '
                   'libs/component_demo/test/Jamfile')


def test_shell_characters_in_arguments_reach_wit_bindgen(root):
    # A $ and a ' in an argument are neither expanded nor end a quotation, in the script that
    # runs wit-bindgen and in the stamp.
    harness.link_wasi_tools(root)
    suffix = "_it's$HOME`id`"
    harness.replace(root / LIBRARY / 'build.jam', 'demo_world : p2 ;',
                    f'demo_world : p2 : --type-section-suffix "{suffix}" ;')
    harness.expect(harness.run_b2(root, '-a', WASIP2, TEST), True)
    directory = generated(root, 'p2')
    inputs = (directory / 'inputs').read_text()
    assert (f'arguments --world "demo" --rename-world "demo_world" "--type-section-suffix" '
            f'"{suffix}"\n') in inputs, inputs
    assert suffix.encode() in (directory / 'demo_world_component_type.o').read_bytes()


SERVED_EXPECTED = harness.FIXTURES / 'component_demo/test/answers.expected'


def linked_wasmtime(root):
    """-sWASMTIME= a link, inside root, to the wasmtime on PATH: every wasmtime the build starts
    is then named with root's path, which the processes of another run do not hold."""
    real = shutil.which('wasmtime')
    assert real, 'wasmtime is not on PATH'
    link = root / 'linked tools/wasmtime'
    link.parent.mkdir(exist_ok=True)
    link.symlink_to(real)
    return f'-sWASMTIME={link}'


def left(root, seconds=5):
    """The processes that name root, which a finished build must not leave, after waiting up to
    seconds for them to go: a killed process is a zombie until its parent reaps it."""
    deadline = time.monotonic() + seconds
    while True:
        listed = subprocess.run(['ps', '-A', '-o', 'pid=,command='], capture_output=True,
                                text=True, check=True)
        found = [line for line in listed.stdout.splitlines() if root.name in line]
        if not found or time.monotonic() > deadline:
            return found
        time.sleep(0.1)


def built_in(root, name, version):
    """The files called name that a build for the WASI version, 2 or 3, wrote under root/bin."""
    return [path for path in (root / 'bin').rglob(name) if f'wasip{version}' in str(path)]


def link_line(output, program):
    """The line of b2's -d+2 output that links program."""
    return next(line for line in output.splitlines()
                if '-mexec-model=reactor' in line and f'/{program} ' in line.replace('"', ' '))


def test_served_component_green_on_wasip2_and_wasip3(root):
    harness.link_wasi_tools(root)
    wasmtime = linked_wasmtime(root)
    # Two lanes at once, each in a build directory of its own: two wasmtimes serve at the same
    # time, each on a port of its own.
    lanes = harness.run_lanes(root, {
        version: ('-a', '-d+2', f'--build-dir=bin/lane-wasip{version}',
                  f'toolset=clang-wasip{version}', wasmtime, TEST)
        for version in (2, 3)})
    for version, result in lanes.items():
        output = result.stdout
        assert result.returncode == 0, (version, output[-4000:])
        assert passed(result) == {'bindings', 'answers', *ALONE_WASI}, output[-4000:]
        served = built_in(root, 'answers.served', version)
        assert len(served) == 1, served
        assert served[0].read_bytes() == SERVED_EXPECTED.read_bytes()
        # The component is built in the test's directory, as a reactor, and linked on wasip2
        # with the handler of a program built without exceptions, which it calls.
        assert 'answers.test' in served[0].parts, served
        line = link_line(output, 'answers.wasm')
        assert ('throw_exception.o' in line) == (version == 2), line
        # The program to serve by hand is not built by default.
        assert not built_in(root, 'answers-component.wasm', version)
    assert not left(root), left(root)
    # Named, it is: a component.
    harness.expect(harness.run_b2(root, WASIP2, f'{TEST}//answers-component'), True)
    components = built_in(root, 'answers-component.wasm', 2)
    assert len(components) == 1 and components[0].read_bytes()[:8] == COMPONENT, components


def test_wrong_expected_is_a_run_failure_in_the_report(root):
    harness.link_wasi_tools(root)
    wasmtime = linked_wasmtime(root)
    harness.replace(root / TEST / 'answers.expected', 'HTTP/1.1 404 Not Found',
                    'HTTP/1.1 405 Method Not Allowed')
    # Alone, b2 fails.
    harness.expect(harness.run_b2(root, '-a', WASIP2, wasmtime, TEST), False,
                   '-HTTP/1.1 405 Method Not Allowed', '+HTTP/1.1 404 Not Found')
    assert not left(root), left(root)
    # With --out-xml, b2 exits 0, and the report is the verdict: the test is listed, and its
    # failure is a run failure, its diff a click away.
    result = harness.run_b2(root, '-a', '--dump-tests', '--out-xml=wasip2.xml', WASIP2, wasmtime,
                            TEST)
    harness.expect(result, True)
    lane = (root / 'wasip2.xml').read_text()
    assert '<test type="SERVE" name="component_demo/answers">' in lane, lane[-4000:]
    report = subprocess.run([sys.executable, str(harness.ROOT / 'tools/report/report.py'),
                             '--lane', f'wasip2={root / "wasip2.xml"}', '--out',
                             str(root / 'report')], capture_output=True, text=True, check=False)
    assert report.returncode == 1, (report.stdout, report.stderr)
    assert report.stderr.splitlines() == ['report: wasip2: component_demo/answers: run'], (
        report.stderr)
    page = (root / 'report/component_demo.html').read_text()
    linked = re.search(r'href="(output/[^"]*answers[^"]*)"', page)
    assert linked, page
    output = (root / 'report' / linked.group(1)).read_text()
    assert '-HTTP/1.1 405 Method Not Allowed' in output and '+HTTP/1.1 404 Not Found' in output, (
        output)
    assert not left(root), left(root)


def refused(root, jamfile, files=('p.cpp', 'p.requests', 'p.expected')):
    """The output of b2 loading a library directory whose Jamfile is jamfile, beside files, a
    served program p.cpp with its requests and transcript unless told otherwise."""
    directory = root / LIBRARY / 'refused'
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir()
    (directory / 'Jamfile').write_text('import webcpp ;\n\n' + jamfile)
    for name in files:
        (directory / name).write_text('')
    return harness.run_b2(root, '-d0', '-n', f'{LIBRARY}/refused')


def test_serve_refuses_native(root):
    where = 'webcpp.serve p.cpp in libs/component_demo/refused/Jamfile'
    for target in ('native', 'emscripten'):
        harness.expect(refused(root, f'webcpp.serve p.cpp : : wasip2 {target} ;\n'), False,
                       f'{where}: {target} is not a target a component is served on')
    # A Jamfile whose targets name neither wasip2 nor wasip3 serves nothing: refused too.
    for declared in ('webcpp.targets native ;\n', ''):
        harness.expect(refused(root, f'{declared}webcpp.serve p.cpp ;\n'), False,
                       f"{where}: its Jamfile's targets, native, name neither wasip2 nor wasip3")
    # One that declares native beside a WASI target serves on that target alone, with no word.
    harness.expect(refused(root, 'webcpp.targets native wasip2 ;\nwebcpp.serve p.cpp ;\n'), True)
    # The requests and the transcript are read beside the source.
    for missing in ('p.requests', 'p.expected'):
        files = [name for name in ('p.cpp', 'p.requests', 'p.expected') if name != missing]
        harness.expect(refused(root, 'webcpp.serve p.cpp : : wasip3 ;\n', files), False,
                       f'{where}: there is no {missing} beside it')


def test_native_lane_skips_served_tests(root):
    harness.link_wasi_tools(root)
    nowhere = ('-sWIT_BINDGEN=/nonexistent', '-sWASI_WIT_P2=/nonexistent',
               '-sWASI_WIT_P3=/nonexistent', '-sWASMTIME=/nonexistent')
    # A dry run asks for no tool and generates nothing.
    harness.expect(harness.run_b2(root, '-n', '-a', *nowhere, TEST), True)
    assert not (root / 'bin/generated').exists()
    result = harness.run_b2(root, '-a', '--dump-tests', '--out-xml=native.xml', *nowhere, TEST)
    harness.expect(result, True)
    assert passed(result) == {'native_alone', *ALONE_NATIVE}, result.stdout[-4000:]
    assert not (root / 'bin/generated').exists()
    assert not list((root / 'bin').rglob('answers*')), sorted((root / 'bin').rglob('answers*'))
    # The lane lists the served test, which it does not build.
    assert '<test type="SERVE" name="component_demo/answers">' in (root / 'native.xml').read_text()


def test_missing_wasmtime_names_it(root):
    # wasmtime is looked up when the served test runs: the test fails, naming it, and b2 shows
    # why.
    harness.link_wasi_tools(root)
    named = 'wasmtime, which serves the test of webcpp.serve answers.cpp in ' \
            'libs/component_demo/test/Jamfile, was not found:'
    result = harness.run_b2(root, '-a', '-sWASMTIME=/nonexistent', WASIP2, TEST)
    harness.expect(result, False, named, '-sWASMTIME=/nonexistent is not an executable file',
                   'It is looked for at -sWASMTIME=<path>, else on PATH.',
                   '...failed webcpp-component.serve-and-compare')
    assert passed(result) == {'bindings', *ALONE_WASI}, result.stdout[-4000:]
    result = harness.run_b2(root, '-a', WASIP3, TEST, env_extra=without(root, 'wasmtime'))
    harness.expect(result, False, named, 'no -sWASMTIME=<path> was given, and there is none on '
                   'PATH')
    # In a lane, the report fails the served test by name, with the message in its output.
    result = harness.run_b2(root, '-a', '--dump-tests', '--out-xml=wasip2.xml',
                            '-sWASMTIME=/nonexistent', WASIP2, TEST)
    harness.expect(result, True)
    report = subprocess.run([sys.executable, str(harness.ROOT / 'tools/report/report.py'),
                             '--lane', f'wasip2={root / "wasip2.xml"}', '--out',
                             str(root / 'report')], capture_output=True, text=True, check=False)
    assert report.returncode == 1, (report.stdout, report.stderr)
    assert report.stderr.splitlines() == ['report: wasip2: component_demo/answers: run'], (
        report.stderr)
    page = (root / 'report/component_demo.html').read_text()
    linked = re.search(r'href="(output/[^"]*answers[^"]*)"', page)
    assert linked, page
    assert named in (root / 'report' / linked.group(1)).read_text()
    # Only a served test that runs asks for it.
    harness.expect(harness.run_b2(root, '-a', '-sWASMTIME=/nonexistent', WASIP2,
                                  f'{TEST}//bindings'), True)


def test_wasm_dry_run_needs_no_wasmtime(root):
    # A dry run, such as the one the lint's compile database makes, runs no served test, so it
    # asks for no wasmtime; it still generates the bindings, which need wit-bindgen.
    harness.link_wasi_tools(root)
    for toolset in (WASIP2, WASIP3):
        result = harness.run_b2(root, '-n', '-a', '-sWASMTIME=/nonexistent', toolset, TEST)
        harness.expect(result, True, 'serve.py')
    result = harness.run_b2(root, '-n', '-a', WASIP2, TEST, env_extra=without(root, 'wasmtime'))
    harness.expect(result, True)


# A script that builds the fixture's served program by hand, as a library's page shows one: with
# the wasi-sdk, the wit-bindgen and the WIT that webcpp.serve-script gives it, it generates the
# world's bindings, compiles them and the program, and links a reactor into its second argument,
# beside which it writes what it was given.
BY_HAND = r"""#!/bin/sh
set -e
version=$1
component=$2
here=$(cd "$(dirname "$0")" && pwd)
printf '%s\n' "$WASI_SDK" "$WIT_BINDGEN" "$WASI_WIT" > "$component.given"
work="$component.work"
rm -rf "$work"
mkdir -p "$work/wit"
cp "$here/../wit/world-$version.wit" "$work/wit/"
ln -s "$WASI_WIT" "$work/wit/deps"
if [ "$version" = p3 ]; then
    "$WIT_BINDGEN" c --world demo --rename-world demo_world \
        --async 'wasi:http/handler@0.3.0#handle' --out-dir "$work/gen" "$work/wit" > /dev/null
    threads=-pthread
else
    "$WIT_BINDGEN" c --world demo --rename-world demo_world --out-dir "$work/gen" "$work/wit" \
        > /dev/null
    threads=
fi
"$WASI_SDK/bin/clang" --target=wasm32-wasi$version $threads -c "$work/gen/demo_world.c" \
    -o "$work/demo_world.o" -I"$work/gen"
"$WASI_SDK/bin/clang++" --target=wasm32-wasi$version -std=c++20 -fno-exceptions \
    -DBOOST_NO_EXCEPTIONS -mexec-model=reactor -I"$here/../include" -I"$work/gen" \
    -isystem "@BOOST@" "$here/answers.cpp" "@ROOT@/tools/throw_exception.cpp" \
    "$work/demo_world.o" "$work/gen/demo_world_component_type.o" -o "$component"
"""


def by_hand(root):
    """Writes BY_HAND into the fixture's test directory, as by_hand.sh, and declares it the
    served test by_hand, answering the requests of answers."""
    using = harness.USING_BOOST.search(harness.user_config(harness.ROOT).read_text())
    assert using, 'this checkout\'s user-config.jam has no `using boost` line'
    include = re.search(r'<include>(\S+)', using.group(0))
    assert include, f'the `using boost` line names no <include>: {using.group(0)}'
    boost = include.group(1)
    script = BY_HAND.replace('@BOOST@', boost).replace('@ROOT@', str(root.resolve()))
    (root / TEST / 'by_hand.sh').write_text(script)
    with (root / TEST / 'Jamfile').open('a') as jamfile:
        jamfile.write('webcpp.serve-script by_hand : by_hand.sh : answers ;\n')


def without_wasi_sdk_given(root):
    """Leaves out of the scratch superproject root's user-config.jam the WASI_SDK it gives, as the
    region wasi-sdk of tools/ci/wasi-sdk.jam does, so that the build looks for wasi-sdk where it
    looks when none is given."""
    config = root / '.local/user-config.jam'
    config.write_text(re.sub(r'^modules\.poke : WASI_SDK :.*\n', '', config.read_text(),
                             flags=re.MULTILINE))


def test_a_script_builds_a_served_component(root):
    # webcpp.serve-script serves what a script builds, with the tools b2 found: wasi-sdk's
    # directory, wit-bindgen and the WIT of the lane's version, and checks its answers as
    # webcpp.serve does. wasi-sdk is where none is given here, .local/wasi-sdk.
    harness.link_wasi_tools(root)
    without_wasi_sdk_given(root)
    by_hand(root)
    wasmtime = linked_wasmtime(root)
    lanes = harness.run_lanes(root, {
        version: ('-a', f'--build-dir=bin/lane-wasip{version}', f'toolset=clang-wasip{version}',
                  wasmtime, TEST)
        for version in (2, 3)})
    for version, result in lanes.items():
        output = result.stdout
        assert result.returncode == 0, (version, output[-4000:])
        assert passed(result) == {'bindings', 'answers', 'by_hand', *ALONE_WASI}, (
            output[-4000:])
        served = built_in(root, 'by_hand.served', version)
        assert len(served) == 1, served
        assert served[0].read_bytes() == SERVED_EXPECTED.read_bytes()
        components = built_in(root, 'by_hand.wasm', version)
        assert len(components) == 1 and components[0].read_bytes()[:8] == COMPONENT, components
        given = built_in(root, 'by_hand.wasm.given', version)[0].read_text().splitlines()
        assert Path(given[0]) == root.resolve() / '.local/wasi-sdk', given
        assert Path(given[1]).resolve() == (root / '.local/wit-bindgen/wit-bindgen').resolve()
        assert Path(given[2]).resolve() == (root / f'.local/wasi-wit/p{version}').resolve()
    assert not left(root), left(root)
    # What the script builds is what is served: one that compiles the program for another
    # target fails the test.
    harness.replace(root / TEST / 'by_hand.sh',
                    '"$WASI_SDK/bin/clang++" --target=wasm32-wasi$version',
                    '"$WASI_SDK/bin/clang++" --target=wasm32-wasip1')
    result = harness.run_b2(root, '-a', WASIP2, wasmtime, f'{TEST}//by_hand')
    harness.expect(result, False)
    assert 'by_hand' not in passed(result), result.stdout[-4000:]
    harness.replace(root / TEST / 'by_hand.sh',
                    '"$WASI_SDK/bin/clang++" --target=wasm32-wasip1',
                    '"$WASI_SDK/bin/clang++" --target=wasm32-wasi$version')
    # wasi-sdk is the directory -sWASI_SDK gives, or a user-config.jam, as the region wasi-sdk of
    # tools/ci/wasi-sdk.jam does, never one read from b2's toolset; else .local/wasi-sdk.
    elsewhere = root / 'another wasi-sdk'
    elsewhere.symlink_to((root / '.local/wasi-sdk').resolve())
    for given_by in ('command line', 'user-config'):
        arguments = [f'-sWASI_SDK={elsewhere}'] if given_by == 'command line' else []
        if given_by == 'user-config':
            config = root / '.local/user-config.jam'
            config.write_text(config.read_text() + f'modules.poke : WASI_SDK : "{elsewhere}" ;\n')
        result = harness.run_b2(root, '-a', '--build-dir=bin/given', WASIP2, wasmtime,
                                *arguments, f'{TEST}//by_hand')
        harness.expect(result, True, '**passed**')
        given = [path for path in built_in(root, 'by_hand.wasm.given', 2)
                 if (root / 'bin/given') in path.parents]
        assert len(given) == 1, given
        assert given[0].read_text().splitlines()[0] == str(elsewhere), (given_by, given)
    without_wasi_sdk_given(root)
    # A wasi-sdk given that holds no clang++, and none given and none at .local/wasi-sdk, stop the
    # build, naming every place it looked.
    where = 'It is looked for at -sWASI_SDK=<dir>, which a user-config.jam may give'
    result = harness.run_b2(root, '-a', WASIP2, wasmtime, f'-sWASI_SDK={root / "nothing"}',
                            f'{TEST}//by_hand')
    harness.expect(result, False, 'webcpp.serve-script by_hand in libs/component_demo/test/Jamfile',
                   f'-sWASI_SDK={root / "nothing"} holds no bin/clang++', where)
    (root / '.local/wasi-sdk').unlink()
    result = harness.run_b2(root, '-a', WASIP2, wasmtime, f'{TEST}//by_hand')
    harness.expect(result, False, 'no -sWASI_SDK=<dir> was given, and there is none at '
                   f'{(root / ".local/wasi-sdk").resolve()}')
    # Natively, it is built nowhere, and asks for no tool.
    nowhere = ('-sWIT_BINDGEN=/nonexistent', '-sWASI_WIT_P2=/nonexistent',
               '-sWASI_WIT_P3=/nonexistent', '-sWASMTIME=/nonexistent', '-sWASI_SDK=/nonexistent')
    result = harness.run_b2(root, '-a', *nowhere, TEST)
    harness.expect(result, True)
    assert 'by_hand' not in passed(result), result.stdout[-4000:]


def test_serve_script_refuses_what_is_not_there(root):
    where = 'webcpp.serve-script b in libs/component_demo/refused/Jamfile'
    files = ('b.sh', 'p.requests', 'p.expected')
    harness.expect(refused(root, 'webcpp.serve-script b : b.sh : p : wasip2 ;\n', files), True)
    for missing in files:
        present = [name for name in files if name != missing]
        harness.expect(refused(root, 'webcpp.serve-script b : b.sh : p : wasip2 ;\n', present),
                       False, f'{where}: there is no {missing} beside it')
    harness.expect(refused(root, 'webcpp.serve-script b : b.sh : p : native ;\n', files), False,
                   f'{where}: native is not a target a component is served on')


# A stand-in for wasmtime that starts the real one, writes the pids of both into the file mark
# once the real one serves, and says so itself only pause seconds later: a window in which the
# test interrupts b2, or b2 stops the action.
SLOW_WASMTIME = """#!{python}
import os
import subprocess
import sys
import time

real = subprocess.Popen([{real!r}, *sys.argv[1:]], stderr=subprocess.PIPE)
line = real.stderr.readline()
with open({mark!r}, 'w') as mark:
    mark.write(f'{{os.getpid()}} {{real.pid}}')
time.sleep({pause})
sys.stderr.buffer.write(line)
sys.stderr.flush()
for line in real.stderr:
    sys.stderr.buffer.write(line)
    sys.stderr.flush()
real.wait()
"""


def test_an_interrupted_b2_leaves_no_wasmtime(root):
    harness.link_wasi_tools(root)
    mark = root / 'serving'
    slow = root / 'linked tools/slow-wasmtime'
    slow.parent.mkdir()
    slow.write_text(SLOW_WASMTIME.format(python=sys.executable, real=shutil.which('wasmtime'),
                                         mark=str(mark), pause=3))
    slow.chmod(0o755)
    process = harness.start_b2(root, '-a', WASIP2, f'-sWASMTIME={slow}', f'{TEST}//answers')
    deadline = time.monotonic() + harness.TIMEOUT
    while not mark.exists() or not mark.read_text():
        assert process.poll() is None, process.communicate()[0][-4000:]
        assert time.monotonic() < deadline, 'wasmtime never served'
        time.sleep(0.05)
    pids = [int(word) for word in mark.read_text().split()]
    # b2 is interrupted as a terminal does it: SIGINT to its process group, which holds b2
    # alone, since b2 gives each action a group of its own. b2 ends; serve.py, left behind,
    # finishes its run and stops wasmtime.
    os.killpg(process.pid, signal.SIGINT)
    process.communicate(timeout=60)
    assert process.returncode != 0
    assert not left(root, seconds=60), left(root)
    for pid in pids:
        try:
            os.kill(pid, 0)
            raise AssertionError(f'{pid} is still there')
        except ProcessLookupError:
            pass


def test_a_b2_that_kills_its_action_leaves_no_wasmtime(root):
    harness.link_wasi_tools(root)
    # The component first, as it is: the run below has b2 serve it, and nothing else.
    harness.expect(harness.run_b2(root, '-a', WASIP2, linked_wasmtime(root), f'{TEST}//answers'),
                   True, '**passed**')
    mark = root / 'serving'
    slow = root / 'linked tools/slow-wasmtime'
    slow.write_text(SLOW_WASMTIME.format(python=sys.executable, real=shutil.which('wasmtime'),
                                         mark=str(mark), pause=60))
    slow.chmod(0o755)
    # b2 -l stops an action that outlasts it with a SIGKILL to the action's process group, which
    # serve.py cannot answer: wasmtime, which says it serves only a minute after it does, is
    # stopped all the same, by the keeper serve.py starts it under.
    began = time.monotonic()
    result = harness.run_b2(root, '-l', '15', WASIP2, f'-sWASMTIME={slow}', f'{TEST}//answers')
    try:
        harness.expect(result, False)
        assert time.monotonic() - began < 60, time.monotonic() - began
        assert mark.is_file() and mark.read_text(), 'wasmtime never served'
        assert not left(root, seconds=30), left(root)
        # The real wasmtime too, whose command names its component by a path relative to root,
        # once the system has reaped it.
        deadline = time.monotonic() + 30
        for pid in [int(word) for word in mark.read_text().split()]:
            while True:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                assert time.monotonic() < deadline, f'{pid} is still there'
                time.sleep(0.1)
    finally:
        for pid in [int(word) for word in mark.read_text().split()] if mark.is_file() else []:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


CASES = [
    test_bindings_generated_for_wasip2_and_wasip3,
    test_bindings_link_into_a_component,
    test_native_build_needs_no_wit_bindgen,
    test_missing_wit_bindgen_names_it,
    test_missing_wit_names_it,
    test_missing_world_file_names_it,
    test_wit_bindgen_failure_names_it,
    test_unknown_version_is_refused,
    test_dry_run_generates_the_header,
    test_headers_target_generates_on_any_toolset,
    test_unchanged_inputs_keep_the_bindings,
    test_a_name_declared_twice_is_refused,
    test_shell_characters_in_arguments_reach_wit_bindgen,
    test_served_component_green_on_wasip2_and_wasip3,
    test_wrong_expected_is_a_run_failure_in_the_report,
    test_serve_refuses_native,
    test_native_lane_skips_served_tests,
    test_missing_wasmtime_names_it,
    test_wasm_dry_run_needs_no_wasmtime,
    test_an_interrupted_b2_leaves_no_wasmtime,
    test_a_b2_that_kills_its_action_leaves_no_wasmtime,
    test_a_script_builds_a_served_component,
    test_serve_script_refuses_what_is_not_there,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('component_jam_test', CASES, sys.argv[1:],
                               fixtures=('component_demo',)))
