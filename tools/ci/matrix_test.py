#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/ci/matrix.py: the plan has a lane per compiler for each target the libraries
declare, with the libraries that declare it, and fails on a target the CI has no lane for or a
library that does not exist; the own lanes the libraries declare are listed, of every library or
of one, and a line of b2's that is no own lane fails; a lane is named and registered by the
compiler's version when the image decides it; a lane runs the lane command and writes its XML,
and fails when b2 cannot build; the report merges the lanes and fails, by name, a planned lane
that wrote nothing. Each case runs the scratch superproject's own copy of matrix.py, with the
fixture library demo. Run with the names of some cases to run only those."""

from __future__ import annotations

import json
import os
import re
import shlex
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
    """Runs root's matrix.py, without the variables the Jamroot refuses, and with GITHUB_OUTPUT
    set to github_output when it is given."""
    environment = {name: value for name, value in os.environ.items()
                   if name not in harness.COMPILER_PATHS}
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


def test_a_target_without_a_lane_fails(root):
    harness.add_library(root, 'browser',
                        'import webcpp ;\nwebcpp.targets emscripten ;\n'
                        'webcpp.run pass : pass.cpp ;\n',
                        {'pass.cpp': 'int main() {}\n'})
    result = run(root, 'plan')
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    assert 'browser declare emscripten, which the CI has no lane for' in result.stderr, (
        result.stderr)
    assert 'the CI gets an emscripten lane when emsdk is pinned (AGENTS.md, Roadmap)' in (
        result.stderr), result.stderr
    assert result.stdout == '', result.stdout
    # Not even for another library: the matrix is planned whole, or not at all.
    assert run(root, 'plan', '--library', 'demo').returncode == 0


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
    alpha = [{'library': 'alpha', 'lane': 'browser', 'directory': 'libs/alpha/example/browser'},
             {'library': 'alpha', 'lane': 'http', 'directory': 'libs/alpha/test'}]
    beta = [{'library': 'beta', 'lane': 'oracle', 'directory': 'libs/beta/test/oracle'}]
    assert own_lanes(root) == alpha + beta
    assert own_lanes(root, '--library', 'beta') == beta
    assert own_lanes(root, '--library', 'demo') == []
    # What the job runs, b2 -a <directory>//<lane>, is built from these words alone: a line that
    # is not three of them, or whose directory is not the library's, fails the listing.
    for printed, named in (('alpha http', 'not "<library> <lane> <directory>"'),
                           ('alpha http libs/beta/test', 'not in libs/alpha/test or'),
                           ('alpha http; libs/alpha/test', 'not "<library> <lane> <directory>"')):
        try:
            matrix.parsed_own_lanes(printed)
        except matrix.Failure as failure:
            assert named in str(failure), (printed, failure)
        else:
            raise AssertionError(f'{printed!r} was read as an own lane')


def test_a_lane_is_named_by_the_compiler_version(root):
    compiler = root / 'fake clang++'
    compiler.write_text('#!/bin/sh\necho 17.0.0\n')
    compiler.chmod(compiler.stat().st_mode | stat.S_IXUSR)
    apple = next(lane for lane in matrix.LANES if lane.id == 'apple-clang')
    lane = matrix.resolved(matrix.replace(apple, detect=str(compiler)))
    assert (lane.lane, lane.toolset) == ('clang-darwin-17', 'clang-17'), lane
    assert lane.using == 'using clang : 17 : clang++ ;', lane.using
    wasip2 = matrix.resolved(next(lane for lane in matrix.LANES if lane.id == 'wasip2'))
    assert f'using clang : wasip2 : {matrix.ROOT.as_posix()}/.local/wasi-sdk/bin/clang++ :' in (
        wasip2.using), wasip2.using
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
    assert lines[2].startswith(f'using clang : wasip2 : {root.resolve().as_posix()}/'
                               '.local/wasi-sdk/bin/clang++ :'), lines
    assert len(lines) == 3, lines
    unknown = run(root, 'register', 'clang-99', '--user-config', str(config))
    assert unknown.returncode == 2, (unknown.returncode, unknown.stderr)
    assert 'no lane clang-99; the lanes are gcc-14, gcc-15' in unknown.stderr, unknown.stderr


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
    test_plan_of_one_library,
    test_plan_with_no_toolset_configured,
    test_plan_of_every_library,
    test_a_target_without_a_lane_fails,
    test_an_unknown_library_fails,
    test_own_lanes_of_every_library_and_of_one,
    test_a_lane_is_named_by_the_compiler_version,
    test_abbreviated_paths_keep_the_lane_name,
    test_register_writes_the_lanes_toolsets_in_order,
    test_a_lane_writes_its_xml_and_the_report_merges_it,
    test_a_lane_that_cannot_build_fails,
    test_the_report_names_a_planned_lane_that_wrote_nothing,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('matrix_test', CASES, sys.argv[1:]))
