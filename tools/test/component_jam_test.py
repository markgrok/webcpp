#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/component/component.jam: webcpp.wit-bindings generates a world's C bindings with
wit-bindgen for wasip2 and wasip3, where a translation unit that includes them compiles and a
component that uses them links; natively it adds nothing and asks for no tool, unless its
-headers target is named; a missing wit-bindgen, WIT or world file stops the build naming it and
where it was looked for; a dry run generates the header; and the bindings are written again only
when what they are made from changes. Each case builds a scratch superproject with the fixture
library component_demo, given this checkout's wit-bindgen and WIT. Run with the names of some
cases to run only those."""

from __future__ import annotations

import re
import shutil
import sys

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
        assert passed(result) == {'bindings'}, result.stdout[-4000:]
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
    assert passed(result) == {'native_alone'}, result.stdout[-4000:]
    assert not (root / 'bin/generated').exists()
    # Nor on a machine without them: none in .local, none on PATH. A native b2 test and b2
    # declared-targets read the library's build.jam, which declares the bindings.
    for name in ('wit-bindgen', 'wasi-wit'):
        (root / '.local' / name).unlink()
    environment = without(root, 'wit-bindgen')
    result = harness.run_b2(root, '-a', 'test', env_extra=environment)
    harness.expect(result, True)
    assert passed(result) == {'native_alone'}, result.stdout[-4000:]
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
    # No temporary directory is left beside them.
    assert sorted(path.name for path in header.parent.parent.iterdir()) == ['demo-bindings-p2']


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
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('component_jam_test', CASES, sys.argv[1:],
                               fixtures=('component_demo',)))
