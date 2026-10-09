#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/drive/drive.py with a stand-in for a driver: a small Python program that records
its process and, as it is told, prints and exits with 0, exits with 3, hangs, or starts a program
that hangs and waits for it. The cases: a driver that passes writes the output and shows what it
printed; one that fails exits with its status, writes nothing and names the test and the command;
a driver that hangs, and a program that hangs, are stopped once the bound has passed, with every
process of their group, and the run fails naming the test, the program and the bound; a run whose
driver leaves its program running leaves nothing either; a SIGKILL of drive.py, alone or with its
group, as b2 stops an action, and a SIGTERM, leave nothing behind; the bound is 30 s by default;
and usage errors exit 2. Each case runs in a scratch directory of its own. Run with the names of
some cases to run only those."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVE = HERE / 'drive.py'

# The stand-in driver: `<python> <stand-in> <mode> <record> <program>`. It records its pid and its
# process group into <record>, and its program's pid once it starts one, then: pass prints ready and
# exits 0; fail exits 3; hang sleeps; program-hangs starts the program, a Python that sleeps, in its
# group, as node's spawnSync does, and waits for it; orphan starts it and exits 0 at once.
STAND_IN = r'''
import json
import subprocess
import sys
import time
import os

mode, record, program = sys.argv[1:4]
recorded = {'pid': os.getpid(), 'pgid': os.getpgid(0)}


def save():
    with open(record + '.tmp', 'w') as file:
        json.dump(recorded, file)
    os.replace(record + '.tmp', record)


save()
if mode == 'pass':
    print(f'driving {program}: ready', flush=True)
    sys.exit(0)
if mode == 'fail':
    print('driving: not ready', flush=True)
    sys.exit(3)
if mode == 'hang':
    while True:
        time.sleep(1)
child = subprocess.Popen([sys.executable, '-c', 'import time\nwhile True: time.sleep(1)'])
recorded['child'] = child.pid
save()
if mode == 'orphan':
    sys.exit(0)
child.wait()
'''

SHOWN = 'webcpp.drive driven in libs/web/test/Jamfile'


def outcome(result: subprocess.CompletedProcess[str]) -> str:
    return f'exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}'


class Run:
    """drive.py over the stand-in in mode, in scratch."""

    def __init__(self, scratch: Path, mode: str) -> None:
        self.stand_in = scratch / 'stand-in driver.py'
        self.stand_in.write_text(STAND_IN)
        self.record = scratch / f'{mode}.json'
        self.output = scratch / f'{mode}.driven'
        self.program = scratch / 'bin/driven program.js'
        self.mode = mode

    def command(self) -> list[str]:
        return [sys.executable, str(self.stand_in), self.mode, str(self.record), str(self.program)]

    def arguments(self, *extra: str) -> list[str]:
        return [sys.executable, str(DRIVE), '--program', SHOWN, '--output', str(self.output),
                *extra, '--', *self.command()]

    def run(self, *extra: str) -> subprocess.CompletedProcess[str]:
        # As b2 starts an action: in a process group of its own.
        return subprocess.run(self.arguments(*extra), capture_output=True, text=True,
                              check=False, timeout=120, preexec_fn=os.setpgrp)

    def recorded(self, holds=lambda record: True, seconds: float = 30) -> dict:
        """What the stand-in recorded, once holds is true of it."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.record.is_file():
                record = json.loads(self.record.read_text())
                if holds(record):
                    return record
            time.sleep(0.05)
        raise AssertionError(f'the stand-in recorded nothing that holds in {seconds} s')


def gone(record: dict, seconds: float = 10) -> None:
    """Asserts that the stand-in's process group and each process it recorded are gone, within
    seconds, and that ps lists none of them: a killed process can stay a zombie for a moment."""
    pids = [record['pid'], *([record['child']] if 'child' in record else [])]
    deadline = time.monotonic() + seconds
    while True:
        listed = subprocess.run(['ps', '-A', '-o', 'pid=,pgid=,stat='], capture_output=True,
                                text=True, check=True).stdout.split('\n')
        alive = [line for line in listed if line.split()[:1] and (
            int(line.split()[0]) in pids or int(line.split()[1]) == record['pgid'])
            and not line.split()[2].startswith('Z')]
        if not alive:
            return
        if time.monotonic() > deadline:
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            raise AssertionError(f'still there: {alive}')
        time.sleep(0.05)


def test_a_driver_that_passes_writes_the_output(scratch: Path) -> None:
    run = Run(scratch, 'pass')
    result = run.run()
    assert result.returncode == 0, outcome(result)
    assert f'driving {run.program}: ready' in result.stdout, outcome(result)
    assert run.output.read_text() == 'driven\n'
    gone(run.recorded())


def test_a_driver_that_fails_exits_with_its_status(scratch: Path) -> None:
    run = Run(scratch, 'fail')
    run.output.write_text('left from an earlier run\n')
    result = run.run()
    assert result.returncode == 3, outcome(result)
    assert 'driving: not ready' in result.stdout, outcome(result)
    assert f'drive: {SHOWN}: the driver of {run.program} exited with 3' in result.stderr, (
        outcome(result))
    assert not run.output.exists()
    gone(run.recorded())


def test_a_hanging_driver_is_stopped_within_its_bound(scratch: Path) -> None:
    run = Run(scratch, 'hang')
    began = time.monotonic()
    result = run.run('--timeout', '2')
    assert time.monotonic() - began < 2 + 5 + 3, time.monotonic() - began
    assert result.returncode == 1, outcome(result)
    assert (f'drive: {SHOWN}: the driver of {run.program} did not end within 2 s; it was stopped '
            'with every process of its group, the program among them') in result.stderr, (
        outcome(result))
    assert not run.output.exists()
    gone(run.recorded())


def test_a_hanging_program_is_stopped_within_its_bound(scratch: Path) -> None:
    run = Run(scratch, 'program-hangs')
    began = time.monotonic()
    result = run.run('--timeout', '2')
    assert time.monotonic() - began < 2 + 5 + 3, time.monotonic() - began
    assert result.returncode == 1, outcome(result)
    assert f'drive: {SHOWN}: the driver of {run.program} did not end within 2 s' in (
        result.stderr), outcome(result)
    gone(run.recorded(lambda record: 'child' in record))


def test_a_program_the_driver_leaves_running_is_stopped(scratch: Path) -> None:
    # The driver passes, and leaves its program running: nothing of its group outlives the run.
    run = Run(scratch, 'orphan')
    result = run.run()
    assert result.returncode == 0, outcome(result)
    gone(run.recorded(lambda record: 'child' in record))


def test_a_killed_or_stopped_run_leaves_nothing(scratch: Path) -> None:
    # A SIGKILL, which drive.py cannot answer, to drive.py alone or to its process group, as b2
    # sends to an action it stops (b2 -l), and a SIGTERM leave nothing: the keeper sees drive.py
    # gone and kills its group.
    for name, kill, number in (('alone', os.kill, signal.SIGKILL),
                               ('group', os.killpg, signal.SIGKILL),
                               ('terminated', os.kill, signal.SIGTERM)):
        run = Run(scratch, 'program-hangs')
        run.record = scratch / f'{name}.json'
        process = subprocess.Popen(run.arguments(), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, preexec_fn=os.setpgrp)
        recorded = run.recorded(lambda record: 'child' in record)
        kill(process.pid, number)
        process.communicate(timeout=60)
        assert process.returncode == -number, (name, process.returncode)
        gone(recorded)


def test_the_bound_is_30_seconds_by_default(scratch: Path) -> None:
    result = subprocess.run([sys.executable, str(DRIVE), '--help'], capture_output=True,
                            text=True, check=False)
    assert result.returncode == 0, outcome(result)
    assert '(30 by default)' in ' '.join(result.stdout.split()), outcome(result)
    run = Run(scratch, 'hang')
    process = subprocess.Popen(run.arguments(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, preexec_fn=os.setpgrp)
    recorded = run.recorded()
    try:
        process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError('drive.py stopped its driver before 30 s')
    process.kill()
    process.communicate()
    gone(recorded)


def test_usage_errors_exit_2(scratch: Path) -> None:
    run = Run(scratch, 'pass')
    for extra, words, message in (
        ((), [], 'drive.py: error: no driver to run'),
        (('--timeout', '0'), None, 'drive.py: error: --timeout 0 is not a number of seconds'),
        (('--timeout', 'soon'), None, 'drive.py: error: --timeout soon is not a number'),
    ):
        arguments = run.arguments(*extra)
        if words is not None:
            arguments = arguments[:arguments.index('--') + 1] + words
        result = subprocess.run(arguments, capture_output=True, text=True, check=False)
        assert result.returncode == 2, (extra, outcome(result))
        assert message in result.stderr, (extra, outcome(result))
    assert not run.record.exists()


CASES = [
    test_a_driver_that_passes_writes_the_output,
    test_a_driver_that_fails_exits_with_its_status,
    test_a_hanging_driver_is_stopped_within_its_bound,
    test_a_hanging_program_is_stopped_within_its_bound,
    test_a_program_the_driver_leaves_running_is_stopped,
    test_a_killed_or_stopped_run_leaves_nothing,
    test_the_bound_is_30_seconds_by_default,
    test_usage_errors_exit_2,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'drive_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='webcpp drive ') as scratch:
            case(Path(scratch))
        print(f'{case.__name__}: ok')
    print('drive_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
