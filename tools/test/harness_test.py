#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks harness.py: a b2 run that outlasts its timeout raises subprocess.TimeoutExpired, and
leaves none of its actions running. b2 gives each action a process group of its own, so killing
b2's group alone would leave them running. Run with the names of some cases to run only those."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import harness

# A test that writes its pid to PID_FILE, then waits far longer than any case.
SLEEPER = ('#include <cstdio>\n'
           '#include <unistd.h>\n'
           '\n'
           'int main() {\n'
           '    std::FILE* file = std::fopen("PID_FILE", "w");\n'
           '    std::fprintf(file, "%d\\n", static_cast<int>(getpid()));\n'
           '    std::fclose(file);\n'
           '    sleep(600);\n'
           '}\n')

# Long enough for b2 to build the sleeper and start it, on a loaded machine too.
TIMEOUT = 20


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


def test_a_timeout_stops_every_action(root):
    pid_file = root / 'sleeper.pid'
    harness.add_library(root, 'sleeper',
                        'import webcpp ;\n'
                        '\n'
                        'webcpp.run sleeper : sleeper.cpp ;\n',
                        {'sleeper.cpp': SLEEPER.replace('PID_FILE', str(pid_file))})
    try:
        result = harness.run_b2(root, 'libs/sleeper/test', timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError(f'b2 ended before its timeout: {result.stdout[-4000:]}')
    assert pid_file.is_file(), 'the sleeper did not start before the timeout'
    pid = int(pid_file.read_text())
    if alive(pid):
        os.kill(pid, signal.SIGKILL)
        raise AssertionError(f'the action {pid} outlived the timeout of its b2 run')


CASES = [
    test_a_timeout_stops_every_action,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('harness_test', CASES, sys.argv[1:]))
