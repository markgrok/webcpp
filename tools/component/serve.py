#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Serves one HTTP component with wasmtime, sends it requests and compares the transcript of its
answers with the committed one.

Usage: serve.py [--wasmtime PATH] [--program NAME] --flags WORDS --component WASM
                --requests FILE --expected FILE --output FILE [--timeout SECONDS]

wasmtime is --wasmtime, which webcpp.serve gives as -sWASMTIME=<path> was given, else wasmtime on
PATH: it is looked up here, when the test runs, so that a build or a dry run that runs no served
test needs none. --program names the served program in a message, as webcpp.serve does ("<source>
in <Jamfile>"), else the component does.

wasmtime runs as `wasmtime serve WORDS --addr 127.0.0.1:0 WASM`, with its standard input
/dev/null, in a process group of its own and in the session of this script, which b2 runs it in:
what stops b2's session stops it too. Port 0 makes the system choose a free port, which wasmtime
names on its standard error when it listens; nothing is sent before that line, and two runs at
once never share a port.

Each line of the requests file is `<METHOD> <target>`; an empty line is skipped. Each request is
sent with http.client, without a body, on a connection of its own. The transcript holds, per
request: the line `$ curl -i -X <METHOD> http://localhost:8080<target>`, then `HTTP/1.1 <status>
<reason>`, the response's headers in lower case, `<name>: <value>`, sorted, but for those wasmtime
adds to every response (HOST_HEADERS), an empty line, and the body as it came. Two requests are
separated by an empty line, after a line break that ends the body when it does not end with one.
The host and the port are written fixed, so that one transcript holds on every machine and lane.

wasmtime is stopped in every outcome: an answer missing, an exception, SIGINT, SIGTERM or SIGHUP.
Its group is sent SIGTERM, and SIGKILL after GRACE seconds, so that nothing it started is left
either. The whole run is bounded, by --timeout (30 s by default) for the line that says it
serves and for each answer, so that a run nobody waits for any longer, its b2 gone, still ends
and stops wasmtime. A SIGKILL of this script itself is the one end it cannot answer, and it leaves
wasmtime running: b2 never sends one to an action, and a harness that stops a run by killing its
session, the way tools/test does, kills wasmtime with it.

Exit 0 when the transcript equals the expected file byte for byte, which the output file then
holds; 1 when it does not, with a unified diff, or when an answer does not come, either with
wasmtime's standard error; 2 on a usage error, when wasmtime is not found, or when it does not
start or does not say it serves, with its standard error; 128 plus the signal's number when one
stops the run, whatever else happened. On any failure the output file is not left behind.
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import http.client
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

# The headers wasmtime 47.0.3 adds to a response, whatever the component sets, measured with
# `wasmtime serve` on a component whose answers carry content-type and x-method only: date on
# every response, and transfer-encoding: chunked on every response that has a body (all but the
# answer to HEAD).
HOST_HEADERS = frozenset({'date', 'transfer-encoding'})

# What a transcript says the server is: one host and port on every machine.
SHOWN_ORIGIN = 'http://localhost:8080'

# The line in which wasmtime 47.0.3 says it listens, on its standard error:
# `Serving HTTP on http://127.0.0.1:53187/`.
SERVING = re.compile(r'Serving HTTP on http://([0-9.]+):([0-9]+)/')

# Seconds between SIGTERM and SIGKILL.
GRACE = 5

# A method, as RFC 9110 writes a token.
METHOD = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")

ADDRESS = '127.0.0.1:0'


class UsageError(Exception):
    """A command line or an input this script cannot run with."""


class Stopped(BaseException):
    """A signal ended the run; a BaseException, so that no handler of Exception takes it."""

    def __init__(self, number: int) -> None:
        super().__init__(signal.Signals(number).name)
        self.number = number


class Failed(Exception):
    """The run failed with an exit status, for the reason given."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status


@dataclass
class Server:
    """wasmtime serve, started, and what it wrote."""

    process: subprocess.Popen[bytes]
    readers: list[threading.Thread] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    output: list[bytes] = field(default_factory=list)
    address: tuple[str, int] | None = None
    said: threading.Event = field(default_factory=threading.Event)

    def standard_error(self) -> str:
        return ''.join(self.errors)

    def wrote(self) -> str:
        """What wasmtime wrote, to show beside a failure: its standard error, which names a
        trap, and the component's standard output, when it wrote any."""
        shown = f"wasmtime's standard error:\n{self.standard_error()}"
        if self.output:
            printed = b''.join(self.output).decode('utf-8', errors='replace')
            shown += f"\nits standard output:\n{printed}"
        return shown


def read_requests(path: Path) -> list[tuple[str, str]]:
    """The requests of the file at path, each (method, target)."""
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as error:
        raise UsageError(f'cannot read the requests {path}: {error}') from None
    requests = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        words = line.split()
        if len(words) != 2 or not METHOD.fullmatch(words[0]):
            raise UsageError(f'{path}:{number}: not `<METHOD> <target>`: {line}')
        requests.append((words[0], words[1]))
    if not requests:
        raise UsageError(f'{path}: holds no request')
    return requests


def start(wasmtime: str, flags: list[str], component: Path) -> Server:
    """wasmtime serving component, started; what it writes is read as it comes.

    Tip: os.setpgrp is Popen's process_group=0 of Python 3.11, which Python 3.9 lacks; no
    thread runs yet when it is called."""
    try:
        process = subprocess.Popen([wasmtime, 'serve', *flags, '--addr', ADDRESS, str(component)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, preexec_fn=os.setpgrp)
    except OSError as error:
        raise Failed(2, f'cannot start {wasmtime}: {error.strerror or error}') from None
    server = Server(process)

    def read_errors() -> None:
        assert process.stderr is not None
        for raw in process.stderr:
            line = raw.decode('utf-8', errors='replace')
            server.errors.append(line)
            found = SERVING.search(line)
            if found and server.address is None:
                server.address = (found.group(1), int(found.group(2)))
                server.said.set()
        server.said.set()

    def read_output() -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            server.output.append(raw)

    for reader in (read_errors, read_output):
        server.readers.append(threading.Thread(target=reader, daemon=True))
        server.readers[-1].start()
    return server


def wait_until_serving(server: Server, timeout: float) -> tuple[str, int]:
    """The address server listens on, once it says so."""
    server.said.wait(timeout)
    if server.address is not None:
        return server.address
    # Its standard error ended: it is ending, if it has not ended yet.
    status = None
    with contextlib.suppress(subprocess.TimeoutExpired):
        status = server.process.wait(1)
    if status is not None:
        raise Failed(2, f'wasmtime exited with status {status} before it served:\n'
                        f'{server.standard_error()}')
    raise Failed(2, f'wasmtime did not say it serves within {timeout:g} s:\n'
                    f'{server.standard_error()}')


def stop(server: Server) -> None:
    """Stops server's process group: SIGTERM, then, once wasmtime has ended or GRACE seconds
    have passed, SIGKILL to whatever of its group is left, which keeps the group, and so its
    number, from being taken by another. A group that is gone, or that refuses (macOS answers
    EPERM for a zombie), is left. What wasmtime wrote is then read to its end."""
    process = server.process
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(GRACE)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()
    for reader in server.readers:
        reader.join(1)


def ask(address: tuple[str, int], method: str, target: str, timeout: float) -> bytes:
    """The block of the transcript for one request: what was asked, and the answer."""
    connection = http.client.HTTPConnection(*address, timeout=timeout)
    try:
        connection.request(method, target)
        response = connection.getresponse()
        body = response.read()
        status, reason, headers = response.status, response.reason, response.getheaders()
    except (OSError, http.client.HTTPException) as error:
        raise Failed(1, f'{method} {target} got no answer: {error!r}') from None
    finally:
        connection.close()
    shown = sorted((name.lower(), value) for name, value in headers
                   if name.lower() not in HOST_HEADERS)
    lines = [f'$ curl -i -X {method} {SHOWN_ORIGIN}{target}'.encode(),
             f'HTTP/1.1 {status} {reason}'.rstrip().encode('latin-1'),
             *(f'{name}: {value}'.encode('latin-1') for name, value in shown)]
    return b'\n'.join(lines) + b'\n\n' + body


def transcript(blocks: list[bytes]) -> bytes:
    """The blocks, an empty line between two, each ended by a line break before it."""
    text = b''
    for block in blocks:
        if text:
            text += (b'' if text.endswith(b'\n') else b'\n') + b'\n'
        text += block
    return text


def diff(expected: bytes, actual: bytes, expected_name: str) -> str:
    """A unified diff from expected to actual, a line without its line break marked as such."""
    def lines(data: bytes) -> list[str]:
        result = data.decode('utf-8', errors='replace').splitlines(keepends=True)
        if result and not result[-1].endswith('\n'):
            result[-1] += '\n\\ No newline at end of file\n'
        return result
    return ''.join(difflib.unified_diff(lines(expected), lines(actual), fromfile=expected_name,
                                        tofile='the transcript'))


class Signals:
    """What a signal does: it stops the run with Stopped, but while the run is disarmed, when
    wasmtime is being started (it would be left running and not yet known) or stopped (the stop
    must not be cut short), it is held: arming the run again stops it then, and a run that ends
    with a signal held ends as that signal stops it."""

    def __init__(self) -> None:
        self.armed = True
        self.held: int | None = None

    def handle(self, number: int, _frame: object) -> None:
        if not self.armed:
            if self.held is None:
                self.held = number
            return
        raise Stopped(number)

    def disarm(self) -> None:
        self.armed = False

    def arm(self) -> None:
        self.armed = True
        if self.held is not None:
            raise Stopped(self.held)


SIGNALS = Signals()

# The signals that stop a run: an interrupt, b2 or a session ending, and the run's bound.
STOPPING = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Serves an HTTP component and checks its answers.')
    parser.add_argument('--wasmtime', help='wasmtime, else wasmtime on PATH')
    parser.add_argument('--program', help='the served program, as a message names it')
    parser.add_argument('--flags', required=True,
                        help='wasmtime serve\'s flags for the target, one argument')
    parser.add_argument('--component', required=True, type=Path)
    parser.add_argument('--requests', required=True, type=Path)
    parser.add_argument('--expected', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--timeout', type=float, default=30.0,
                        help='seconds to wait for wasmtime to serve, and for each answer')
    return parser.parse_args(argv)


def find_wasmtime(given: str | None, program: str) -> str:
    """The wasmtime that serves program: given, which must be an executable file, else wasmtime
    on PATH. Raises UsageError, naming both places, when there is none."""
    what = f'wasmtime, which serves the test of webcpp.serve {program}, was not found:'
    if given is not None:
        if not (os.path.isfile(given) and os.access(given, os.X_OK)):
            raise UsageError(f'{what} -sWASMTIME={given} is not an executable file. It is looked '
                             'for at -sWASMTIME=<path>, else on PATH.')
        return given
    found = shutil.which('wasmtime')
    if found is None:
        raise UsageError(f'{what} no -sWASMTIME=<path> was given, and there is none on PATH. '
                         'Install wasmtime 47.0.3 on PATH, or give its path with '
                         '-sWASMTIME=<path>.')
    return found


def stopped_by(number: int, arguments: argparse.Namespace) -> int:
    """Says that the signal number stopped the run, and returns the run's exit status."""
    if number == signal.SIGALRM:
        print(f'serve: {arguments.component}: the run took longer than its bound, '
              f'{arguments.timeout:g} s for the server to say it serves and for each answer',
              file=sys.stderr)
        return 1
    print(f'serve: {arguments.component}: stopped by {signal.Signals(number).name}',
          file=sys.stderr)
    return 128 + number


def run(arguments: argparse.Namespace) -> tuple[bytes, Server]:
    """The transcript of the component's answers, and the server, stopped."""
    if not arguments.component.is_file():
        raise UsageError(f'no component at {arguments.component}')
    requests = read_requests(arguments.requests)
    if not arguments.expected.is_file():
        raise UsageError(f'no expected transcript at {arguments.expected}')
    # The whole run's bound: the wait for the line, each answer, and the stop.
    signal.alarm(int(arguments.timeout * (len(requests) + 1) + GRACE + 1))
    wasmtime = find_wasmtime(arguments.wasmtime, arguments.program or str(arguments.component))
    SIGNALS.disarm()
    server = start(wasmtime, arguments.flags.split(), arguments.component)
    try:
        try:
            SIGNALS.arm()
            address = wait_until_serving(server, arguments.timeout)
            blocks = [ask(address, method, target, arguments.timeout)
                      for method, target in requests]
        finally:
            # A signal from here on is only held, and cannot cut the stop short.
            SIGNALS.disarm()
            signal.alarm(0)
            stop(server)
    except Failed as failure:
        if failure.status == 1:
            failure.args = (f'{failure}\n{server.wrote()}',)
        raise
    return transcript(blocks), server


def main(argv: list[str]) -> int:
    arguments = parse(argv)
    for number in STOPPING:
        signal.signal(number, SIGNALS.handle)
    with contextlib.suppress(FileNotFoundError):
        arguments.output.unlink()
    try:
        actual, server = run(arguments)
    except UsageError as error:
        print(f'serve: {error}', file=sys.stderr)
        return 2 if SIGNALS.held is None else stopped_by(SIGNALS.held, arguments)
    except Failed as failure:
        print(f'serve: {arguments.component}: {failure}', file=sys.stderr)
        return failure.status if SIGNALS.held is None else stopped_by(SIGNALS.held, arguments)
    except Stopped as stopped:
        return stopped_by(stopped.number, arguments)
    if SIGNALS.held is not None:
        return stopped_by(SIGNALS.held, arguments)
    expected = arguments.expected.read_bytes()
    if actual != expected:
        print(f'serve: {arguments.component}: the transcript differs from {arguments.expected}:')
        print(diff(expected, actual, str(arguments.expected)), end='')
        print(server.wrote(), end='')
        return 1
    arguments.output.write_bytes(actual)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
