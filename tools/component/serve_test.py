#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/component/serve.py with a stand-in for wasmtime: a small Python program, given as
--wasmtime, that serves fixed answers on the address it is given and says so as wasmtime 47.0.3
does, so that the runner is checked without a component. The stand-in reads what to do from the
file given as the component: when to say it serves, whether to answer, to ignore SIGTERM or to
start a child in its process group, and where to record its process, its port and the requests
it got, with when. The cases: the transcript's format; a difference exits 1 with a unified diff
and no output; two runs at once take two ports; nothing is sent before the server says it
serves; a server that never says so exits 2 within the timeout, and one that exits first exits 2
with its standard error; a server that ignores SIGTERM is killed with its whole group, after a
pass and after a failure; an interrupted run stops the server; a run whose answer never comes
ends by itself within its bound and stops it; and usage errors exit 2. Each case runs in a scratch
directory of its own. Run with the names of some cases to run only those."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVE = HERE / 'serve.py'

# The stand-in for wasmtime: `<stand-in> serve <flags> --addr <host>:0 <component>`, where the
# component is a JSON file of settings: delay, the seconds between listening and saying so; meet
# and meeting, a directory and a number of stand-ins, none of which says it serves before that
# many listen; silent, never to say it; exit, to exit with that status first, as a wasmtime that
# cannot bind; hang, never to answer; ignore_term; child, to start a child in its group; and
# unended, to end no body with a line break. It records into settings['record'] its pid, its
# process group, its session, the flags it was given, its port, when it said it serves, and each
# request with when it came. It answers as answers.cpp of tools/test/fixtures/component_demo does:
# 404 for /missing, else 200, with the method and the target in the body (none for HEAD), the
# method in X-Method, and the headers wasmtime adds, Date always and Transfer-Encoding: chunked
# with a body. Its headers are not in lower case, which the transcript writes them in.
STAND_IN = r'''#!/usr/bin/env python3
import json
import os
import signal
import socket
import subprocess
import sys
import time
from email.utils import formatdate
from http import HTTPStatus

arguments = sys.argv[1:]
assert arguments[0] == 'serve', arguments
flags = arguments[1:arguments.index('--addr')]
host, port = arguments[arguments.index('--addr') + 1].rsplit(':', 1)
settings = json.loads(open(arguments[-1]).read())
record = {'pid': os.getpid(), 'pgid': os.getpgid(0), 'sid': os.getsid(0), 'flags': flags,
          'requests': []}


def save():
    with open(settings['record'] + '.part', 'w') as file:
        json.dump(record, file)
    os.replace(settings['record'] + '.part', settings['record'])


if settings.get('ignore_term'):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if settings.get('child'):
    record['child'] = subprocess.Popen(['sleep', '600']).pid
if 'exit' in settings:
    save()
    print('Error: Address already in use (os error 48)', file=sys.stderr)
    sys.exit(settings['exit'])
server = socket.socket()
server.bind((host, int(port)))
server.listen()
record['port'] = server.getsockname()[1]
save()
if settings.get('silent'):
    time.sleep(600)
if 'meet' in settings:
    # Waits until as many stand-ins as the setting says listen, before any of them says so.
    open(os.path.join(settings['meet'], str(os.getpid())), 'w').close()
    while len(os.listdir(settings['meet'])) < settings['meeting']:
        time.sleep(0.01)
time.sleep(settings.get('delay', 0))
record['said_at'] = time.time()
save()
print(f'Serving HTTP on http://{host}:{record["port"]}/', file=sys.stderr, flush=True)
while True:
    connection, _ = server.accept()
    data = b''
    while b'\r\n\r\n' not in data:
        chunk = connection.recv(4096)
        if not chunk:
            break
        data += chunk
    if b'\r\n\r\n' not in data:
        connection.close()
        continue
    method, target, _ = data.split(b'\r\n', 1)[0].decode().split(' ')
    record['requests'].append({'method': method, 'target': target, 'at': time.time()})
    save()
    if settings.get('hang'):
        time.sleep(600)
    status = HTTPStatus.NOT_FOUND if target == '/missing' else HTTPStatus.OK
    ending = '' if settings.get('unended') else '\n'
    body = b'' if method == 'HEAD' else f'{method} {target}{ending}'.encode()
    head = [f'HTTP/1.1 {status.value} {status.phrase}', f'X-Method: {method}',
            'Content-Type: text/plain', f'Date: {formatdate(usegmt=True)}']
    if method != 'HEAD':
        head.append('Transfer-Encoding: chunked')
    answer = ('\r\n'.join(head) + '\r\n\r\n').encode()
    if method != 'HEAD':
        answer += f'{len(body):x}\r\n'.encode() + body + b'\r\n0\r\n\r\n'
    connection.sendall(answer)
    connection.close()
'''

REQUESTS = 'GET /v1/greeting?name=ana\nHEAD /\n\nPOST /missing\n'

# The transcript of REQUESTS, as the stand-in answers them.
TRANSCRIPT = ('$ curl -i -X GET http://localhost:8080/v1/greeting?name=ana\n'
              'HTTP/1.1 200 OK\n'
              'content-type: text/plain\n'
              'x-method: GET\n'
              '\n'
              'GET /v1/greeting?name=ana\n'
              '\n'
              '$ curl -i -X HEAD http://localhost:8080/\n'
              'HTTP/1.1 200 OK\n'
              'content-type: text/plain\n'
              'x-method: HEAD\n'
              '\n'
              '\n'
              '$ curl -i -X POST http://localhost:8080/missing\n'
              'HTTP/1.1 404 Not Found\n'
              'content-type: text/plain\n'
              'x-method: POST\n'
              '\n'
              'POST /missing\n')


class Run:
    """One run of serve.py in a scratch directory, with the stand-in's settings."""

    def __init__(self, scratch: Path, name: str, settings: dict | None = None,
                 requests: str = REQUESTS, expected: str = TRANSCRIPT) -> None:
        self.directory = scratch / name
        self.directory.mkdir()
        self.record = self.directory / 'record.json'
        self.component = self.directory / 'component.json'
        self.component.write_text(json.dumps({**(settings or {}), 'record': str(self.record)}))
        self.requests = self.directory / 'answers.requests'
        self.requests.write_text(requests)
        self.expected = self.directory / 'answers.expected'
        self.expected.write_text(expected)
        self.output = self.directory / 'answers.served'
        self.stand_in = scratch / 'stand-in'
        if not self.stand_in.exists():
            self.stand_in.write_text(STAND_IN.replace('/usr/bin/env python3', sys.executable, 1))
            self.stand_in.chmod(0o755)

    def arguments(self, *extra: str, flags: str = '-S cli') -> list[str]:
        return [sys.executable, str(SERVE), '--wasmtime', str(self.stand_in), f'--flags={flags}',
                '--component', str(self.component), '--requests', str(self.requests),
                '--expected', str(self.expected), '--output', str(self.output), *extra]

    def run(self, *extra: str, flags: str = '-S cli') -> subprocess.CompletedProcess[str]:
        return subprocess.run(self.arguments(*extra, flags=flags), capture_output=True, text=True,
                              check=False, timeout=120)

    def start(self, *extra: str) -> subprocess.Popen[str]:
        return subprocess.Popen(self.arguments(*extra), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

    def recorded(self) -> dict:
        return json.loads(self.record.read_text())

    def wait_for_record(self, holds: Callable[[dict], bool], seconds: float = 30) -> dict:
        """The stand-in's record, once it holds."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.record.exists() and holds(self.recorded()):
                return self.recorded()
            time.sleep(0.05)
        raise AssertionError(f'the stand-in never recorded what was waited for: {self.record}')


def outcome(result: subprocess.CompletedProcess[str]) -> str:
    return f'exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}'


def gone(pids: list[int], pgid: int, seconds: float = 5) -> None:
    """Asserts that the process group pgid, and each of pids, is gone, within seconds: a killed
    process can stay a zombie for a moment, until whoever is its parent reaps it."""
    deadline = time.monotonic() + seconds
    while True:
        alive = []
        try:
            os.killpg(pgid, 0)
            alive.append(f'group {pgid}')
        except ProcessLookupError:
            pass
        except PermissionError:
            alive.append(f'group {pgid} (a zombie)')
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive.append(f'pid {pid}')
            except ProcessLookupError:
                pass
            except PermissionError:
                alive.append(f'pid {pid} (a zombie)')
        if not alive:
            return
        if time.monotonic() > deadline:
            raise AssertionError(f'still there: {", ".join(alive)}')
        time.sleep(0.05)


def test_transcript_format(scratch: Path) -> None:
    # Headers in lower case and sorted, without the host's date and transfer-encoding; a HEAD
    # answer without a body; an empty line between two requests, skipped in the requests.
    run = Run(scratch, 'format')
    result = run.run(flags='-S cli,p3 -W component-model-async')
    assert result.returncode == 0, outcome(result)
    assert result.stdout == '' and result.stderr == '', outcome(result)
    assert run.output.read_bytes() == TRANSCRIPT.encode()
    recorded = run.recorded()
    # The flags reach wasmtime serve as words, before --addr.
    assert recorded['flags'] == ['-S', 'cli,p3', '-W', 'component-model-async'], recorded
    assert [(request['method'], request['target']) for request in recorded['requests']] == [
        ('GET', '/v1/greeting?name=ana'), ('HEAD', '/'), ('POST', '/missing')], recorded
    # wasmtime runs in a process group of its own, in the session of serve.py.
    assert recorded['pgid'] == recorded['pid'], recorded
    assert recorded['sid'] == os.getsid(0), recorded
    gone([recorded['pid']], recorded['pgid'])
    # A body that does not end with a line break is ended before the empty line that separates
    # two requests; the last one stays as it came.
    unended = Run(scratch, 'unended', {'unended': True}, requests='GET /a\nGET /b\n',
                  expected=('$ curl -i -X GET http://localhost:8080/a\n'
                            'HTTP/1.1 200 OK\ncontent-type: text/plain\nx-method: GET\n\n'
                            'GET /a\n\n'
                            '$ curl -i -X GET http://localhost:8080/b\n'
                            'HTTP/1.1 200 OK\ncontent-type: text/plain\nx-method: GET\n\n'
                            'GET /b'))
    result = unended.run()
    assert result.returncode == 0, outcome(result)


def test_difference_exits_1_with_a_diff(scratch: Path) -> None:
    run = Run(scratch, 'differs', expected=TRANSCRIPT.replace('404 Not Found', '405 Nope'))
    run.output.write_text('left over from an earlier run\n')
    result = run.run()
    assert result.returncode == 1, outcome(result)
    assert f'the transcript differs from {run.expected}' in result.stdout, outcome(result)
    for line in (f'--- {run.expected}', '+++ the transcript', '-HTTP/1.1 405 Nope',
                 '+HTTP/1.1 404 Not Found'):
        assert line in result.stdout.splitlines(), (line, outcome(result))
    # What wasmtime wrote follows the diff: its standard error names a trap.
    assert "\nwasmtime's standard error:\nServing HTTP on http://127.0.0.1:" in result.stdout, (
        outcome(result))
    assert not run.output.exists()
    gone([run.recorded()['pid']], run.recorded()['pgid'])
    # A missing line break at the end is a difference too, and the diff says so.
    run = Run(scratch, 'unended', expected=TRANSCRIPT.rstrip('\n'))
    result = run.run()
    assert result.returncode == 1, outcome(result)
    assert '\\ No newline at end of file' in result.stdout, outcome(result)


def test_two_runs_at_once_take_two_ports(scratch: Path) -> None:
    # Neither stand-in says it serves before both listen: the two servers are up at once.
    meet = scratch / 'meet'
    meet.mkdir()
    runs = [Run(scratch, name, {'meet': str(meet), 'meeting': 2}) for name in ('first', 'second')]
    started = [run.start() for run in runs]
    for run, process in zip(runs, started):
        stdout, stderr = process.communicate(timeout=60)
        assert process.returncode == 0, (stdout, stderr)
        assert run.output.read_bytes() == TRANSCRIPT.encode()
    first, second = (run.recorded() for run in runs)
    assert first['port'] != second['port'], (first, second)
    assert len(list(meet.iterdir())) == 2


def test_nothing_is_sent_before_the_server_says_it_serves(scratch: Path) -> None:
    # The stand-in listens at once, and says so only two seconds later.
    run = Run(scratch, 'late', {'delay': 2})
    result = run.run()
    assert result.returncode == 0, outcome(result)
    recorded = run.recorded()
    assert recorded['requests'][0]['at'] >= recorded['said_at'], recorded


def test_a_server_that_never_serves_exits_2(scratch: Path) -> None:
    run = Run(scratch, 'silent', {'silent': True, 'child': True})
    began = time.monotonic()
    result = run.run('--timeout', '2')
    took = time.monotonic() - began
    assert result.returncode == 2, outcome(result)
    assert 'wasmtime did not say it serves within 2 s' in result.stderr, outcome(result)
    # Two seconds of waiting, and the stop, at most GRACE seconds more.
    assert took < 2 + 5 + 3, took
    recorded = run.recorded()
    gone([recorded['pid'], recorded['child']], recorded['pgid'])
    # One that exits first is named with its standard error, at once.
    run = Run(scratch, 'exits', {'exit': 1})
    began = time.monotonic()
    result = run.run()
    assert result.returncode == 2, outcome(result)
    assert 'wasmtime exited with status 1 before it served' in result.stderr, outcome(result)
    assert 'Address already in use' in result.stderr, outcome(result)
    assert time.monotonic() - began < 10
    # And one that cannot be started.
    run = Run(scratch, 'missing')
    arguments = run.arguments()
    arguments[arguments.index('--wasmtime') + 1] = str(scratch / 'no wasmtime here')
    result = subprocess.run(arguments, capture_output=True, text=True, check=False, timeout=60)
    assert result.returncode == 2, outcome(result)
    assert f'cannot start {scratch / "no wasmtime here"}' in result.stderr, outcome(result)


def test_a_server_that_ignores_sigterm_is_killed(scratch: Path) -> None:
    # After a pass, and after a failure, its whole group is gone: the child it started too.
    for name, expected, status in (('passes', TRANSCRIPT, 0), ('fails', 'other\n', 1)):
        run = Run(scratch, name, {'ignore_term': True, 'child': True}, expected=expected)
        began = time.monotonic()
        result = run.run()
        assert result.returncode == status, outcome(result)
        # SIGTERM is ignored, so serve.py waits its GRACE seconds before SIGKILL.
        assert 5 <= time.monotonic() - began < 30
        recorded = run.recorded()
        gone([recorded['pid'], recorded['child']], recorded['pgid'])


def test_an_interrupted_run_stops_the_server(scratch: Path) -> None:
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        # The stand-in never answers, so the run is waiting on it when the signal comes.
        run = Run(scratch, number.name, {'hang': True, 'child': True})
        process = run.start()
        recorded = run.wait_for_record(lambda record: bool(record['requests']))
        process.send_signal(number)
        stdout, stderr = process.communicate(timeout=60)
        assert process.returncode == 128 + number, (number, stdout, stderr)
        assert f'stopped by {number.name}' in stderr, (number, stderr)
        gone([recorded['pid'], recorded['child']], recorded['pgid'])
        assert not run.output.exists()


def test_a_run_bounds_itself(scratch: Path) -> None:
    # An answer that never comes fails the run once the timeout has passed, naming the request,
    # and stops the server: a run whose b2 is gone ends by itself.
    run = Run(scratch, 'hangs', {'hang': True, 'child': True})
    began = time.monotonic()
    result = run.run('--timeout', '2')
    assert result.returncode == 1, outcome(result)
    assert 'GET /v1/greeting?name=ana got no answer' in result.stderr, outcome(result)
    assert "wasmtime's standard error:\nServing HTTP on http://127.0.0.1:" in result.stderr, (
        outcome(result))
    assert time.monotonic() - began < 2 + 5 + 3
    recorded = run.recorded()
    gone([recorded['pid'], recorded['child']], recorded['pgid'])


def test_usage_errors_exit_2(scratch: Path) -> None:
    run = Run(scratch, 'usage', requests='GET /\nGET\n')
    result = run.run()
    assert result.returncode == 2, outcome(result)
    assert f'{run.requests}:2: not `<METHOD> <target>`: GET' in result.stderr, outcome(result)
    assert not run.record.exists(), 'nothing was served'
    for requests, named in (('\n\n', 'holds no request'), ('GET / extra\n', 'not `<METHOD>'),
                            ('G(T /\n', 'not `<METHOD>')):
        run.requests.write_text(requests)
        result = run.run()
        assert result.returncode == 2 and named in result.stderr, (requests, outcome(result))
    run.requests.write_text(REQUESTS)
    for path, named in ((run.expected, 'no expected transcript'),
                        (run.component, 'no component')):
        path.unlink()
        result = run.run()
        assert result.returncode == 2 and named in result.stderr, (named, outcome(result))
    run.requests.unlink()
    result = run.run()
    assert result.returncode == 2, outcome(result)
    result = subprocess.run([sys.executable, str(SERVE), '--wasmtime', 'wasmtime'],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 2 and '--flags' in result.stderr, outcome(result)


CASES = [
    test_transcript_format,
    test_difference_exits_1_with_a_diff,
    test_two_runs_at_once_take_two_ports,
    test_nothing_is_sent_before_the_server_says_it_serves,
    test_a_server_that_never_serves_exits_2,
    test_a_server_that_ignores_sigterm_is_killed,
    test_an_interrupted_run_stops_the_server,
    test_a_run_bounds_itself,
    test_usage_errors_exit_2,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'serve_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='webcpp serve ') as scratch:
            case(Path(scratch))
        print(f'{case.__name__}: ok')
    print('serve_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
