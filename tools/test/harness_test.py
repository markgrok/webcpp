#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks harness.py: a b2 run that outlasts its timeout raises subprocess.TimeoutExpired, and
leaves none of its actions running. b2 gives each action a process group of its own, so killing
b2's group alone would leave them running. Lanes run at once start on a bin that exists, and a
lane that fails stops the others, with what they started. Run with the names of some cases to run
only those. b2 gets one environment, without CPATH and its kin, however it is started, with
Emscripten's cache the shell's, else the run's own; and a scratch superproject gets the emsdk it
is given."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import harness

# A test that, when SLEEPS names a variable of its environment, writes its pid to PID_FILE, then
# waits far longer than any case; without it, it passes at once.
SLEEPER = ('#include <cstdio>\n'
           '#include <cstdlib>\n'
           '#include <unistd.h>\n'
           '\n'
           'int main() {\n'
           '    if (std::getenv("SLEEPS") == nullptr) {\n'
           '        return 0;\n'
           '    }\n'
           '    std::FILE* file = std::fopen("PID_FILE", "w");\n'
           '    std::fprintf(file, "%d\\n", static_cast<int>(getpid()));\n'
           '    std::fclose(file);\n'
           '    sleep(600);\n'
           '}\n')

# The variable that makes the sleeper sleep.
SLEEPS = 'WEBCPP_HARNESS_TEST_SLEEPS'

# Long enough for b2 to start the sleeper, already built, on a loaded machine too.
TIMEOUT = 20

# What b2 writes when it runs a test, which a later run reads as the test already passed.
RUN_RECORDS = ('.output', '.run', '.test')


def alive(pid: int) -> bool:
    """Whether the process pid exists, waiting up to ten seconds for a killed one to be reaped."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        time.sleep(0.1)
    return True


def forget_the_run(root: Path) -> None:
    """Removes what records that the sleeper ran, so that the next b2 run runs it again, without
    building it again."""
    records = [path for path in (root / 'bin').rglob('sleeper*')
               if path.is_file() and path.suffix in RUN_RECORDS]
    assert records, f'b2 recorded no run of the sleeper under {root / "bin"}'
    for path in records:
        path.unlink()


def test_a_timeout_stops_every_action(root):
    """The sleeper is built in a first run, which has no timeout, so that the timeout of the
    second covers starting it alone, and a slow compiler cannot make the case fail."""
    pid_file = root / 'sleeper.pid'
    harness.add_library(root, 'sleeper',
                        'import webcpp ;\n'
                        '\n'
                        'webcpp.run sleeper : sleeper.cpp ;\n',
                        {'sleeper.cpp': SLEEPER.replace('SLEEPS', SLEEPS)
                                               .replace('PID_FILE', str(pid_file))})
    built = harness.run_b2(root, 'libs/sleeper/test', env_extra={SLEEPS: None})
    harness.expect(built, True, '**passed**')
    forget_the_run(root)
    try:
        result = harness.run_b2(root, 'libs/sleeper/test', env_extra={SLEEPS: '1'},
                                timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError(f'b2 ended before its timeout: {result.stdout[-4000:]}')
    assert pid_file.is_file(), 'the sleeper did not start before the timeout'
    pid = int(pid_file.read_text())
    if alive(pid):
        os.kill(pid, signal.SIGKILL)
        raise AssertionError(f'the action {pid} outlived the timeout of its b2 run')


# A stand-in for b2, first on PATH: it fails when the directory it runs in has no bin, as two b2
# runs at once may when neither finds bin and both make it; with --fail it fails after a moment;
# with --sleep <file> it starts a child, as an action, writes the child's pid to the file, and
# waits far longer than any case; otherwise it says it is done.
FAKE_B2 = """#!{python}
import os
import subprocess
import sys
import time

arguments = sys.argv[1:]
if not os.path.isdir('bin'):
    print('there is no bin')
    sys.exit(9)
if '--fail' in arguments:
    time.sleep(1)
    print('failed')
    sys.exit(3)
if '--sleep' in arguments:
    child = subprocess.Popen(['sleep', '600'])
    with open(arguments[arguments.index('--sleep') + 1], 'w') as pid:
        pid.write(str(child.pid))
    time.sleep(600)
print('done')
"""


def test_lanes_start_on_bin_and_a_failure_stops_the_others(root):
    tools = root / 'fake tools'
    tools.mkdir()
    (tools / 'b2').write_text(FAKE_B2.format(python=sys.executable))
    (tools / 'b2').chmod(0o755)
    path = {'PATH': f'{tools}{os.pathsep}{os.environ["PATH"]}'}
    # A scratch superproject has no bin: run_lanes makes it before any lane starts.
    assert not (root / 'bin').exists()
    ended = harness.run_lanes(root, {'one': ('--ok',), 'two': ('--ok',)}, env_extra=path)
    assert {name: (result.returncode, result.stdout) for name, result in ended.items()} == {
        'one': (0, 'done\n'), 'two': (0, 'done\n')}, ended
    # A lane that fails stops the one still running, the child it started included, at once:
    # the failure comes first, and the case does not wait for the sleeper's ten minutes.
    pid_file = root / 'child.pid'
    began = time.monotonic()
    ended = harness.run_lanes(root, {'sleeps': ('--sleep', str(pid_file)), 'fails': ('--fail',)},
                              env_extra=path, timeout=120)
    assert time.monotonic() - began < 60, time.monotonic() - began
    assert list(ended) == ['fails', 'sleeps'], ended
    assert ended['fails'].returncode == 3 and ended['fails'].stdout == 'failed\n', ended
    assert ended['sleeps'].returncode != 0, ended
    assert pid_file.is_file(), 'the sleeping lane did not start its child'
    child = int(pid_file.read_text())
    if alive(child):
        os.kill(child, signal.SIGKILL)
        raise AssertionError(f'the child {child} of the stopped lane outlived it')


# A b2 that prints the variables of its environment that a case names in SHOWN, one per line,
# NAME=value, or NAME unset.
ENVIRONMENT_B2 = """#!{python}
import os
for name in os.environ['SHOWN'].split():
    print(f'{{name}}={{os.environ[name]}}' if name in os.environ else f'{{name}} unset')
"""


def test_every_b2_gets_one_environment(root):
    # b2 runs without CPATH and its kin, which the Jamroot refuses, and with what env_extra adds,
    # a value of None removing its variable: b2_environment makes that environment, and run_b2,
    # start_b2 and so run_lanes give b2 that one.
    tools = root / 'fake tools'
    tools.mkdir()
    (tools / 'b2').write_text(ENVIRONMENT_B2.format(python=sys.executable))
    (tools / 'b2').chmod(0o755)
    shown = 'CPATH C_INCLUDE_PATH WEBCPP_KEPT WEBCPP_REMOVED WEBCPP_ADDED'
    extra = {'PATH': f'{tools}{os.pathsep}{os.environ["PATH"]}', 'SHOWN': shown,
             'WEBCPP_REMOVED': None, 'WEBCPP_ADDED': 'added'}
    saved = dict(os.environ)
    os.environ.update(CPATH='/somewhere', C_INCLUDE_PATH='/elsewhere', WEBCPP_KEPT='kept',
                      WEBCPP_REMOVED='removed')
    try:
        environment = harness.b2_environment(extra)
        printed = [harness.run_b2(root, env_extra=extra).stdout]
        started = harness.start_b2(root, env_extra=extra)
        printed.append(started.communicate()[0])
        printed += [result.stdout for result in harness.run_lanes(root, {'lane': ()},
                                                                  env_extra=extra).values()]
    finally:
        os.environ.clear()
        os.environ.update(saved)
    assert {name: environment.get(name) for name in shown.split()} == {
        'CPATH': None, 'C_INCLUDE_PATH': None, 'WEBCPP_KEPT': 'kept', 'WEBCPP_REMOVED': None,
        'WEBCPP_ADDED': 'added'}, environment
    expected = ('CPATH unset\nC_INCLUDE_PATH unset\nWEBCPP_KEPT=kept\nWEBCPP_REMOVED unset\n'
                'WEBCPP_ADDED=added\n')
    assert printed == [expected] * 3, printed


def test_emscripten_cache_is_the_shells_else_one_per_run(root):
    # Emscripten writes its cache where EM_CACHE names, else inside the emsdk, which is read-only.
    # Every b2 gets the cache the shell names, as the CI's emsdk action names the one it restores
    # with its system libraries built, so that no test builds them again; else the run's own,
    # beside the run's scratch superprojects, made once and shared by the cases. Either is shared,
    # since Emscripten locks it, and named by its resolved path. Emscripten's sanity check, which a
    # fresh cache would print, is skipped. env_extra may name another cache.
    tools = root / 'fake tools'
    tools.mkdir()
    (tools / 'b2').write_text(ENVIRONMENT_B2.format(python=sys.executable))
    (tools / 'b2').chmod(0o755)
    extra = {'PATH': f'{tools}{os.pathsep}{os.environ["PATH"]}',
             'SHOWN': 'EM_CACHE EMCC_SKIP_SANITY_CHECK'}
    shells = root / 'shell cache'
    linked = root / 'shell cache link'
    linked.symlink_to(shells)
    saved = os.environ.get('EM_CACHE')
    try:
        os.environ.pop('EM_CACHE', None)
        own = harness.emscripten_cache()
        assert own == harness.emscripten_cache() and own.is_dir(), own
        assert own.parent == root.parent.resolve() and own.name == 'emscripten-cache', (own, root)
        printed = harness.run_b2(root, env_extra=extra).stdout
        assert printed == f'EM_CACHE={own}\nEMCC_SKIP_SANITY_CHECK=1\n', printed
        # The shell's, by its resolved path, made when it is not there yet.
        os.environ['EM_CACHE'] = str(linked)
        assert harness.emscripten_cache() == shells.resolve() and shells.is_dir(), shells
        printed = harness.run_b2(root, env_extra=extra).stdout
        given = harness.run_b2(root, env_extra={**extra, 'EM_CACHE': '/elsewhere'}).stdout
    finally:
        if saved is None:
            os.environ.pop('EM_CACHE', None)
        else:
            os.environ['EM_CACHE'] = saved
    assert printed == f'EM_CACHE={shells.resolve()}\nEMCC_SKIP_SANITY_CHECK=1\n', printed
    assert given == 'EM_CACHE=/elsewhere\nEMCC_SKIP_SANITY_CHECK=1\n', given


def test_link_emsdk_links_the_emsdk_it_is_given(root):
    # A scratch superproject gets the emsdk in its .local: $EMSDK_ROOT, else this checkout's
    # .local/emsdk, which must hold upstream/emscripten/em++, or the case stops naming it.
    given = root / 'given emsdk'
    (given / 'upstream/emscripten').mkdir(parents=True)
    (given / 'upstream/emscripten/em++').write_text('')
    empty = root / 'empty emsdk'
    empty.mkdir()
    saved = os.environ.get('EMSDK_ROOT')
    try:
        os.environ['EMSDK_ROOT'] = str(given)
        harness.link_emsdk(root)
        assert (root / '.local/emsdk').resolve() == given.resolve()
        assert (root / '.local/emsdk/upstream/emscripten/em++').is_file()
        (root / '.local/emsdk').unlink()
        os.environ['EMSDK_ROOT'] = str(empty)
        try:
            harness.link_emsdk(root)
        except RuntimeError as error:
            assert str(error) == (f'no upstream/emscripten/em++ in {empty}: install emsdk there, '
                                  'or set EMSDK_ROOT'), error
        else:
            raise AssertionError('link_emsdk linked an emsdk without em++')
        assert not (root / '.local/emsdk').exists()
    finally:
        if saved is None:
            os.environ.pop('EMSDK_ROOT', None)
        else:
            os.environ['EMSDK_ROOT'] = saved


CASES = [
    test_every_b2_gets_one_environment,
    test_emscripten_cache_is_the_shells_else_one_per_run,
    test_link_emsdk_links_the_emsdk_it_is_given,
    test_a_timeout_stops_every_action,
    test_lanes_start_on_bin_and_a_failure_stops_the_others,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('harness_test', CASES, sys.argv[1:]))
