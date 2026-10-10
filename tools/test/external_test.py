#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks webcpp.external-root and webcpp.external-found (tools/webcpp.jam), how a library's
build.jam finds a library webcpp does not build: from -s<VARIABLE>=<dir> on b2's command line, else
.local/<directory> when that holds the header, never from the environment; a -s that names a
directory without the header stops the build, naming it; and when no candidate holds the header,
the library is left out, its programs skipped, with one message that names it, what is missing and
how to give it, while the other libraries build, unless the build asks webcpp-require-external=on,
as the CI does, which stops it instead. Each case runs in a scratch superproject with the fixture
demo and a library needs_ext, which needs the fake library libfake, whose header is fake.h. Run
with the names of some cases to run only those."""

from __future__ import annotations

import sys
from pathlib import Path

import harness

BUILD = ('project /webcpp/needs_ext ;\n'
         '\n'
         'import webcpp ;\n'
         '\n'
         'local fake-root = [ webcpp.external-root FAKE_ROOT : fake : fake.h ] ;\n'
         '\n'
         'rule fake-found ( properties * )\n'
         '{\n'
         '    return [ webcpp.external-found needs_ext : libfake : FAKE_ROOT : fake : fake.h\n'
         '        : : $(properties) ] ;\n'
         '}\n'
         '\n'
         'alias needs_ext : : <conditional>@fake-found : : <include>$(fake-root)/include ;\n')

TEST = ('project : requirements <library>/webcpp/needs_ext//needs_ext ;\n'
        '\n'
        'import webcpp ;\n'
        '\n'
        'webcpp.run uses : uses.cpp ;\n')

USES = '#include <fake.h>\n\nint main() { return fake_answer() - 42; }\n'

HEADER = 'inline int fake_answer() { return 42; }\n'

LEFT_OUT = 'webcpp: needs_ext is left out: libfake was not found'


def needs_ext(root: Path) -> None:
    """Adds the library needs_ext to root."""
    harness.add_library(root, 'needs_ext', TEST, {'uses.cpp': USES})
    (root / 'libs/needs_ext/build.jam').write_text(BUILD)


def fake(directory: Path) -> Path:
    """directory, holding include/fake.h."""
    (directory / 'include').mkdir(parents=True)
    (directory / 'include/fake.h').write_text(HEADER)
    return directory


def built(output: str, name: str) -> bool:
    """Whether b2 ran the test name: its **passed** line."""
    return any(line.startswith('**passed**') and f'/{name}.test' in line
               for line in output.splitlines())


def test_a_missing_library_leaves_its_user_out_and_builds_the_others(root):
    needs_ext(root)
    result = harness.run_b2(root, '-a', 'libs/needs_ext/test', 'libs/demo/test//pass',
                            env_extra={'FAKE_ROOT': None})
    assert result.returncode == 0, result.stdout[-4000:]
    assert result.stdout.count(LEFT_OUT) == 1, result.stdout[-4000:]
    local = (root / '.local/fake').resolve()
    assert (f'{LEFT_OUT}: -sFAKE_ROOT=<dir> was not given, and {local}/include holds no '
            'fake.h. Give -sFAKE_ROOT=<dir>, the directory of its include/ and lib/, or install '
            f'it in {local}, as libs/needs_ext/README.md says.') in result.stdout, (
                result.stdout[-4000:])
    assert built(result.stdout, 'pass') and not built(result.stdout, 'uses'), result.stdout[-4000:]


def test_the_ci_requires_it(root):
    needs_ext(root)
    result = harness.run_b2(root, '-a', 'webcpp-require-external=on', 'libs/needs_ext/test',
                            'libs/demo/test//pass')
    assert result.returncode != 0, result.stdout[-4000:]
    assert ('error: libfake was not found, and the build requires it '
            '(webcpp-require-external=on): -sFAKE_ROOT=<dir> was not given') in result.stdout, (
                result.stdout[-4000:])


def test_the_command_line_or_local_finds_it_and_the_environment_never_does(root):
    needs_ext(root)
    elsewhere = fake(root / 'elsewhere')
    # The environment is never read: a stale variable that names a valid build changes nothing.
    result = harness.run_b2(root, '-a', 'libs/needs_ext/test',
                            env_extra={'FAKE_ROOT': str(elsewhere)})
    assert result.returncode == 0 and LEFT_OUT in result.stdout, result.stdout[-4000:]
    assert not built(result.stdout, 'uses'), result.stdout[-4000:]
    # -s on the command line.
    result = harness.run_b2(root, '-a', f'-sFAKE_ROOT={elsewhere}', 'libs/needs_ext/test')
    assert result.returncode == 0 and built(result.stdout, 'uses'), result.stdout[-4000:]
    assert LEFT_OUT not in result.stdout, result.stdout[-4000:]
    # .local/<directory>, where the CI's actions install.
    fake(root / '.local/fake')
    result = harness.run_b2(root, '-a', 'webcpp-require-external=on', 'libs/needs_ext/test')
    assert result.returncode == 0 and built(result.stdout, 'uses'), result.stdout[-4000:]


def test_a_command_line_without_the_header_stops_the_build(root):
    needs_ext(root)
    fake(root / '.local/fake')
    empty = root / 'empty'
    empty.mkdir()
    result = harness.run_b2(root, '-a', f'-sFAKE_ROOT={empty}', 'libs/needs_ext/test')
    assert result.returncode != 0, result.stdout[-4000:]
    assert (f'error: -sFAKE_ROOT={empty} holds no include/fake.h: give the directory of '
            "libfake's include/ and lib/") in result.stdout, result.stdout[-4000:]


CASES = [
    test_a_missing_library_leaves_its_user_out_and_builds_the_others,
    test_the_ci_requires_it,
    test_the_command_line_or_local_finds_it_and_the_environment_never_does,
    test_a_command_line_without_the_header_stops_the_build,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('external_test', CASES, sys.argv[1:]))
