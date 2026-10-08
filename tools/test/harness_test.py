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
only those."""

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


CASES = [
    test_a_timeout_stops_every_action,
    test_lanes_start_on_bin_and_a_failure_stops_the_others,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('harness_test', CASES, sys.argv[1:]))
