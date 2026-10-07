#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/oracle/oracle.jam and webcpp.lane: a library's oracle lane runs its twins and its
cases on the original and fails naming a difference; update-expected rewrites what the original
writes, refuses an own output that agrees, and stays red when the original fails; `b2
declared-lanes` lists the lanes the libraries declare; and only an oracle target needs Node. Each
case builds a scratch superproject with the fixture library oracle_demo. Run with the names of
some cases to run only those."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import harness

LIBRARY = 'libs/oracle_demo'
ORACLE = f'{LIBRARY}/test/oracle'
LANE = f'{ORACLE}//oracle'
UPDATE = f'{ORACLE}//update-expected'

# What a lane line of `b2 declared-lanes` says for the fixture.
ORACLE_LANE = 'oracle_demo oracle libs/oracle_demo/test/oracle\n'

PLAIN_SOURCE = 'int main() { return 0; }\n'


def without(root: Path, *tools: str) -> dict[str, str]:
    """The environment of a b2 run where none of tools is on PATH: each directory of PATH that
    holds one is replaced with one of root's, made of links to everything else it holds, so that
    b2, python3 and the compilers beside them are still found.

    Tip: b2 is a script that starts the real one, not a link: b2 looks for its own Jam files
    beside the path it was started from, which a link would move."""
    shadows: dict[str, str] = {}
    directories = []
    for directory in os.environ['PATH'].split(os.pathsep):
        source = Path(directory)
        if not directory or not any((source / tool).exists() for tool in tools):
            directories.append(directory)
            continue
        if directory not in shadows:
            shadow = root / 'without tools' / str(len(shadows))
            shadow.mkdir(parents=True)
            for entry in source.iterdir():
                if entry.name == 'b2':
                    (shadow / 'b2').write_text(f'#!/bin/sh\nexec "{entry}" "$@"\n')
                    (shadow / 'b2').chmod(0o755)
                elif entry.name not in tools:
                    (shadow / entry.name).symlink_to(entry)
            shadows[directory] = str(shadow)
        directories.append(shadows[directory])
    path = os.pathsep.join(directories)
    for tool in tools:
        assert shutil.which(tool, path=path) is None, (tool, path)
    return {'PATH': path}


def test_lane_runs_twins_and_cases_green(root):
    result = harness.run_b2(root, '-a', LANE)
    harness.expect(result, True)
    # The twins ran, and the cases' script wrote what the comparison found equal to the committed
    # expected results.
    assert 'run-twins' in result.stdout, result.stdout[-4000:]
    assert 'run-cases' in result.stdout, result.stdout[-4000:]
    written = sorted((root / 'bin').rglob('squares/three.json'))
    assert len(written) == 1, (written, result.stdout[-4000:])
    expected = root / LIBRARY / 'test/fixtures/expected/three.json'
    assert written[0].read_bytes() == expected.read_bytes()


def test_twin_difference_fails_the_lane(root):
    (root / LIBRARY / 'example/square.expected').write_text('3 squared is 8.\n')
    result = harness.run_b2(root, '-a', LANE)
    harness.expect(result, False, 'twins: square: differs', '-3 squared is 8.',
                   '+3 squared is 9.')
    # The other twins are compared too, and agree.
    assert 'twins: half' not in result.stdout, result.stdout[-4000:]


def test_case_difference_fails_the_lane(root):
    expected = root / LIBRARY / 'test/fixtures/expected/three.json'
    expected.write_text(expected.read_text().replace('9', '10'))
    result = harness.run_b2(root, '-a', LANE)
    harness.expect(result, False, 'compare: ',
                   'test/fixtures/expected/three.json: contents differ')
    assert 'seven.json' not in result.stdout, result.stdout[-4000:]


def test_update_expected_rewrites_cases(root):
    expected = root / LIBRARY / 'test/fixtures/expected'
    before = {path.name: path.read_bytes() for path in expected.iterdir()}
    own = root / ORACLE / 'twins/half.expected'
    own_before = own.read_bytes()
    (expected / 'three.json').unlink()
    # A file the original does not write goes: the directory is written again whole.
    (expected / 'stale.json').write_text('{}\n')
    result = harness.run_b2(root, '-a', UPDATE)
    harness.expect(result, True)
    after = {path.name: path.read_bytes() for path in expected.iterdir()}
    assert after == before, (sorted(after), sorted(before))
    # The divergent twin's own output is written again from the original, unchanged.
    assert own.read_bytes() == own_before
    # The whole directory, gone, comes back too.
    shutil.rmtree(expected)
    harness.expect(harness.run_b2(root, '-a', UPDATE), True)
    after = {path.name: path.read_bytes() for path in expected.iterdir()}
    assert after == before, (sorted(after), sorted(before))


def test_update_expected_refuses_agreeing_twin(root):
    # An own output for square, whose twin prints what the program prints.
    program = (root / LIBRARY / 'example/square.expected').read_bytes()
    own = root / ORACLE / 'twins/square.expected'
    own.write_bytes(program)
    result = harness.run_b2(root, '-a', UPDATE)
    harness.expect(result, False, 'twins: square: --update refuses')
    assert own.read_bytes() == program
    # The lane refuses it too.
    harness.expect(harness.run_b2(root, '-a', LANE), False,
                   "twins: square: its own output is the program's")


def test_failing_script_leaves_update_red(root):
    script = root / ORACLE / 'cases.mjs'
    script.write_text(script.read_text().replace(
        "const [casesDirectory, outputDirectory] = process.argv.slice(2);\n",
        "const [casesDirectory, outputDirectory] = process.argv.slice(2);\nprocess.exit(1);\n"))
    result = harness.run_b2(root, '-a', UPDATE)
    harness.expect(result, False)
    assert '...failed' in result.stdout, result.stdout[-4000:]
    # The twins are not updated after the cases failed.
    assert 'update-twins' not in result.stdout.split('...failed', 1)[1], result.stdout[-4000:]


def test_declared_lanes_lists_the_oracle(root):
    result = harness.run_b2(root, '-d0', 'declared-lanes')
    harness.expect(result, True)
    assert result.stdout == ORACLE_LANE, result.stdout
    # Sorted across libraries, from a test or an example Jamfile at any depth.
    harness.add_library(root, 'alpha',
                        'import webcpp ;\n'
                        '\n'
                        'webcpp.run plain : plain.cpp ;\n'
                        'webcpp.lane http : plain ;\n',
                        {'plain.cpp': PLAIN_SOURCE})
    (root / 'libs/alpha/example/browser').mkdir(parents=True)
    (root / 'libs/alpha/example/browser/Jamfile').write_text(
        'import webcpp ;\n'
        '\n'
        'webcpp.example page.cpp ;\n'
        'webcpp.lane browser : page.output ;\n')
    lanes = ('alpha browser libs/alpha/example/browser\n'
             'alpha http libs/alpha/test\n' + ORACLE_LANE)
    result = harness.run_b2(root, '-d0', 'declared-lanes')
    harness.expect(result, True)
    assert result.stdout == lanes, result.stdout
    # It reads only Jamfiles: CI plans its lanes on a machine without Boost.
    harness.configure(root, harness.without_boost())
    result = harness.run_b2(root, '-d0', 'declared-lanes', env_extra={'BOOST_ROOT': None})
    harness.expect(result, True)
    assert result.stdout == lanes, result.stdout


def test_lane_outside_test_or_example_is_refused(root):
    build = root / LIBRARY / 'build.jam'
    build.write_text(build.read_text() + '\n'
                     'import webcpp ;\n'
                     'webcpp.lane oracle_demo : oracle_demo ;\n')
    result = harness.run_b2(root, '-d0', 'declared-lanes')
    harness.expect(result, False, 'webcpp.lane is declared in', 'libs/oracle_demo/build.jam',
                   'test or an example Jamfile')


def test_b2_test_runs_no_node(root):
    environment = without(root, 'node', 'npm')
    # The examples' outputs, which the twins are compared with, are the programs' own.
    result = harness.run_b2(root, '-a', f'{LIBRARY}/test', f'{LIBRARY}/example',
                            env_extra=environment)
    harness.expect(result, True, '**passed**')
    for name in ('square', 'half', 'compile_time'):
        assert f'{name}.output' in result.stdout, (name, result.stdout[-4000:])
    assert '...failed' not in result.stdout, result.stdout[-4000:]
    result = harness.run_b2(root, '-d0', 'declared-lanes', env_extra=environment)
    harness.expect(result, True)
    assert result.stdout == ORACLE_LANE, result.stdout
    result = harness.run_b2(root, '-d0', 'declared-targets', env_extra=environment)
    harness.expect(result, True)
    assert result.stdout == 'oracle_demo native\n', result.stdout


def test_missing_node_or_npm_names_it(root):
    for tools, missing in ((('node', 'npm'), 'node'), (('npm',), 'npm')):
        result = harness.run_b2(root, '-a', LANE, env_extra=without(root, *tools))
        harness.expect(result, False, f'{missing} is not on PATH')
        shutil.rmtree(root / 'without tools')
    for target in (UPDATE, f'{ORACLE}//twins', f'{ORACLE}//cases-squares'):
        result = harness.run_b2(root, '-a', target, env_extra=without(root, 'node', 'npm'))
        harness.expect(result, False, 'node is not on PATH')
        shutil.rmtree(root / 'without tools')


def test_missing_lockfile_names_it(root):
    for name in ('package-lock.json', 'package.json'):
        path = root / ORACLE / name
        text = path.read_bytes()
        path.unlink()
        result = harness.run_b2(root, '-a', LANE)
        harness.expect(result, False, f'{ORACLE}/{name}', 'does not exist')
        path.write_bytes(text)


def test_rules_in_their_order(root):
    jamfile = root / ORACLE / 'Jamfile'
    text = jamfile.read_text()
    for wrong, message in (
        (text.replace('webcpp.original node --conditions=development ;\n', ''),
         'webcpp.twins: webcpp.original must come first'),
        (text + 'webcpp.original node ;\n', 'webcpp.original is called twice'),
        (text + 'webcpp.twins ../../example : twins : .js ;\n', 'webcpp.twins is called twice'),
        (text + 'webcpp.cases squares : cases.mjs : ../fixtures/cases : ../fixtures/expected ;\n',
         'webcpp.cases squares is declared twice'),
    ):
        jamfile.write_text(wrong)
        result = harness.run_b2(root, '-a', LANE)
        harness.expect(result, False, message)
        assert f'{ORACLE}/Jamfile:' in result.stdout, result.stdout[-4000:]


CASES = [
    test_lane_runs_twins_and_cases_green,
    test_twin_difference_fails_the_lane,
    test_case_difference_fails_the_lane,
    test_update_expected_rewrites_cases,
    test_update_expected_refuses_agreeing_twin,
    test_failing_script_leaves_update_red,
    test_declared_lanes_lists_the_oracle,
    test_lane_outside_test_or_example_is_refused,
    test_b2_test_runs_no_node,
    test_missing_node_or_npm_names_it,
    test_missing_lockfile_names_it,
    test_rules_in_their_order,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('oracle_jam_test', CASES, sys.argv[1:], fixtures=('oracle_demo',)))
