#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/oracle/oracle.jam and webcpp.lane: a library's oracle lane runs its twins and its
cases on the original and fails naming a difference; update-expected rewrites what the original
writes, refuses an own output that agrees, and stays red when the original fails; `b2
declared-lanes` lists the lanes the libraries declare; a library declares its twins once; and only
an oracle target needs Node. Each case builds a scratch superproject with the fixture library
oracle_demo. Run with the names of some cases to run only those."""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import harness

LIBRARY = 'libs/oracle_demo'
ORACLE = f'{LIBRARY}/test/oracle'
LANE = f'{ORACLE}//oracle'
UPDATE = f'{ORACLE}//update-expected'

# What a lane line of `b2 declared-lanes` says for the fixture: a lane of the kind original, since
# it runs the original's cases and twins.
ORACLE_LANE = 'oracle_demo oracle libs/oracle_demo/test/oracle original\n'

PLAIN_SOURCE = 'int main() { return 0; }\n'

# The line b2 prints when it runs npm ci.
NPM_CI = re.compile(r'^npm-ci ', re.MULTILINE)


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
    own.write_text('Half of 7 is 4.\n')
    (expected / 'three.json').unlink()
    # A file the original does not write goes: the directory is written again whole.
    (expected / 'stale.json').write_text('{}\n')
    result = harness.run_b2(root, '-a', UPDATE)
    harness.expect(result, True)
    after = {path.name: path.read_bytes() for path in expected.iterdir()}
    assert after == before, (sorted(after), sorted(before))
    # The divergent twin's own output is written again from the original.
    assert own.read_bytes() == own_before, own.read_text()
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


def test_npm_ci_runs_again_only_when_the_lockfile_changes(root):
    result = harness.run_b2(root, LANE)
    harness.expect(result, True)
    assert NPM_CI.search(result.stdout), result.stdout[-4000:]
    result = harness.run_b2(root, LANE)
    harness.expect(result, True)
    assert not NPM_CI.search(result.stdout), result.stdout[-4000:]
    # A lockfile newer than the stamp the install left runs the install again, which finds the
    # packages of that lockfile installed already, under .node-modules/, and keeps them.
    oracle = root / ORACLE
    installs = sorted((oracle / '.node-modules').iterdir())
    stamps = sorted((root / 'bin').rglob('node-modules.stamp'))
    assert len(stamps) == 1, stamps
    lockfile = oracle / 'package-lock.json'
    later = stamps[0].stat().st_mtime + 10
    os.utime(lockfile, (later, later))
    result = harness.run_b2(root, LANE)
    harness.expect(result, True)
    assert NPM_CI.search(result.stdout), result.stdout[-4000:]
    assert sorted((oracle / '.node-modules').iterdir()) == installs, installs
    # A package.json or lockfile whose content changed installs anew, and the old install stays
    # as the previous one, for a build that may still read it.
    harness.replace(oracle / 'package.json', 'with no dependency.', 'with no dependency at all.')
    os.utime(lockfile, (later + 10, later + 10))
    result = harness.run_b2(root, LANE)
    harness.expect(result, True)
    [lock, old] = installs
    previous = oracle / '.node-modules/.previous'
    assert previous.read_text() == f'{old.name}\n', previous.read_text()
    [new] = sorted(set((oracle / '.node-modules').iterdir()) - {lock, old, previous})
    assert (oracle / 'node_modules').resolve().parent == new.resolve(), new


# A stand-in for npm, first on PATH, that does what npm ci does to the directory it runs in,
# slowly: it removes node_modules, waits a second, and makes it again with the package the
# lockfile pins, failing, as npm ci does with ENOTEMPTY, when another made it meanwhile; it counts
# its runs in the file NPM_RUNS names.
SLOW_NPM = """#!{python}
import os
import shutil
import sys
import time
from pathlib import Path

assert sys.argv[1] == 'ci', sys.argv
with open(os.environ['NPM_RUNS'], 'a') as runs:
    runs.write(os.getcwd() + '\\n')
shutil.rmtree('node_modules', ignore_errors=True)
time.sleep(1)
try:
    Path('node_modules/pinned').mkdir(parents=True)
except FileExistsError:
    print('npm error code ENOTEMPTY')
    sys.exit(1)
"""


def test_installs_at_once_share_the_packages(root):
    # Two b2 runs at once that each install the original's packages, as two lanes started
    # together do, each in a build directory of its own: neither fails, npm ci runs once for
    # the lockfile, and the packages are linked at node_modules from .node-modules/.
    tools = root / 'slow tools'
    tools.mkdir()
    (tools / 'npm').write_text(SLOW_NPM.format(python=sys.executable))
    (tools / 'npm').chmod(0o755)
    environment = {'PATH': f'{tools}{os.pathsep}{os.environ["PATH"]}',
                   'NPM_RUNS': str(root / 'npm runs')}
    for round in range(3):
        ended = harness.run_lanes(root, {
            name: ('-a', f'--build-dir=bin/install-{round}-{name}', f'{ORACLE}//node-modules')
            for name in ('a', 'b')}, env_extra=environment)
        for name, result in ended.items():
            assert result.returncode == 0, (round, name, result.stdout[-4000:])
        assert len(ended) == 2, ended
    assert len((root / 'npm runs').read_text().splitlines()) == 1, (root / 'npm runs').read_text()
    oracle = root / ORACLE
    installs = sorted(path.name for path in (oracle / '.node-modules').iterdir())
    assert len(installs) == 2 and installs[0] == '.lock', installs
    assert (oracle / 'node_modules').is_symlink(), oracle / 'node_modules'
    assert (oracle / 'node_modules/pinned').is_dir(), oracle / 'node_modules'


def test_expected_directory_is_guarded(root):
    jamfile = root / ORACLE / 'Jamfile'
    line = 'webcpp.cases squares : cases.mjs : ../fixtures/cases : ../fixtures/expected ;\n'
    holds_oracle = ('the directory of the oracle, or one that holds it, which update-expected '
                    'removes')
    overlaps = 'is the cases directory, holds it or is inside it, and update-expected removes it'
    for cases, expected, directory, message in (
        ('../fixtures/cases', '.', ORACLE, holds_oracle),
        ('../fixtures/cases', '..', f'{LIBRARY}/test', holds_oracle),
        ('../fixtures/cases', '../fixtures/cases', f'{LIBRARY}/test/fixtures/cases', overlaps),
        ('../fixtures/cases', '../fixtures', f'{LIBRARY}/test/fixtures', overlaps),
        ('../fixtures/cases', '../fixtures/cases/out', f'{LIBRARY}/test/fixtures/cases/out',
         overlaps),
        ('../fixtures/missing', '../fixtures/expected', f'{LIBRARY}/test/fixtures/missing',
         'does not exist'),
    ):
        declared = f'webcpp.cases squares : cases.mjs : {cases} : {expected} ;\n'
        harness.replace(jamfile, line, declared)
        result = harness.run_b2(root, '-d0', 'declared-lanes')
        harness.expect(result, False, f'webcpp.cases squares: {directory} ', message,
                       f'{ORACLE}/Jamfile')
        harness.replace(jamfile, declared, line)
    # Nothing was removed.
    assert sorted(path.name for path in (root / LIBRARY / 'test/fixtures/expected').iterdir()) == [
        'seven.json', 'three.json']


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
    lanes = ('alpha browser libs/alpha/example/browser programs\n'
             'alpha http libs/alpha/test programs\n' + ORACLE_LANE)
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


def test_twins_declared_once_per_library(root):
    # A library's page shows one set of twins, and counts it: a second oracle Jamfile that
    # declares twins is refused as it loads.
    second = root / LIBRARY / 'test/second'
    second.mkdir()
    for name in ('package.json', 'package-lock.json'):
        shutil.copy2(root / ORACLE / name, second / name)
    (second / 'Jamfile').write_text('import webcpp ;\n'
                                    '\n'
                                    'webcpp.original node ;\n'
                                    'webcpp.twins ../../example : ../oracle/twins : .mjs ;\n')
    result = harness.run_b2(root, '-d0', 'declared-lanes')
    harness.expect(result, False, 'webcpp.twins is declared for oracle_demo in',
                   f'{LIBRARY}/test/second/Jamfile', f'{ORACLE}/Jamfile', 'already',
                   'one set of twins')


CASES = [
    test_lane_runs_twins_and_cases_green,
    test_twin_difference_fails_the_lane,
    test_case_difference_fails_the_lane,
    test_update_expected_rewrites_cases,
    test_update_expected_refuses_agreeing_twin,
    test_npm_ci_runs_again_only_when_the_lockfile_changes,
    test_installs_at_once_share_the_packages,
    test_expected_directory_is_guarded,
    test_failing_script_leaves_update_red,
    test_declared_lanes_lists_the_oracle,
    test_lane_outside_test_or_example_is_refused,
    test_b2_test_runs_no_node,
    test_missing_node_or_npm_names_it,
    test_missing_lockfile_names_it,
    test_rules_in_their_order,
    test_twins_declared_once_per_library,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('oracle_jam_test', CASES, sys.argv[1:], fixtures=('oracle_demo',)))
