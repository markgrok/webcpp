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
lanes and the own lanes on a target and fails, by name, a planned lane that wrote nothing;
`declares emscripten` says whether any library of the superproject declares emscripten, which
the docs and lint jobs install emsdk on, without its system libraries; a lane and an own lane of a
library that needs libraries webcpp does not build say external, with the compilers to build them
with, also through a library that uses one, `external` says whether a library needs them, or
any library, and every job installs them by the actions of their names; an own lane whose driver
meets a browser has the pinned chrome-headless-shell; and a container lane builds its image of
the Dockerfile's tag unless it is there, which the container action restores, and runs its b2
there with no network, or fails when the image does not build. Each
case runs the scratch superproject's own copy of matrix.py, with the fixture library demo, and
browser_demo where it says so. Run with the names of some cases to run only those."""

from __future__ import annotations

import hashlib
import json
import os
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
                   'emsdk': True, 'node': True, 'cc': '', 'cxx': '', 'container': False,
                   'external': False}


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


def test_whether_a_library_declares_emscripten(root):
    # The docs and lint jobs install emsdk only when some library of the superproject declares
    # emscripten, every library's, whatever library the CI runs for: the lint analyses every
    # library, and a page builds the page of each library it links, with its reference.
    boost_only(root)
    for arguments in ((), ('--library', 'demo')):
        result = run(root, 'declares', 'emscripten', *arguments)
        assert (result.returncode, result.stdout) == (0, 'false\n'), (result.returncode,
                                                                   result.stdout, result.stderr)
    assert run(root, 'declares', 'wasip2').stdout == 'true\n'
    shutil.copytree(harness.FIXTURES / 'browser_demo', root / 'libs/browser_demo',
                    ignore=harness.built)
    for arguments in ((), ('--library', 'demo'), ('--library', 'browser_demo')):
        result = run(root, 'declares', 'emscripten', *arguments)
        assert (result.returncode, result.stdout) == (0, 'true\n'), (result.returncode,
                                                                  result.stdout, result.stderr)
    result = run(root, 'declares', 'wasip9')
    assert result.returncode == 2 and 'wasip9' in result.stderr, (result.returncode,
                                                                  result.stderr)
    result = run(root, 'declares', 'emscripten', '--library', 'nothing')
    assert result.returncode == 2, (result.returncode, result.stderr)
    assert 'libs/nothing declares no target, or is no library' in result.stderr, result.stderr


def test_the_docs_and_lint_jobs_install_emsdk_when_a_library_declares_emscripten(_):
    # The plan job writes has-emscripten, from matrix.py declares emscripten; the docs job and
    # the lint job need it, install emsdk without its system libraries, which they never link,
    # only when it is true, and the lint registers the emscripten toolset only then.
    workflow = (harness.ROOT / '.github/workflows/library.yml').read_text()
    jobs = {match.group(1): match.group(2) for match in re.finditer(
        r'^  ([a-z-]+):\n(.*?)(?=^  [a-z-]+:\n|\Z)', workflow[workflow.index('\njobs:\n'):],
        re.MULTILINE | re.DOTALL)}
    plan = jobs['plan']
    assert 'has-emscripten: ${{ steps.plan.outputs.has-emscripten }}' in plan, plan
    assert 'python3 tools/ci/matrix.py declares emscripten' in plan, plan
    for name in ('docs', 'lint'):
        job = jobs[name]
        assert re.search(r'^    needs: plan$', job, re.MULTILINE), (name, job)
        steps = re.findall(r'^      - (?:(?!^      - ).)*', job, re.MULTILINE | re.DOTALL)
        emsdk = [step for step in steps if 'uses: ./tools/ci/actions/emsdk' in step]
        assert len(emsdk) == 1, (name, emsdk)
        assert "if: needs.plan.outputs.has-emscripten == 'true'" in emsdk[0], (name, emsdk)
        assert "libraries: 'false'" in emsdk[0], (name, emsdk)
    lint = jobs['lint']
    assert 'HAS_EMSCRIPTEN: ${{ needs.plan.outputs.has-emscripten }}' in lint, lint
    assert 'python3 tools/ci/matrix.py register clang-18 wasip2 wasip3 emscripten' not in lint


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
    oracle_library(root, 'beta')
    # Every entry names its job and its image, which the job reads from here alone, and its kind,
    # by which it has Node: an oracle runs its original with it, and the lanes of programs alone
    # need none.
    alpha = [{'library': 'alpha', 'lane': 'browser', 'directories': ['libs/alpha/example/browser'],
              'kind': 'programs', 'name': 'Own lane (alpha, browser)', 'os': 'ubuntu-24.04',
              'wasm': False, 'emsdk': False, 'node': False,
              'cc': 'clang-18', 'cxx': 'clang++-18', 'external': False,
              'chrome': False},
             {'library': 'alpha', 'lane': 'http', 'directories': ['libs/alpha/test'],
              'kind': 'programs', 'name': 'Own lane (alpha, http)', 'os': 'ubuntu-24.04',
              'wasm': False, 'emsdk': False, 'node': False,
              'cc': 'clang-18', 'cxx': 'clang++-18', 'external': False,
              'chrome': False}]
    beta = [{'library': 'beta', 'lane': 'oracle', 'directories': ['libs/beta/test/oracle'],
             'kind': 'original', 'name': 'Own lane (beta, oracle)', 'os': 'ubuntu-24.04',
             'wasm': False, 'emsdk': False, 'node': True,
             'cc': 'clang-18', 'cxx': 'clang++-18', 'external': False,
             'chrome': False}]
    assert own_lanes(root) == alpha + beta
    assert own_lanes(root, '--library', 'beta') == beta
    assert own_lanes(root, '--library', 'demo') == []
    # A library that does not exist is no library without own lanes: it fails as the plan's
    # --library does, by name, and prints no matrix.
    result = run(root, 'own-lanes', '--library', 'nothing')
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    assert 'libs/nothing is no library of libs/' in result.stderr, result.stderr
    assert result.stdout == '', result.stdout
    # What the job runs, b2 -a <directory>//<lane>, is built from these words alone, and what it
    # sets up from the kind: a line that is not four or five of them, whose directory is not the
    # library's, or whose target or kind is none, fails the listing.
    form = 'not "<library> <lane> <directory> [<target>] <kind>"'
    for printed, named in (('alpha http programs', form),
                           ('alpha http libs/alpha/test', form),
                           ('alpha http libs/beta/test programs', 'not in libs/alpha/test or'),
                           ('alpha http; libs/alpha/test programs', form),
                           ('alpha http libs/alpha/test wasm programs', 'wasm is not a target'),
                           ('alpha http libs/alpha/test wasip2',
                            'wasip2 is not a kind; the kinds are original, programs'),
                           ('alpha http libs/alpha/test wasip2 node',
                            'node is not a kind; the kinds are original, programs'),
                           ('alpha http libs/alpha/test wasip2 wasip3 programs', form)):
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
    oracle_library(root, 'beta')
    # A lane of programs alone, a served one on wasip2 or wasip3 among them, needs no Node.
    alpha = [{'library': 'alpha', 'lane': 'http', 'directories': ['libs/alpha/example'],
              'platform': 'native', 'id': 'native.alpha.http', 'kind': 'programs',
              'name': 'Own lane (alpha, http, native)', 'os': 'ubuntu-24.04', 'wasm': False,
              'emsdk': False, 'node': False,
              'cc': 'clang-18', 'cxx': 'clang++-18', 'external': False,
              'chrome': False},
             {'library': 'alpha', 'lane': 'http',
              'directories': ['libs/alpha/example', 'libs/alpha/test'], 'platform': 'wasip2',
              'id': 'wasip2.alpha.http', 'kind': 'programs', 'name': 'Own lane (alpha, http, '
              'wasip2)', 'os': 'ubuntu-24.04', 'wasm': True, 'emsdk': False, 'node': False,
              'cc': '', 'cxx': '', 'external': False,
              'chrome': False},
             {'library': 'alpha', 'lane': 'http', 'directories': ['libs/alpha/test'],
              'platform': 'wasip3', 'id': 'wasip3.alpha.http', 'kind': 'programs',
              'name': 'Own lane (alpha, http, wasip3)', 'os': 'ubuntu-24.04', 'wasm': True,
              'emsdk': False, 'node': False, 'cc': '', 'cxx': '', 'external': False,
              'chrome': False}]
    beta = {'library': 'beta', 'lane': 'oracle', 'directories': ['libs/beta/test/oracle'],
            'kind': 'original', 'name': 'Own lane (beta, oracle)', 'os': 'ubuntu-24.04',
            'wasm': False, 'emsdk': False, 'node': True,
            'cc': 'clang-18', 'cxx': 'clang++-18', 'external': False,
            'chrome': False}
    assert own_lanes(root) == [*alpha, beta]
    assert own_lanes(root, '--library', 'alpha') == alpha
    assert run(root, 'own-lanes', '--library', 'beta').stdout == (
        '{"include":[{"library":"beta","lane":"oracle","directories":["libs/beta/test/oracle"],'
        '"kind":"original","name":"Own lane (beta, oracle)","os":"ubuntu-24.04","wasm":false,'
        '"emsdk":false,"node":true,"cc":"clang-18","cxx":"clang++-18","external":false,'
        '"chrome":false}]}\n')
    # Each entry is read back as the lane it is, and runs in each of its directories.
    for entry in alpha:
        own = matrix.parsed_own_lane(json.dumps(entry))
        assert own_lane_entry_of(own) == entry, (own, entry)
        assert own.requests == [f'{directory}//http' for directory in entry['directories']]
    # An own lane on emscripten shares the emscripten lane's setup, emsdk and Node, which runs its
    # programs, whatever its kind; a driven test on native has Node for its driver, the version
    # the CI pins rather than the image's.
    harness.add_library(root, 'gamma',
                        'import webcpp ;\n'
                        'webcpp.targets native emscripten ;\n'
                        'webcpp.original node ;\n'
                        'webcpp.run plain : plain.cpp ;\n'
                        'webcpp.drive driven : plain.cpp : : drive.mjs ;\n'
                        'webcpp.lane browser : plain : emscripten ;\n'
                        'webcpp.lane driver : driven : native emscripten ;\n',
                        {'plain.cpp': 'int main() {}\n', 'drive.mjs': '',
                         'package.json': '{}\n', 'package-lock.json': '{}\n'})
    gamma = [{'library': 'gamma', 'lane': 'browser', 'directories': ['libs/gamma/test'],
              'platform': 'emscripten', 'id': 'emscripten.gamma.browser', 'kind': 'programs',
              'name': 'Own lane (gamma, browser, emscripten)', 'os': 'ubuntu-24.04',
              'wasm': False, 'emsdk': True, 'node': True, 'cc': '', 'cxx': '', 'external': False,
              'chrome': False},
             {'library': 'gamma', 'lane': 'driver', 'directories': ['libs/gamma/test'],
              'platform': 'emscripten', 'id': 'emscripten.gamma.driver', 'kind': 'original',
              'name': 'Own lane (gamma, driver, emscripten)', 'os': 'ubuntu-24.04',
              'wasm': False, 'emsdk': True, 'node': True, 'cc': '', 'cxx': '', 'external': False,
              'chrome': False},
             {'library': 'gamma', 'lane': 'driver', 'directories': ['libs/gamma/test'],
              'platform': 'native', 'id': 'native.gamma.driver', 'kind': 'original',
              'name': 'Own lane (gamma, driver, native)', 'os': 'ubuntu-24.04', 'wasm': False,
              'emsdk': False, 'node': True,
              'cc': 'clang-18', 'cxx': 'clang++-18', 'external': False,
              'chrome': False}]
    assert own_lanes(root) == [*alpha, beta, *gamma]
    assert own_lanes(root, '--library', 'gamma') == gamma
    for entry in gamma:
        own = matrix.parsed_own_lane(json.dumps(entry))
        assert own_lane_entry_of(own) == entry, (own, entry)
    # Node exactly where the original runs, or where the target's own lane has it.
    assert [entry['id'] for entry in own_lanes(root) if not entry['node']] == [
        'native.alpha.http', 'wasip2.alpha.http', 'wasip3.alpha.http'], own_lanes(root)
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


def oracle_library(root: Path, name: str) -> None:
    """Adds to root the library name, whose oracle declares its twins and its lane oracle over
    them: a lane of the kind original."""
    harness.add_library(root, name, 'import webcpp ;\n', {})
    oracle = root / 'libs' / name / 'test/oracle'
    oracle.mkdir()
    for lockfile in ('package.json', 'package-lock.json'):
        (oracle / lockfile).write_text('{}\n')
    (oracle / 'Jamfile').write_text('import webcpp ;\n'
                                    'webcpp.original node ;\n'
                                    'webcpp.twins ../../example : twins : .mjs ;\n'
                                    'webcpp.lane oracle : twins ;\n')


def own_lane_entry_of(own: matrix.OwnLane) -> dict:
    """The entry of the own-lanes matrix of own, as own-lanes prints it."""
    return json.loads(json.dumps(matrix.own_lane_entry(own)))


def test_an_own_lanes_command(root):
    config = root / 'config.jam'
    oracle = matrix.parsed_own_lanes('beta oracle libs/beta/test/oracle original')[0]
    # Without a target, as an oracle runs: Clang 18, from scratch, its exit status the verdict.
    assert matrix.own_lane_command(oracle, config, None, ['--build-dir=bin/x']) == [
        'b2', f'--user-config={config}', '-a', 'toolset=clang-18', '--build-dir=bin/x',
        'libs/beta/test/oracle//oracle']
    # On a target, as that target's lane runs: its toolset and options, and the XML the report
    # reads; in each directory that declares it there.
    served = matrix.parsed_own_lanes('alpha http libs/alpha/test wasip2 programs\n'
                                     'alpha http libs/alpha/example wasip2 programs')
    assert len(served) == 1, served
    # One lane, whose directories hold programs alone in one and the original in another, runs
    # the original.
    mixed = matrix.parsed_own_lanes('alpha http libs/alpha/test wasip2 programs\n'
                                    'alpha http libs/alpha/example wasip2 original')
    assert [lane.kind for lane in mixed] == ['original'], mixed
    xml = Path('bin/ci/wasip2.alpha.http.xml')
    assert matrix.own_lane_command(served[0], config, xml, []) == [
        'b2', f'--user-config={config}', '-a', '--dump-tests', f'--out-xml={xml}',
        'toolset=clang-wasip2', 'testing.launcher=wasmtime', 'libs/alpha/example//http',
        'libs/alpha/test//http']
    # On emscripten, as the emscripten lane runs: its toolset, and no launcher.
    driven = matrix.parsed_own_lanes('alpha driver libs/alpha/test/driver emscripten original')
    xml = Path('bin/ci/emscripten.alpha.driver.xml')
    assert matrix.own_lane_command(driven[0], config, xml, []) == [
        'b2', f'--user-config={config}', '-a', '--dump-tests', f'--out-xml={xml}',
        'toolset=emscripten', 'libs/alpha/test/driver//driver']
    # An own lane of a library that needs external libraries requires them, as its lane does.
    interop = matrix.parsed_own_lanes('trystero interop libs/trystero/test/oracle native original')
    command = matrix.own_lane_command(interop[0], config, xml, [])
    assert command[command.index('toolset=clang-18') + 1] == 'webcpp-require-external=on', command
    oracle_command = matrix.own_lane_command(oracle, config, None, [])
    assert 'webcpp-require-external=on' not in oracle_command, oracle_command
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


def test_the_lanes_name_their_compilers_and_their_container(_):
    # The compilers an external dependency is built with, the lane's own, and the lanes whose b2
    # runs in a container with no network: GCC 14 and Clang 18 on Ubuntu 24.04.
    by_id = {lane.id: lane for lane in matrix.LANES}
    assert {lane_id: (lane.cc, lane.cxx) for lane_id, lane in by_id.items()} == {
        'gcc-14': ('gcc-14', 'g++-14'), 'gcc-15': ('gcc-15', 'g++-15'),
        'clang-18': ('clang-18', 'clang++-18'), 'clang-22': ('clang-22', 'clang++-22'),
        'apple-clang': ('clang', 'clang++'), 'msvc-14.3': ('', ''), 'msvc-14.5': ('', ''),
        'emscripten': ('', ''), 'wasip2': ('', ''), 'wasip3': ('', '')}, by_id
    assert [lane.id for lane in matrix.LANES if lane.container] == ['gcc-14', 'clang-18']
    assert all(by_id[lane_id].os == 'ubuntu-24.04' for lane_id in ('gcc-14', 'clang-18'))
    assert by_id['gcc-14'].name == 'GCC 14 (container, no network)', by_id['gcc-14']
    assert by_id['clang-18'].name == 'Clang 18 (libstdc++, container, no network)', (
        by_id['clang-18'])


def external_library(root: Path) -> None:
    """Adds to root a library named trystero, as EXTERNAL_DEPENDENCIES names it: native and
    emscripten, and an own lane on each."""
    harness.add_library(root, 'trystero',
                        'import webcpp ;\n'
                        'webcpp.targets native emscripten ;\n'
                        'webcpp.run plain : plain.cpp ;\n'
                        'webcpp.run served : plain.cpp ;\n'
                        'webcpp.lane interop : served : native emscripten ;\n',
                        {'plain.cpp': 'int main() {}\n'})


def test_a_lane_of_a_library_with_external_dependencies_says_so(root):
    # Until webcpp builds them from third_party/, the libraries trystero needs are installed by
    # the CI's actions of their names, on a lane or an own lane that builds trystero: its entry
    # says external, and no other does.
    assert matrix.EXTERNAL_DEPENDENCIES == {
        'trystero': ('secp256k1', 'libdatachannel', 'openssl')}, matrix.EXTERNAL_DEPENDENCIES
    for dependencies in matrix.EXTERNAL_DEPENDENCIES.values():
        for dependency in dependencies:
            assert (matrix.ROOT / 'tools/ci/actions' / dependency / 'action.yml').is_file(), (
                dependency)
    boost_only(root)
    assert not any(lane['external'] for lane in planned(root)), planned(root)
    external_library(root)
    lanes = planned(root)
    assert {lane['id']: lane['external'] for lane in lanes} == {
        **{name: True for name in NATIVE}, 'emscripten': True, 'wasip2': False,
        'wasip3': False}, lanes
    assert not any(lane['external'] for lane in planned(root, '--library', 'demo'))
    assert all(lane['external'] for lane in planned(root, '--library', 'trystero'))
    entries = own_lanes(root, '--library', 'trystero')
    assert [(entry['id'], entry['external'], entry['cc'], entry['cxx']) for entry in entries] == [
        ('emscripten.trystero.interop', True, '', ''),
        ('native.trystero.interop', True, 'clang-18', 'clang++-18')], entries
    # Each entry is read back as the lane it is.
    for entry in entries:
        assert own_lane_entry_of(matrix.parsed_own_lane(json.dumps(entry))) == entry, entry
    oracle_library(root, 'beta')
    assert [entry['external'] for entry in own_lanes(root, '--library', 'beta')] == [False]


def test_whether_a_library_has_external_dependencies(root):
    # With --library, whether that library needs them, itself or through a library of libs/ its
    # Jamfiles use (/webcpp/<name>), which the docs job installs them on: its page parses its
    # headers and those of the libraries it uses. Without, whether any library of libs/ does,
    # which the lint job, which analyses every library, installs them on.
    boost_only(root)
    for arguments in ((), ('--library', 'demo')):
        result = run(root, 'external', *arguments)
        assert (result.returncode, result.stdout) == (0, 'false\n'), (result.returncode,
                                                                   result.stdout, result.stderr)
    external_library(root)
    harness.add_library(root, 'user',
                        'import webcpp ;\nwebcpp.run plain : plain.cpp\n'
                        '  : <library>/webcpp/trystero//trystero ;\n',
                        {'plain.cpp': 'int main() {}\n'})
    harness.add_library(root, 'user_of_user', 'import webcpp ;\n', {})
    (root / 'libs/user_of_user/build.jam').write_text(
        'project /webcpp/user_of_user ;\n'
        'alias user_of_user : : : : <library>/webcpp/user//user ;\n')
    for arguments, expected in (((), 'true'), (('--library', 'trystero'), 'true'),
                                (('--library', 'user'), 'true'),
                                (('--library', 'user_of_user'), 'true'),
                                (('--library', 'demo'), 'false')):
        result = run(root, 'external', *arguments)
        assert (result.returncode, result.stdout) == (0, f'{expected}\n'), (
            arguments, result.returncode, result.stdout, result.stderr)
    # A lane of a library that uses one says external too.
    assert {lane['id']: lane['external'] for lane in planned(root, '--library', 'user')} == {
        name: True for name in NATIVE}
    result = run(root, 'external', '--library', 'nothing')
    assert result.returncode == 2 and result.stdout == '', (result.returncode, result.stdout)
    assert 'libs/nothing is no library of libs/' in result.stderr, result.stderr


def workflow_jobs() -> dict[str, str]:
    """The text of each job of library.yml, by its name."""
    workflow = (harness.ROOT / '.github/workflows/library.yml').read_text()
    return {match.group(1): match.group(2) for match in re.finditer(
        r'^  ([a-z-]+):\n(.*?)(?=^  [a-z-]+:\n|\Z)', workflow[workflow.index('\njobs:\n'):],
        re.MULTILINE | re.DOTALL)}


def job_steps(job: str) -> list[str]:
    """The text of each step of a job."""
    return re.findall(r'^      - (?:(?!^      - ).)*', job, re.MULTILINE | re.DOTALL)


def test_the_jobs_install_the_external_dependencies(_):
    # The lanes and the own lanes run the dependency actions for an entry that says external,
    # OpenSSL first, which libdatachannel builds against, and secp256k1 for emscripten too after
    # emsdk on an entry that has it; libdatachannel and OpenSSL, which only the native backend
    # needs, not on emscripten. The docs and lint jobs run them when the plan's external is true,
    # with Clang 18, the toolset they parse with, and the lint, which analyses emscripten's
    # commands, with secp256k1's emscripten build when a library declares emscripten.
    jobs = workflow_jobs()
    plan = jobs['plan']
    assert 'external: ${{ steps.plan.outputs.external }}' in plan, plan
    assert 'lint-external: ${{ steps.plan.outputs.lint-external }}' in plan, plan
    assert 'python3 tools/ci/matrix.py external "${arguments[@]}"' in plan, plan
    assert 'lint_external="$(python3 tools/ci/matrix.py external)"' in plan, plan
    actions = ('emsdk', 'openssl', 'secp256k1', 'libdatachannel')
    steps = job_steps(jobs['lanes'])
    uses = [next((action for action in actions if f'./tools/ci/actions/{action}' in step), None)
            for step in steps]
    assert [action for action in uses if action] == list(actions), uses
    by_action = {action: step for action, step in zip(uses, steps) if action}
    for action in actions:
        assert by_action[action].lstrip().startswith(f'- &{action}\n'), by_action[action]
    assert 'if: matrix.external && !matrix.emsdk' in by_action['openssl'], by_action
    assert 'if: matrix.external\n' in by_action['secp256k1'], by_action
    assert 'emscripten: ${{ matrix.emsdk }}' in by_action['secp256k1'], by_action
    assert 'cc: ${{ matrix.cc }}' in by_action['secp256k1'], by_action
    assert 'if: matrix.external && !matrix.emsdk' in by_action['libdatachannel'], by_action
    assert 'cxx: ${{ matrix.cxx }}' in by_action['libdatachannel'], by_action
    # The own lanes install them by the same anchors, in the same order.
    firsts = [step.strip().splitlines()[0] for step in job_steps(jobs['own-lanes'])]
    aliases = [first for first in firsts if first in {f'- *{action}' for action in actions}]
    assert aliases == [f'- *{action}' for action in actions], aliases
    for name, output in (('docs', 'external'), ('lint', 'lint-external')):
        steps = job_steps(jobs[name])
        for action in ('openssl', 'secp256k1', 'libdatachannel'):
            found = [step for step in steps if f'uses: ./tools/ci/actions/{action}' in step]
            assert len(found) == 1, (name, action, found)
            assert f"if: needs.plan.outputs.{output} == 'true'" in found[0], (name, found)
            if action != 'openssl':
                assert 'cc: clang-18' in found[0], (name, found)
        emsdk = next(index for index, step in enumerate(steps) if 'actions/emsdk' in step)
        secp256k1 = next(index for index, step in enumerate(steps) if 'actions/secp256k1' in step)
        assert emsdk < secp256k1, name
    documentation = next(step for step in job_steps(jobs['docs']) if 'name: Documentation' in step)
    assert 'request=(webcpp-require-external=on "${request[@]}")' in documentation, documentation
    for variable in matrix.EXTERNAL_VARIABLES:
        assert variable in documentation, (variable, documentation)
    lint_secp256k1 = next(step for step in job_steps(jobs['lint'])
                          if 'actions/secp256k1' in step)
    assert 'emscripten: ${{ needs.plan.outputs.has-emscripten }}' in lint_secp256k1


def test_a_container_lane_has_its_image_from_the_cache(_):
    # The container job builds the image once per run, and caches it, before any lane: the lanes
    # wait for it, and their container action restores the image of this Dockerfile before the
    # lane runs, which then builds nothing. The plan says whether a container lane is planned.
    jobs = workflow_jobs()
    plan = jobs['plan']
    assert 'has-container: ${{ steps.plan.outputs.has-container }}' in plan, plan
    container_job = jobs['container']
    assert re.search(r'^    needs: plan$', container_job, re.MULTILINE), container_job
    assert "if: needs.plan.outputs.has-container == 'true'" in container_job, container_job
    assert len([step for step in job_steps(container_job)
                if 'uses: ./tools/ci/actions/container' in step]) == 1, container_job
    lanes_job = jobs['lanes']
    assert re.search(r'^    needs: \[plan, container\]$', lanes_job, re.MULTILINE), lanes_job
    assert ("needs.container.result == 'success' || needs.container.result == 'skipped'"
            in lanes_job), lanes_job
    steps = job_steps(lanes_job)
    container = [index for index, step in enumerate(steps)
                 if 'uses: ./tools/ci/actions/container' in step]
    lane = next(index for index, step in enumerate(steps) if 'matrix.py lane "$LANE"' in step)
    assert len(container) == 1 and container[0] < lane, (container, lane)
    assert 'if: matrix.container\n' in steps[container[0]], steps[container[0]]


def test_a_browser_lane_has_the_pinned_chrome(root):
    # An own lane whose driver meets a browser, trystero's interop (CHROME_LANES), says chrome,
    # on every target it runs on, and its job installs the pinned chrome-headless-shell, which
    # gives CHROME; no other own lane does, and no job names the image's Chrome.
    assert matrix.CHROME_LANES == {('trystero', 'interop')}, matrix.CHROME_LANES
    boost_only(root)
    external_library(root)
    oracle_library(root, 'beta')
    assert {entry.get('id', entry['lane']): entry['chrome'] for entry in own_lanes(root)} == {
        'oracle': False, 'emscripten.trystero.interop': True,
        'native.trystero.interop': True}, own_lanes(root)
    steps = job_steps(workflow_jobs()['own-lanes'])
    chrome = [step for step in steps if 'uses: ./tools/ci/actions/chrome' in step]
    assert len(chrome) == 1 and 'if: matrix.chrome\n' in chrome[0], chrome
    workflow = (harness.ROOT / '.github/workflows/library.yml').read_text()
    assert '/usr/bin/google-chrome' not in workflow
    # AGENTS.md names the shell's version once, the action's.
    pinned = re.search(r'^version=(\S+)$',
                       (matrix.ROOT / 'tools/ci/actions/chrome/install.sh').read_text(),
                       re.MULTILINE)
    agents = (matrix.ROOT / 'AGENTS.md').read_text()
    assert pinned and agents.count(pinned.group(1)) == 1, pinned
    assert 'Chrome 154' not in agents and 'google-chrome' not in agents
    action = (matrix.ROOT / 'tools/ci/actions/chrome/action.yml').read_text()
    assert set(re.findall(r'\d+\.\d+\.\d+\.\d+', action)) == {pinned.group(1)}, action


# A stand-in of docker: each call's words to docker.log, quoted as a shell reads them, one line
# each; `image inspect` succeeds when STAND_IN_IMAGE_PRESENT is set, `build` builds nothing, and
# `run` runs, on the host, the command after the image.
FAKE_DOCKER = r"""#!/usr/bin/env bash
set -euo pipefail
{ printf '%q ' docker "$@"; printf '\n'; } >> "${STAND_IN_DOCKER_LOG}"
if [ "$1 $2" = 'image inspect' ]; then
    [ -n "${STAND_IN_IMAGE_PRESENT-}" ]
    exit
fi
[ "$1" = run ] || exit 0
shift
while [ "$1" != "${STAND_IN_IMAGE}" ]; do
    shift
done
shift
exec "$@"
"""


def test_a_container_lane_runs_b2_with_no_network(root):
    # A container lane builds its image from tools/ci/container/Dockerfile, then runs the lane
    # command's b2 by its path in it, as the user who runs the lane, with no network but the
    # loopback, the superproject and b2's prefix (the Boost action's, with Boost's headers)
    # mounted at their own paths, and the external dependencies' variables passed on. The XML is
    # the lane's, as written outside a container.
    dockerfile = (matrix.ROOT / 'tools/ci/container/Dockerfile').read_text()
    assert re.search(r'^FROM ubuntu:24\.04@sha256:[0-9a-f]{64}$', dockerfile, re.MULTILINE), (
        dockerfile)
    # Its packages from Ubuntu's snapshot at one date, and its tag that of this Dockerfile.
    assert re.search(r'^ARG SNAPSHOT=\d{8}T\d{6}Z$', dockerfile, re.MULTILINE), dockerfile
    # Every package from the snapshot, ca-certificates included: each apt-get update and install
    # names it, and none reads the live archive.
    code = ''.join(line for line in dockerfile.splitlines(keepends=True)
                   if not line.startswith('#'))
    commands = re.findall(r'apt-get (?:-o \S+ )?(update|install)\b[^&]*', code)
    assert len(commands) == 4, commands
    calls = re.findall(r'apt-get[^&]*', code)
    assert all('--snapshot "${SNAPSHOT}"' in call for call in calls), calls
    assert re.search(r'install[^&]*--snapshot "\$\{SNAPSHOT\}" ca-certificates', code), code
    digest = hashlib.sha256(dockerfile.encode()).hexdigest()
    assert matrix.CONTAINER_IMAGE == f'webcpp-lane:{digest[:16]}', matrix.CONTAINER_IMAGE
    for package in ('g++-14', 'clang-18', 'libssl-dev', 'python3'):
        assert f' {package}' in dockerfile, (package, dockerfile)
    entry = host_lane(root)
    entry['container'] = True
    # A lane of a library that needs external libraries: the build requires them, and is given
    # each that an action exported, on b2's command line.
    entry['external'] = True
    config = boost_only(root)
    tools = root / 'stand-ins'
    tools.mkdir()
    (tools / 'docker').write_text(FAKE_DOCKER)
    (tools / 'docker').chmod(0o755)
    log = root / 'docker.log'
    environment = harness.b2_environment()
    environment.pop('GITHUB_OUTPUT', None)
    environment.update(PATH=f'{tools}:{environment["PATH"]}', STAND_IN_DOCKER_LOG=str(log),
                       STAND_IN_IMAGE=matrix.CONTAINER_IMAGE, LIBDATACHANNEL_ROOT='/somewhere')
    environment.pop('SECP256K1_ROOT', None)
    result = subprocess.run([sys.executable, str(root / 'tools/ci/matrix.py'), 'lane',
                             json.dumps(entry), '--', '--build-dir=bin/lane'], cwd=root,
                            env=environment, capture_output=True, text=True, check=False,
                            timeout=harness.TIMEOUT)
    assert result.returncode == 0, (result.returncode, result.stdout[-4000:], result.stderr)
    b2 = Path(shutil.which('b2', path=environment['PATH']) or 'b2').resolve()
    resolved = root.resolve()
    calls = [shlex.split(line) for line in log.read_text().splitlines()]
    # The image is built only when no image of this Dockerfile's tag is there.
    assert calls[0] == ['docker', 'image', 'inspect', matrix.CONTAINER_IMAGE], calls
    assert calls[1] == ['docker', 'build', '--tag', matrix.CONTAINER_IMAGE,
                        f'{resolved}/tools/ci/container'], calls
    assert len(calls) == 3 and calls[2][0] == 'docker', calls
    run_words = calls[2][1:]
    image = run_words.index(matrix.CONTAINER_IMAGE)
    options, command = run_words[:image], run_words[image + 1:]
    assert options[:4] == ['run', '--rm', '--network', 'none'], options
    assert ['--user', f'{os.getuid()}:{os.getgid()}'] == options[4:6], options
    assert ['--workdir', str(resolved)] == options[6:8], options
    # The environment reaches no b2: the container is given no variable of the external
    # libraries, and b2 has them on its command line.
    assert '--env' not in options, options
    volumes = [options[index + 1] for index, word in enumerate(options) if word == '--volume']
    assert f'{resolved}:{resolved}' in volumes, volumes
    assert f'{b2.parents[1]}:{b2.parents[1]}' in volumes, volumes
    assert command[0] == str(b2), command
    assert command[1:4] == [f'--user-config={config.resolve()}', '-a', '--dump-tests'], command
    toolset = command.index(next(word for word in command if word.startswith('toolset=')))
    assert command[toolset + 1:toolset + 3] == ['webcpp-require-external=on',
                                                '-sLIBDATACHANNEL_ROOT=/somewhere'], command
    assert not any(word.startswith('-sSECP256K1_ROOT') for word in command), command
    version = matrix.major_version('clang++')
    system = 'darwin' if sys.platform == 'darwin' else 'linux'
    assert (resolved / f'bin/ci/clang-{system}-{version}.xml').is_file()
    # With the image there, as the container action loads it from its cache, nothing is built.
    log.unlink()
    result = subprocess.run([sys.executable, str(root / 'tools/ci/matrix.py'), 'lane',
                             json.dumps(entry), '--', '--build-dir=bin/lane'], cwd=root,
                            env={**environment, 'STAND_IN_IMAGE_PRESENT': '1'},
                            capture_output=True, text=True, check=False, timeout=harness.TIMEOUT)
    assert result.returncode == 0, (result.returncode, result.stdout[-4000:], result.stderr)
    calls = [shlex.split(line) for line in log.read_text().splitlines()]
    assert [call[:2] for call in calls] == [['docker', 'image'], ['docker', 'run']], calls
    # A lane outside a container runs b2 as it is.
    log.unlink()
    entry['container'] = False
    result = subprocess.run([sys.executable, str(root / 'tools/ci/matrix.py'), 'lane',
                             json.dumps(entry), '--', '--build-dir=bin/lane'], cwd=root,
                            env=environment, capture_output=True, text=True, check=False,
                            timeout=harness.TIMEOUT)
    assert result.returncode == 0, (result.returncode, result.stdout[-4000:], result.stderr)
    assert not log.exists(), log.read_text()


def test_a_container_lane_whose_image_does_not_build_fails(root):
    entry = host_lane(root)
    entry['container'] = True
    boost_only(root)
    tools = root / 'stand-ins'
    tools.mkdir()
    (tools / 'docker').write_text('#!/bin/sh\n[ "$1" = image ] && exit 1\n'
                                  'echo "no daemon" >&2\nexit 1\n')
    (tools / 'docker').chmod(0o755)
    environment = harness.b2_environment()
    environment.pop('GITHUB_OUTPUT', None)
    environment['PATH'] = f'{tools}:{environment["PATH"]}'
    result = subprocess.run([sys.executable, str(root / 'tools/ci/matrix.py'), 'lane',
                             json.dumps(entry)], cwd=root, env=environment, capture_output=True,
                            text=True, check=False, timeout=harness.TIMEOUT)
    assert result.returncode == 1, (result.returncode, result.stdout[-2000:], result.stderr)
    build = shlex.join(['docker', 'build', '--tag', matrix.CONTAINER_IMAGE,
                        f'{root.resolve()}/tools/ci/container'])
    assert f'matrix.py: {build} exited 1' in result.stderr, result.stderr
    assert not (root / 'bin/ci').exists() or not list((root / 'bin/ci').iterdir())


CASES = [
    test_the_targets_are_spelled_once,
    test_plan_of_one_library,
    test_plan_with_no_toolset_configured,
    test_plan_of_every_library,
    test_plan_of_a_library_on_emscripten,
    test_whether_a_library_declares_emscripten,
    test_the_docs_and_lint_jobs_install_emsdk_when_a_library_declares_emscripten,
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
    test_the_lanes_name_their_compilers_and_their_container,
    test_a_lane_of_a_library_with_external_dependencies_says_so,
    test_whether_a_library_has_external_dependencies,
    test_the_jobs_install_the_external_dependencies,
    test_a_container_lane_has_its_image_from_the_cache,
    test_a_browser_lane_has_the_pinned_chrome,
    test_a_container_lane_runs_b2_with_no_network,
    test_a_container_lane_whose_image_does_not_build_fails,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('matrix_test', CASES, sys.argv[1:]))
