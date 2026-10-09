#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/ci/matrix.py: the plan has a lane per compiler for each target the libraries
declare, emscripten's among them, with the libraries that declare it, and fails on a target the CI
has no lane for or a library that does not exist; the own lanes the libraries declare are listed,
of every library or of one, once per target an own lane runs on, emscripten included, and as
before for one that names none, and a library that does not exist, a line of b2's that is no own
lane or an own lane on a target the CI cannot set up fails; a lane is named and registered by the
compiler's version when the image decides it, a WASI lane by the lines of tools/ci/wasi-sdk.jam,
its wasi-sdk directory one word of Jam, and the emscripten lane by the lines of
tools/ci/emsdk.jam, its emsdk directory and its node one word of Jam each; a lane runs the lane
command and writes its XML, emscripten's under node, and fails when b2 cannot build; an own lane
runs as the lane it shares does, and writes its XML under its own name; the report merges the
lanes and the own lanes on a target and fails, by name, a planned lane that wrote nothing. Each
case runs the scratch superproject's own copy of matrix.py, with the fixture library demo, and
browser_demo where it says so. Run with the names of some cases to run only those."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

# The harness lives beside the other tests of the build, in tools/test.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'test'))

import harness
import matrix

NATIVE = ['gcc-14', 'gcc-15', 'clang-18', 'clang-22', 'apple-clang', 'msvc-14.3', 'msvc-14.5']


def run(root: Path, *arguments: str,
        github_output: Path | None = None) -> subprocess.CompletedProcess:
    """Runs root's matrix.py in the environment the harness gives b2, Emscripten's cache the
    run's own, and with GITHUB_OUTPUT set to github_output when it is given."""
    environment = harness.b2_environment()
    environment.pop('GITHUB_OUTPUT', None)
    if github_output is not None:
        environment['GITHUB_OUTPUT'] = str(github_output)
    return subprocess.run([sys.executable, str(root / 'tools/ci/matrix.py'), *arguments],
                          cwd=root, env=environment, capture_output=True, text=True,
                          check=False, timeout=harness.TIMEOUT)


def planned(root: Path, *arguments: str) -> list[dict]:
    result = run(root, 'plan', *arguments)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    lines = result.stdout.splitlines()
    assert len(lines) == 1, lines
    return json.loads(lines[0])['include']


def test_the_targets_are_spelled_once(_):
    # The CI's targets are the report's, lanes.py's TARGETS, which the name of an own lane begins
    # with: a target added there is known to both.
    import lanes
    assert matrix.TARGETS is lanes.TARGETS, (matrix.TARGETS, lanes.TARGETS)
    patched = (*lanes.TARGETS, 'wasip9')
    assert lanes.own_lane_name(patched).fullmatch('wasip9.demo.http')
    assert not lanes.own_lane_name(lanes.TARGETS).fullmatch('wasip9.demo.http')
    assert lanes.OWN_LANE.pattern == lanes.own_lane_name(lanes.TARGETS).pattern


def test_plan_of_one_library(root):
    lanes = planned(root, '--library', 'demo')
    assert [lane['id'] for lane in lanes] == NATIVE + ['wasip2', 'wasip3'], lanes
    for lane in lanes:
        assert lane['projects'] == ['libs/demo/test', 'libs/demo/example'], lane
    by_id = {lane['id']: lane for lane in lanes}
    # Named after the directory b2 builds them in, which the report checks.
    assert [by_id[name]['lane'] for name in NATIVE] == [
        'gcc-14', 'gcc-15', 'clang-linux-18', 'clang-linux-22', 'clang-darwin-{version}',
        'msvc-14.3', 'msvc-14.5'], lanes
    assert by_id['apple-clang']['detect'] == 'clang++', by_id['apple-clang']
    assert by_id['wasip2']['toolset'] == 'clang-wasip2', by_id['wasip2']
    assert by_id['wasip3']['options'] == ['testing.launcher=wasmtime'], by_id['wasip3']
    assert by_id['wasip3']['wasm'] and not by_id['gcc-14']['wasm'], lanes
    assert by_id['msvc-14.5']['os'] == 'windows-2025', by_id['msvc-14.5']
    assert by_id['clang-22']['os'] == 'ubuntu-26.04', by_id['clang-22']


def test_plan_with_no_toolset_configured(root):
    # The plan job's user-config.jam holds the `using boost` line alone, as the Boost action
    # writes it, and b2 then warns on its standard output that it configures a default toolset.
    boost_only(root)
    assert [lane['id'] for lane in planned(root, '--library', 'demo')] == NATIVE + [
        'wasip2', 'wasip3']


def test_plan_of_every_library(root):
    harness.add_library(root, 'plain',
                        'import webcpp ;\nwebcpp.targets native ;\n'
                        'webcpp.run pass : pass.cpp ;\n',
                        {'pass.cpp': 'int main() {}\n'})
    lanes = planned(root)
    by_id = {lane['id']: lane for lane in lanes}
    both = ['libs/demo/test', 'libs/demo/example', 'libs/plain/test', 'libs/plain/example']
    for name in NATIVE:
        assert by_id[name]['projects'] == both, by_id[name]
    # Only demo declares the wasm targets, so their lanes build only demo.
    assert by_id['wasip2']['projects'] == ['libs/demo/test', 'libs/demo/example'], lanes
    # A library alone gets the lanes of its own targets, and no other.
    assert [lane['id'] for lane in planned(root, '--library', 'plain')] == NATIVE


# The emscripten lane, as the plan writes it for a library that declares emscripten.
EMSCRIPTEN_LANE = {'id': 'emscripten', 'name': 'Emscripten 6.0.11 (node)', 'os': 'ubuntu-24.04',
                   'target': 'emscripten', 'lane': 'emscripten', 'toolset': 'emscripten',
                   'using': '{emsdk.jam}', 'detect': '', 'options': [], 'wasm': False,
                   'emsdk': True, 'node': True}


def test_plan_of_a_library_on_emscripten(root):
    # browser_demo declares native and emscripten: its native lanes, and the emscripten lane,
    # which needs emsdk and Node, and neither wasi-sdk nor a launcher.
    shutil.copytree(harness.FIXTURES / 'browser_demo', root / 'libs/browser_demo',
                    ignore=harness.built)
    boost_only(root)
    lanes = planned(root, '--library', 'browser_demo')
    assert [lane['id'] for lane in lanes] == NATIVE + ['emscripten'], lanes
    emscripten = lanes[-1]
    projects = emscripten.pop('projects')
    assert projects == ['libs/browser_demo/test', 'libs/browser_demo/example'], projects
    assert emscripten == EMSCRIPTEN_LANE, emscripten
    assert not any(lane['emsdk'] or lane['node'] for lane in lanes[:-1]), lanes
    # Every library's plan has it once, for the libraries that declare emscripten alone.
    by_id = {lane['id']: lane for lane in planned(root)}
    assert by_id['emscripten']['projects'] == projects, by_id['emscripten']
    assert by_id['wasip2']['projects'] == ['libs/demo/test', 'libs/demo/example'], by_id
    assert not by_id['wasip2']['emsdk'], by_id['wasip2']


def test_a_target_without_a_lane_fails(_):
    # Every target has a lane today; one added to the report's TARGETS before the CI has a lane
    # for it fails the plan by name, rather than leave it untested.
    pairs = [('browser', 'emscripten'), ('demo', 'native')]
    original = matrix.LANES
    matrix.LANES = tuple(lane for lane in original if lane.target != 'emscripten')
    try:
        matrix.plan(pairs, None)
    except matrix.Failure as failure:
        assert failure.status == 2, failure.status
        assert str(failure) == ('browser declare emscripten, which the CI has no lane for: a '
                                'target is never left untested'), failure
    else:
        raise AssertionError('a target without a lane was planned')
    finally:
        matrix.LANES = original
    assert [lane.id for lane in matrix.plan(pairs, None)] == NATIVE + ['emscripten']


def test_an_unknown_library_fails(root):
    result = run(root, 'plan', '--library', 'nothing')
    assert result.returncode == 2, (result.returncode, result.stderr)
    assert 'libs/nothing declares no target, or is no library' in result.stderr, result.stderr


def own_lanes(root: Path, *arguments: str) -> list[dict]:
    result = run(root, 'own-lanes', *arguments)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    lines = result.stdout.splitlines()
    assert len(lines) == 1, lines
    return json.loads(lines[0])['include']


def test_own_lanes_of_every_library_and_of_one(root):
    # demo declares no lane of its own, as xactor does not: its matrix is empty, and the CI then
    # runs no own-lane job.
    boost_only(root)
    assert own_lanes(root) == []
    assert run(root, 'own-lanes', '--library', 'demo').stdout == '{"include":[]}\n'
    harness.add_library(root, 'alpha',
                        'import webcpp ;\n'
                        'webcpp.run plain : plain.cpp ;\n'
                        'webcpp.lane http : plain ;\n',
                        {'plain.cpp': 'int main() {}\n'})
    (root / 'libs/alpha/example/browser').mkdir(parents=True)
    (root / 'libs/alpha/example/browser/Jamfile').write_text(
        'import webcpp ;\n'
        'webcpp.example page.cpp ;\n'
        'webcpp.lane browser : page.output ;\n')
    harness.add_library(root, 'beta', 'import webcpp ;\n', {})
    (root / 'libs/beta/test/oracle').mkdir()
    (root / 'libs/beta/test/oracle/Jamfile').write_text(
        'import webcpp ;\n'
        'alias twins ;\n'
        'webcpp.lane oracle : twins ;\n')
    # Every entry names its job and its image, which the job reads from here alone.
    alpha = [{'library': 'alpha', 'lane': 'browser', 'directories': ['libs/alpha/example/browser'],
              'name': 'Own lane (alpha, browser)', 'os': 'ubuntu-24.04', 'wasm': False,
              'emsdk': False, 'node': True},
             {'library': 'alpha', 'lane': 'http', 'directories': ['libs/alpha/test'],
              'name': 'Own lane (alpha, http)', 'os': 'ubuntu-24.04', 'wasm': False,
              'emsdk': False, 'node': True}]
    beta = [{'library': 'beta', 'lane': 'oracle', 'directories': ['libs/beta/test/oracle'],
             'name': 'Own lane (beta, oracle)', 'os': 'ubuntu-24.04', 'wasm': False,
             'emsdk': False, 'node': True}]
    assert own_lanes(root) == alpha + beta
    assert own_lanes(root, '--library', 'beta') == beta
    assert own_lanes(root, '--library', 'demo') == []
    # A library that does not exist is no library without own lanes: it fails as the plan's
    # --library does, by name, and prints no matrix.
    result = run(root, 'own-lanes', '--library', 'nothing')
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    assert 'libs/nothing is no library of libs/' in result.stderr, result.stderr
    assert result.stdout == '', result.stdout
    # What the job runs, b2 -a <directory>//<lane>, is built from these words alone: a line that
    # is not three of them, or whose directory is not the library's, fails the listing.
    for printed, named in (('alpha http', 'not "<library> <lane> <directory> [<target>]"'),
                           ('alpha http libs/beta/test', 'not in libs/alpha/test or'),
                           ('alpha http; libs/alpha/test',
                            'not "<library> <lane> <directory> [<target>]"'),
                           ('alpha http libs/alpha/test wasm', 'wasm is not a target'),
                           ('alpha http libs/alpha/test wasip2 wasip3',
                            'not "<library> <lane> <directory> [<target>]"')):
        try:
            matrix.parsed_own_lanes(printed)
        except matrix.Failure as failure:
            assert named in str(failure), (printed, failure)
        else:
            raise AssertionError(f'{printed!r} was read as an own lane')


def test_own_lanes_on_targets(root):
    # A lane that names targets is an entry per target, one job, which runs it in every directory
    # of the library that declares it there, and says what the job sets up and the name of the
    # XML it writes: <target>.<library>.<lane>.
    boost_only(root)
    harness.add_library(root, 'alpha',
                        'import webcpp ;\n'
                        'webcpp.targets native wasip2 wasip3 ;\n'
                        'webcpp.run plain : plain.cpp ;\n'
                        'webcpp.lane http : plain : wasip3 wasip2 ;\n',
                        {'plain.cpp': 'int main() {}\n'})
    (root / 'libs/alpha/example').mkdir()
    (root / 'libs/alpha/example/Jamfile').write_text(
        'import webcpp ;\n'
        'webcpp.targets native wasip2 ;\n'
        'webcpp.example page.cpp ;\n'
        'webcpp.lane http : page.output : native wasip2 ;\n')
    harness.add_library(root, 'beta', 'import webcpp ;\n', {})
    (root / 'libs/beta/test/oracle').mkdir()
    (root / 'libs/beta/test/oracle/Jamfile').write_text(
        'import webcpp ;\n'
        'alias twins ;\n'
        'webcpp.lane oracle : twins ;\n')
    alpha = [{'library': 'alpha', 'lane': 'http', 'directories': ['libs/alpha/example'],
              'platform': 'native', 'id': 'native.alpha.http', 'name': 'Own lane (alpha, http, '
              'native)', 'os': 'ubuntu-24.04', 'wasm': False, 'emsdk': False, 'node': True},
             {'library': 'alpha', 'lane': 'http',
              'directories': ['libs/alpha/example', 'libs/alpha/test'], 'platform': 'wasip2',
              'id': 'wasip2.alpha.http', 'name': 'Own lane (alpha, http, wasip2)',
              'os': 'ubuntu-24.04', 'wasm': True, 'emsdk': False, 'node': True},
             {'library': 'alpha', 'lane': 'http', 'directories': ['libs/alpha/test'],
              'platform': 'wasip3', 'id': 'wasip3.alpha.http', 'name': 'Own lane (alpha, http, '
              'wasip3)', 'os': 'ubuntu-24.04', 'wasm': True, 'emsdk': False, 'node': True}]
    beta = {'library': 'beta', 'lane': 'oracle', 'directories': ['libs/beta/test/oracle'],
            'name': 'Own lane (beta, oracle)', 'os': 'ubuntu-24.04', 'wasm': False,
            'emsdk': False, 'node': True}
    assert own_lanes(root) == [*alpha, beta]
    assert own_lanes(root, '--library', 'alpha') == alpha
    assert run(root, 'own-lanes', '--library', 'beta').stdout == (
        '{"include":[{"library":"beta","lane":"oracle","directories":["libs/beta/test/oracle"],'
        '"name":"Own lane (beta, oracle)","os":"ubuntu-24.04","wasm":false,"emsdk":false,'
        '"node":true}]}\n')
    # Each entry is read back as the lane it is, and runs in each of its directories.
    for entry in alpha:
        own = matrix.parsed_own_lane(json.dumps(entry))
        assert own_lane_entry_of(own) == entry, (own, entry)
        assert own.requests == [f'{directory}//http' for directory in entry['directories']]
    # Every own lane has Node, the version the CI pins, whatever its target: an oracle runs npm
    # and its original under node, and a driven test its driver, natively too (webcpp.drive).
    assert all(entry['node'] for entry in own_lanes(root)), own_lanes(root)
    # An own lane on emscripten shares the emscripten lane's setup: emsdk and Node.
    harness.add_library(root, 'gamma',
                        'import webcpp ;\n'
                        'webcpp.targets emscripten ;\n'
                        'webcpp.run plain : plain.cpp ;\n'
                        'webcpp.lane browser : plain : emscripten ;\n',
                        {'plain.cpp': 'int main() {}\n'})
    gamma = {'library': 'gamma', 'lane': 'browser', 'directories': ['libs/gamma/test'],
             'platform': 'emscripten', 'id': 'emscripten.gamma.browser',
             'name': 'Own lane (gamma, browser, emscripten)', 'os': 'ubuntu-24.04', 'wasm': False,
             'emsdk': True, 'node': True}
    assert own_lanes(root) == [*alpha, beta, gamma]
    assert own_lanes(root, '--library', 'gamma') == [gamma]
    own = matrix.parsed_own_lane(json.dumps(gamma))
    assert own_lane_entry_of(own) == gamma, (own, gamma)
    # A target the job cannot set up fails the listing by name, rather than run natively; every
    # target has a lane today, so the case is made by leaving emscripten's out.
    original = matrix.OWN_LANE_BASES
    matrix.OWN_LANE_BASES = {target: lane for target, lane in original.items()
                             if target != 'emscripten'}
    try:
        matrix.own_lane_base('emscripten')
    except matrix.Failure as failure:
        assert failure.status == 2, failure.status
        assert str(failure) == ('an own lane on emscripten needs a lane of that target to share '
                                'its setup with, and the CI has none'), failure
    else:
        raise AssertionError('an own lane was set up on a target without a lane')
    finally:
        matrix.OWN_LANE_BASES = original


def own_lane_entry_of(own: matrix.OwnLane) -> dict:
    """The entry of the own-lanes matrix of own, as own-lanes prints it."""
    return json.loads(json.dumps(matrix.own_lane_entry(own)))


def test_an_own_lanes_command(root):
    config = root / 'config.jam'
    oracle = matrix.parsed_own_lanes('beta oracle libs/beta/test/oracle')[0]
    # Without a target, as an oracle runs: Clang 18, from scratch, its exit status the verdict.
    assert matrix.own_lane_command(oracle, config, None, ['--build-dir=bin/x']) == [
        'b2', f'--user-config={config}', '-a', 'toolset=clang-18', '--build-dir=bin/x',
        'libs/beta/test/oracle//oracle']
    # On a target, as that target's lane runs: its toolset and options, and the XML the report
    # reads; in each directory that declares it there.
    served = matrix.parsed_own_lanes('alpha http libs/alpha/test wasip2\n'
                                     'alpha http libs/alpha/example wasip2')
    assert len(served) == 1, served
    xml = Path('bin/ci/wasip2.alpha.http.xml')
    assert matrix.own_lane_command(served[0], config, xml, []) == [
        'b2', f'--user-config={config}', '-a', '--dump-tests', f'--out-xml={xml}',
        'toolset=clang-wasip2', 'testing.launcher=wasmtime', 'libs/alpha/example//http',
        'libs/alpha/test//http']
    # On emscripten, as the emscripten lane runs: its toolset, and no launcher.
    driven = matrix.parsed_own_lanes('alpha driver libs/alpha/test/driver emscripten')
    xml = Path('bin/ci/emscripten.alpha.driver.xml')
    assert matrix.own_lane_command(driven[0], config, xml, []) == [
        'b2', f'--user-config={config}', '-a', '--dump-tests', f'--out-xml={xml}',
        'toolset=emscripten', 'libs/alpha/test/driver//driver']
    # The lane the job sets up for each target runs on the own-lanes job's image, and the native
    # one is the oracle's Clang 18.
    for target, lane_id in (('native', 'clang-18'), ('wasip2', 'wasip2'), ('wasip3', 'wasip3'),
                            ('emscripten', 'emscripten')):
        lane = matrix.own_lane_base(target)
        assert (lane.id, lane.os) == (lane_id, 'ubuntu-24.04'), lane


def test_an_own_lane_on_a_target_writes_its_xml_and_the_report_merges_it(root):
    jamfile = root / 'libs/demo/test/Jamfile'
    jamfile.write_text(jamfile.read_text() + 'webcpp.lane served : pass : wasip2 ;\n')
    config = boost_only(root)
    # wasi-sdk where the CI's action installs it, which the lane's toolset is registered against.
    (root / '.local/wasi-sdk').symlink_to((matrix.ROOT / '.local/wasi-sdk').resolve())
    entry = own_lanes(root, '--library', 'demo')
    assert [lane['id'] for lane in entry] == ['wasip2.demo.served'], entry
    output = root / 'github-output'
    output.write_text('')
    result = run(root, 'own-lane', json.dumps(entry[0]), '--', '--build-dir=bin/own',
                 github_output=output)
    assert result.returncode == 0, (result.returncode, result.stdout[-4000:], result.stderr)
    xml = root.resolve() / 'bin/ci/wasip2.demo.served.xml'
    printed = (f'own lane wasip2.demo.served: b2 '
               f'{shlex.quote(f"--user-config={config.resolve()}")} -a --dump-tests '
               f'{shlex.quote(f"--out-xml={xml}")} toolset=clang-wasip2 '
               'testing.launcher=wasmtime --build-dir=bin/own libs/demo/test//served\n')
    assert result.stdout.startswith(printed), (printed, result.stdout[:2000])
    assert output.read_text().splitlines() == ['lane=wasip2.demo.served',
                                               f'xml={xml.as_posix()}'], output.read_text()
    lanes = root / 'downloaded'
    (lanes / 'lane-wasip2.demo.served').mkdir(parents=True)
    xml.rename(lanes / 'lane-wasip2.demo.served' / xml.name)
    own = json.dumps({'include': entry})
    report = run(root, 'report', '--plan', '{"include":[]}', '--own-lanes', own, '--lanes',
                 str(lanes), '--out', str(root / 'report'))
    # The lane is a column of the matrix under its own name, and its test passed there.
    assert report.returncode == 0, (report.returncode, report.stdout, report.stderr)
    page = (root / 'report/demo.html').read_text()
    assert 'data-lane="wasip2.demo.served"' in page, page[:2000]
    # An own lane on a target that wrote no XML fails the report by name, as a lane does.
    (lanes / 'lane-wasip2.demo.served' / xml.name).unlink()
    report = run(root, 'report', '--plan', '{"include":[]}', '--own-lanes', own, '--lanes',
                 str(lanes), '--out', str(root / 'report-missing'))
    assert report.returncode == 2, (report.returncode, report.stdout, report.stderr)
    assert ('the lane wasip2.demo.served (Own lane (demo, served, wasip2)) wrote no XML') in (
        report.stderr), report.stderr


def test_an_own_lanes_failing_served_test_fails_the_report(root):
    # An own lane whose served test answers other than its transcript writes its XML as one that
    # passes does, b2 exiting 0, and the report fails, naming the test under the lane's id, as a
    # run failure.
    shutil.copytree(harness.FIXTURES / 'component_demo', root / 'libs/component_demo',
                    ignore=harness.built)
    harness.link_wasi_tools(root)
    jamfile = root / 'libs/component_demo/test/Jamfile'
    jamfile.write_text(jamfile.read_text() + 'webcpp.lane served : answers : wasip2 wasip3 ;\n')
    harness.replace(root / 'libs/component_demo/test/answers.expected', 'HTTP/1.1 404 Not Found',
                    'HTTP/1.1 405 Method Not Allowed')
    boost_only(root)
    entry = [lane for lane in own_lanes(root, '--library', 'component_demo')
             if lane.get('id') == 'wasip2.component_demo.served']
    assert len(entry) == 1, own_lanes(root, '--library', 'component_demo')
    result = run(root, 'own-lane', json.dumps(entry[0]), '--', '--build-dir=bin/own')
    assert result.returncode == 0, (result.returncode, result.stdout[-4000:], result.stderr)
    lanes = root / 'downloaded' / 'lane-wasip2.component_demo.served'
    lanes.mkdir(parents=True)
    xml = root.resolve() / 'bin/ci/wasip2.component_demo.served.xml'
    xml.rename(lanes / xml.name)
    report = run(root, 'report', '--plan', '{"include":[]}', '--own-lanes',
                 json.dumps({'include': entry}), '--lanes', str(lanes.parent), '--out',
                 str(root / 'report'))
    assert report.returncode == 1, (report.returncode, report.stdout, report.stderr)
    assert 'report: wasip2.component_demo.served: component_demo/answers: run' in (
        report.stderr), report.stderr


def test_a_lane_is_named_by_the_compiler_version(root):
    compiler = root / 'fake clang++'
    compiler.write_text('#!/bin/sh\necho 17.0.0\n')
    compiler.chmod(compiler.stat().st_mode | stat.S_IXUSR)
    apple = next(lane for lane in matrix.LANES if lane.id == 'apple-clang')
    lane = matrix.resolved(matrix.replace(apple, detect=str(compiler)))
    assert (lane.lane, lane.toolset) == ('clang-darwin-17', 'clang-17'), lane
    assert lane.using == 'using clang : 17 : clang++ ;', lane.using
    wasip2 = matrix.resolved(next(lane for lane in matrix.LANES if lane.id == 'wasip2'))
    assert f'using clang : wasip2 : "{matrix.ROOT.as_posix()}/.local/wasi-sdk"/bin/clang++\n' in (
        wasip2.using), wasip2.using
    emscripten = matrix.resolved(next(lane for lane in matrix.LANES if lane.id == 'emscripten'))
    assert (emscripten.lane, emscripten.toolset) == ('emscripten', 'emscripten'), emscripten
    assert (f'using emscripten : : "{matrix.ROOT.as_posix()}/.local/emsdk"/upstream/emscripten/'
            f'em++ : <nodejs>"{matrix.ROOT.as_posix()}/.local/emscripten/node" ;') in (
                emscripten.using.splitlines()), emscripten.using
    # Registered once, after what the file holds.
    config = root / 'config.jam'
    config.write_text('using boost : 1.92 ;')
    matrix.register(lane, config)
    matrix.register(lane, config)
    assert config.read_text() == 'using boost : 1.92 ;\nusing clang : 17 : clang++ ;\n', (
        config.read_text())
    command = matrix.lane_command(matrix.replace(lane, projects=('libs/x/test',)), config,
                                  Path('bin/ci/clang-darwin-17.xml'), ['--build-dir=bin/lane'])
    assert command == ['b2', f'--user-config={config}', '-a', '--dump-tests',
                       '--out-xml=bin/ci/clang-darwin-17.xml', 'toolset=clang-17',
                       '--build-dir=bin/lane', 'libs/x/test'], command
    broken = root / 'broken'
    broken.write_text('#!/bin/sh\nexit 3\n')
    broken.chmod(broken.stat().st_mode | stat.S_IXUSR)
    try:
        matrix.resolved(matrix.replace(apple, detect=str(broken)))
    except matrix.Failure as failure:
        assert 'no version to name the lane by' in str(failure), failure
    else:
        raise AssertionError('a compiler without a version named a lane')


def test_abbreviated_paths_keep_the_lane_name(root):
    # The MSVC lanes pass --abbreviate-paths, against Windows's MAX_PATH, and b2 then abbreviates
    # each word of the toolset directory (clang-darwin-21 is clng-drwn-21): the lane's name must
    # be what b2 makes of it, or the report refuses the lane.
    abbreviating = [lane for lane in matrix.LANES if '--abbreviate-paths' in lane.options]
    assert [lane.id for lane in abbreviating] == ['msvc-14.3', 'msvc-14.5'], abbreviating
    names = [lane.lane for lane in abbreviating]
    (root / 'probe').mkdir()
    (root / 'probe/Jamroot').write_text(
        'import string ;\n'
        f'for local name in {" ".join(names)}\n'
        '{\n'
        '    local words ;\n'
        '    for local word in [ MATCH "^([^-]*)-(.*)$" : $(name) ]\n'
        '    {\n'
        '        words += [ string.abbreviate $(word) ] ;\n'
        '    }\n'
        '    ECHO "abbreviated $(name) $(words:J=-)" ;\n'
        '}\n')
    result = subprocess.run(['b2', '-n'], cwd=root / 'probe', capture_output=True, text=True,
                            check=False)
    found = re.findall(r'^abbreviated (\S+) (\S+)$', result.stdout, re.MULTILINE)
    assert len(found) == len(names), result.stdout
    for name, abbreviated in found:
        assert abbreviated == name, (name, abbreviated)
    # And it does change another lane's: a clang lane could not take the option as it is.
    (root / 'probe/Jamroot').write_text('import string ;\nECHO [ string.abbreviate clang ] ;\n')
    clang = subprocess.run(['b2', '-n'], cwd=root / 'probe', capture_output=True, text=True,
                           check=False)
    assert clang.stdout.startswith('clng'), clang.stdout


def test_register_writes_the_lanes_toolsets_in_order(root):
    config = boost_only(root)
    result = run(root, 'register', 'clang-18', 'wasip2', '--user-config', str(config))
    assert result.returncode == 0, (result.returncode, result.stderr)
    lines = config.read_text().splitlines()
    assert lines[1] == 'using clang : 18 : clang++-18 ;', lines
    # wasi-sdk's directory is one word of Jam, quoted, though the scratch superproject's path holds
    # a space: a lane registered there builds (test_an_own_lane_on_a_target_writes_its_xml...).
    # The build is given it as WASI_SDK too.
    wasi_sdk = f'"{root.resolve().as_posix()}/.local/wasi-sdk"'
    assert lines[2:5] == [f'local wasi-sdk = {wasi_sdk} ;',
                          f'modules.poke : WASI_SDK : {wasi_sdk} ;',
                          f'using clang : wasip2 : {wasi_sdk}/bin/clang++'], lines
    assert lines[-1].endswith(' ;') and not any(line.endswith(' ;') for line in lines[4:-1]), lines
    unknown = run(root, 'register', 'clang-99', '--user-config', str(config))
    assert unknown.returncode == 2, (unknown.returncode, unknown.stderr)
    assert 'no lane clang-99; the lanes are gcc-14, gcc-15' in unknown.stderr, unknown.stderr


def region(jam: Path, tag: str) -> str:
    """The lines of jam between `# tag::<tag>[]` and `# end::<tag>[]`."""
    return jam.read_text().split(f'# tag::{tag}[]\n')[1].split(f'# end::{tag}[]')[0]


def test_the_wasm_toolsets_come_from_wasi_sdk_jam(root):
    # tools/ci/wasi-sdk.jam holds the lines that name wasi-sdk's directory and give it to the
    # build as WASI_SDK, and those that register each WASI toolset against $(wasi-sdk), each
    # between `# tag::<target>[]` and `# end::<target>[]`, and the documentation shows them from
    # there; register writes the first, once, and a lane's, with wasi-sdk's directory in place of
    # /path/to/wasi-sdk and of $(wasi-sdk).
    jam = root / 'tools/ci/wasi-sdk.jam'
    wasi_sdk = f'"{root.resolve().as_posix()}/.local/wasi-sdk"'
    sdk = region(jam, 'wasi-sdk')
    assert sdk == ('local wasi-sdk = /path/to/wasi-sdk ;\n'
                   'modules.poke : WASI_SDK : $(wasi-sdk) ;\n'), sdk
    sdk = sdk.replace('/path/to/wasi-sdk', wasi_sdk).replace('$(wasi-sdk)', wasi_sdk)
    regions = {}
    for target in ('wasip2', 'wasip3'):
        regions[target] = region(jam, target)
        assert regions[target].startswith(f'using clang : {target} : $(wasi-sdk)/bin/clang++\n'), (
            regions[target])
        assert f'<cxxflags>--target=wasm32-{target}' in regions[target], regions[target]
        regions[target] = regions[target].replace('$(wasi-sdk)', wasi_sdk)
        config = boost_only(root)
        before = config.read_text()
        for _ in range(2):
            result = run(root, 'register', target, '--user-config', str(config))
            assert result.returncode == 0, (result.returncode, result.stderr)
        # Once, after what the file held.
        assert config.read_text() == before + sdk + regions[target], config.read_text()
    # Two WASI lanes share the lines of wasi-sdk, written once.
    config = boost_only(root)
    before = config.read_text()
    result = run(root, 'register', 'wasip2', 'wasip3', '--user-config', str(config))
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert config.read_text() == before + sdk + regions['wasip2'] + regions['wasip3'], (
        config.read_text())
    # The file is read, not a copy of it: a flag added there is registered.
    harness.replace(jam, '<linkflags>--target=wasm32-wasip2',
                    '<linkflags>--target=wasm32-wasip2 <linkflags>-Wl,--probe')
    config = boost_only(root)
    result = run(root, 'register', 'wasip2', '--user-config', str(config))
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert '<linkflags>-Wl,--probe' in config.read_text(), config.read_text()
    # A file that does not hold a target's lines fails what registers that target, naming the
    # file and the tag, and nothing else: the module loads, for an importer too, and the plan,
    # which registers nothing, is made.
    harness.replace(jam, '# tag::wasip3[]', '# tag::other[]')
    imported = subprocess.run([sys.executable, '-c', 'import matrix'], cwd=root / 'tools/ci',
                              capture_output=True, text=True, check=False)
    assert imported.returncode == 0, (imported.returncode, imported.stderr)
    config = boost_only(root)
    assert [lane['id'] for lane in planned(root, '--library', 'demo')] == NATIVE + [
        'wasip2', 'wasip3']
    result = run(root, 'register', 'wasip2', 'wasip3', '--user-config', str(config))
    assert result.returncode == 2 and result.stdout == '', (result.returncode, result.stdout)
    assert f'{jam.resolve()} holds no lines tag::wasip3[] to end::wasip3[]' in result.stderr, (
        result.stderr)
    harness.replace(jam, '# tag::wasi-sdk[]', '# tag::sdk[]')
    result = run(root, 'register', 'wasip2', '--user-config', str(config))
    assert result.returncode == 2, (result.returncode, result.stderr)
    assert f'{jam.resolve()} holds no lines tag::wasi-sdk[] to end::wasi-sdk[]' in (
        result.stderr), result.stderr


def test_the_emscripten_toolset_comes_from_emsdk_jam(root):
    # tools/ci/emsdk.jam holds the lines that name the emsdk's directory and the node that runs a
    # program, and those that register b2's emscripten toolset against them, between
    # `# tag::<region>[]` and `# end::<region>[]`, and the documentation shows them from there;
    # register writes both, once, with the directory where tools/ci/actions/emsdk installs the
    # emsdk in place of /path/to/emsdk and of $(emsdk), and the node wrapper it installs in place
    # of /path/to/node and of $(node), each quoted: the scratch superproject's path holds a space.
    jam = root / 'tools/ci/emsdk.jam'
    emsdk = f'"{root.resolve().as_posix()}/.local/emsdk"'
    node = f'"{root.resolve().as_posix()}/.local/emscripten/node"'
    sdk = region(jam, 'emsdk')
    assert sdk == 'local emsdk = /path/to/emsdk ;\nlocal node = /path/to/node ;\n', sdk
    toolset = region(jam, 'emscripten')
    assert toolset == ('using emscripten : : $(emsdk)/upstream/emscripten/em++ : '
                       '<nodejs>$(node) ;\n'), toolset

    def filled(text: str) -> str:
        return (text.replace('/path/to/emsdk', emsdk).replace('$(emsdk)', emsdk)
                .replace('/path/to/node', node).replace('$(node)', node))

    config = boost_only(root)
    before = config.read_text()
    for _ in range(2):
        result = run(root, 'register', 'emscripten', '--user-config', str(config))
        assert result.returncode == 0, (result.returncode, result.stderr)
    # Once, after what the file held.
    assert config.read_text() == before + filled(sdk) + filled(toolset), config.read_text()
    assert config.read_text().splitlines()[-1] == (
        f'using emscripten : : {emsdk}/upstream/emscripten/em++ : <nodejs>{node} ;')
    # Beside the toolsets the lint registers, after them.
    config = boost_only(root)
    result = run(root, 'register', 'clang-18', 'wasip2', 'wasip3', 'emscripten', '--user-config',
                 str(config))
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert config.read_text().endswith(filled(sdk) + filled(toolset)), config.read_text()
    assert config.read_text().splitlines()[1] == 'using clang : 18 : clang++-18 ;'
    # A file that does not hold the lines fails what registers emscripten, naming the file and
    # the tag, and leaves the user-config.jam as it was.
    for tag in ('emscripten', 'emsdk'):
        harness.replace(jam, f'# tag::{tag}[]', '# tag::other[]')
        config = boost_only(root)
        before = config.read_text()
        result = run(root, 'register', 'clang-18', 'emscripten', '--user-config', str(config))
        assert result.returncode == 2 and result.stdout == '', (result.returncode, result.stdout)
        assert f'{jam.resolve()} holds no lines tag::{tag}[] to end::{tag}[]' in (
            result.stderr), result.stderr
        assert config.read_text() == before, config.read_text()
        harness.replace(jam, '# tag::other[]', f'# tag::{tag}[]')


def host_lane(root: Path) -> dict:
    """The demo's lane for the host's clang++, as the plan writes Apple Clang's."""
    system = 'darwin' if sys.platform == 'darwin' else 'linux'
    entry = next(lane for lane in planned(root, '--library', 'demo') if lane['id'] == 'apple-clang')
    entry['lane'] = f'clang-{system}-{{version}}'
    return entry


def boost_only(root: Path) -> Path:
    """Makes root's user-config.jam this machine's `using boost` line alone, as the CI's Boost
    action writes it before a lane registers its toolset, and returns it."""
    lines = harness.USING_BOOST.findall(harness.user_config(harness.ROOT).read_text())
    harness.configure(root, ''.join(f'{line}\n' for line in lines))
    return root / '.local/user-config.jam'


def test_a_lane_writes_its_xml_and_the_report_merges_it(root):
    entry = host_lane(root)
    config = boost_only(root)
    output = root / 'github-output'
    output.write_text('')
    result = run(root, 'lane', json.dumps(entry), '--', '--build-dir=bin/lane',
                 github_output=output)
    assert result.returncode == 0, (result.returncode, result.stdout[-4000:], result.stderr)
    version = matrix.major_version('clang++')
    name = entry['lane'].replace('{version}', version)
    xml = root.resolve() / 'bin/ci' / f'{name}.xml'
    printed = (f'lane {name}: b2 {shlex.quote(f"--user-config={config.resolve()}")} -a '
               f'--dump-tests {shlex.quote(f"--out-xml={xml}")} toolset=clang-{version} '
               '--build-dir=bin/lane libs/demo/test libs/demo/example\n')
    assert result.stdout.startswith(printed), (printed, result.stdout[:2000])
    assert f'using clang : {version} : clang++ ;' in config.read_text().splitlines()
    assert xml.is_file(), xml
    assert output.read_text().splitlines() == [f'lane={name}', f'xml={xml.as_posix()}'], (
        output.read_text())
    lanes = root / 'downloaded'
    (lanes / 'lane-apple-clang').mkdir(parents=True)
    xml.rename(lanes / 'lane-apple-clang' / xml.name)
    plan = json.dumps({'include': [entry]})
    report = run(root, 'report', '--plan', plan, '--lanes', str(lanes), '--out',
                 str(root / 'report'))
    # The demo's tests pass, and the lane is a column of the matrix under its own name.
    assert report.returncode == 0, (report.returncode, report.stdout, report.stderr)
    page = (root / 'report/index.html').read_text()
    assert f'data-lane="{name}"' in page, page[:2000]


def test_an_emscripten_lane_writes_its_xml_and_the_report_merges_it(root):
    # The emscripten lane of browser_demo, run as the CI runs it: matrix.py lane registers the
    # toolset against the emsdk and the node wrapper where tools/ci/actions/emsdk installs them,
    # and b2 runs each program with that node. The wrapper refuses b2's probe of
    # --experimental-wasm-threads quietly, so no line of node's complaint reaches the output.
    shutil.copytree(harness.FIXTURES / 'browser_demo', root / 'libs/browser_demo',
                    ignore=harness.built)
    harness.link_emsdk(root)
    wrapper = root / '.local/emscripten/node'
    wrapper.parent.mkdir(parents=True)
    shutil.copy2(root / 'tools/ci/actions/emsdk/node.sh', wrapper)
    config = boost_only(root)
    entry = next(lane for lane in planned(root, '--library', 'browser_demo')
                 if lane['id'] == 'emscripten')
    output = root / 'github-output'
    output.write_text('')
    result = run(root, 'lane', json.dumps(entry), '--', '--build-dir=bin/lane',
                 github_output=output)
    assert result.returncode == 0, (result.returncode, result.stdout[-4000:], result.stderr)
    xml = root.resolve() / 'bin/ci/emscripten.xml'
    printed = (f'lane emscripten: b2 {shlex.quote(f"--user-config={config.resolve()}")} -a '
               f'--dump-tests {shlex.quote(f"--out-xml={xml}")} toolset=emscripten '
               '--build-dir=bin/lane libs/browser_demo/test libs/browser_demo/example\n')
    assert result.stdout.startswith(printed), (printed, result.stdout[:2000])
    assert 'experimental-wasm-threads' not in result.stdout + result.stderr, (
        result.stdout[-4000:], result.stderr)
    assert output.read_text().splitlines() == ['lane=emscripten', f'xml={xml.as_posix()}'], (
        output.read_text())
    lanes = root / 'downloaded'
    (lanes / 'lane-emscripten').mkdir(parents=True)
    xml.rename(lanes / 'lane-emscripten' / xml.name)
    report = run(root, 'report', '--plan', json.dumps({'include': [entry]}), '--lanes',
                 str(lanes), '--out', str(root / 'report'))
    # browser_demo's tests pass under node, and the lane is a column of the matrix.
    assert report.returncode == 0, (report.returncode, report.stdout, report.stderr)
    page = (root / 'report/browser_demo.html').read_text()
    assert 'data-lane="emscripten"' in page, page[:2000]


def test_a_lane_that_cannot_build_fails(root):
    entry = host_lane(root)
    # A user-config.jam that stops b2 as it loads, before it writes any XML.
    harness.configure(root, 'EXIT "a user-config.jam that stops b2" : 1 ;\n')
    output = root / 'github-output'
    output.write_text('')
    result = run(root, 'lane', json.dumps(entry), '--', '--build-dir=bin/lane',
                 github_output=output)
    assert result.returncode == 1, (result.returncode, result.stdout[-2000:], result.stderr)
    assert 'a user-config.jam that stops b2' in result.stdout, result.stdout[-2000:]
    assert 'b2 exited 1' in result.stderr, result.stderr
    # The job's outputs name the lane, and no XML: the upload step has nothing to upload.
    written = output.read_text().splitlines()
    assert any(line.startswith('lane=clang-') for line in written), written
    assert not any(line.startswith('xml=') for line in written), written


def test_the_report_names_a_planned_lane_that_wrote_nothing(root):
    samples = matrix.ROOT / 'tools/report/samples'
    lanes = root / 'downloaded'
    (lanes / 'lane-wasip2').mkdir(parents=True)
    (lanes / 'lane-wasip2' / 'wasip2.xml').write_bytes((samples / 'wasip2-pass.xml').read_bytes())
    entries = [lane for lane in planned(root, '--library', 'demo')
               if lane['id'] in ('wasip2', 'wasip3')]
    report = run(root, 'report', '--plan', json.dumps({'include': entries}), '--lanes',
                 str(lanes), '--out', str(root / 'report'))
    assert report.returncode == 2, (report.returncode, report.stdout, report.stderr)
    assert 'the lane wasip3 (wasm32-wasip3 (wasi-sdk 34, wasmtime 47.0.3)) wrote no XML' in (
        report.stderr), report.stderr
    # The lanes that did write are still reported.
    assert 'data-lane="wasip2"' in (root / 'report/index.html').read_text()


CASES = [
    test_the_targets_are_spelled_once,
    test_plan_of_one_library,
    test_plan_with_no_toolset_configured,
    test_plan_of_every_library,
    test_plan_of_a_library_on_emscripten,
    test_a_target_without_a_lane_fails,
    test_an_unknown_library_fails,
    test_own_lanes_of_every_library_and_of_one,
    test_own_lanes_on_targets,
    test_an_own_lanes_command,
    test_a_lane_is_named_by_the_compiler_version,
    test_abbreviated_paths_keep_the_lane_name,
    test_register_writes_the_lanes_toolsets_in_order,
    test_the_wasm_toolsets_come_from_wasi_sdk_jam,
    test_the_emscripten_toolset_comes_from_emsdk_jam,
    test_a_lane_writes_its_xml_and_the_report_merges_it,
    test_an_emscripten_lane_writes_its_xml_and_the_report_merges_it,
    test_a_lane_that_cannot_build_fails,
    test_the_report_names_a_planned_lane_that_wrote_nothing,
    test_an_own_lane_on_a_target_writes_its_xml_and_the_report_merges_it,
    test_an_own_lanes_failing_served_test_fails_the_report,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('matrix_test', CASES, sys.argv[1:]))
