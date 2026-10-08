# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks run_example.py: CRLF ignored, a difference reported, a missing
launcher named, a nonzero exit status failing the comparison and named before
the diff of what the program printed until then, a crash named by its signal,
a program that cannot be started (a wasm module run without a launcher)
named in one line, and the standard input the --input file, else empty."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, 'run_example.py')


def run(args, stdin=None):
    return subprocess.run([sys.executable, RUNNER] + args, stdin=stdin, capture_output=True,
                          text=True, timeout=60)


def main():
    with tempfile.TemporaryDirectory() as scratch:
        expected = os.path.join(scratch, 'expected')
        with open(expected, 'w', newline='') as out:
            out.write('one\ntwo\n')
        output = os.path.join(scratch, 'output')
        printer = [sys.executable, '-c',
                   'import sys; sys.stdout.buffer.write(b"one\\r\\ntwo\\r\\n")']
        same = run(['--expected', expected, '--output', output, '--'] + printer)
        assert same.returncode == 0, same.stderr
        assert open(output).read() == 'one\ntwo\n'
        other = [sys.executable, '-c', 'print("three")']
        differ = run(['--expected', expected, '--output', output, '--'] + other)
        assert differ.returncode == 1 and 'three' in differ.stderr, differ.stderr
        missing = run(['--launcher', 'no-such-launcher', '--expected', expected,
                       '--output', output, '--', 'prog'])
        assert missing.returncode == 2 and 'no-such-launcher' in missing.stderr, missing.stderr
        output2 = os.path.join(scratch, 'output2')
        exits_bad = [sys.executable, '-c',
                     'import sys; sys.stdout.write("one\\ntwo\\n"); sys.exit(3)']
        bad_status = run(['--expected', expected, '--output', output2, '--'] + exits_bad)
        assert bad_status.returncode == 1 and '3' in bad_status.stderr, bad_status.stderr
        assert not os.path.exists(output2), (
            'the output file must not be written on a nonzero exit status')
        # A program that stops halfway, after printing part of its output: its exit status is
        # named first, and the diff follows.
        stops = [sys.executable, '-c',
                 'import sys; sys.stdout.write("one\\n"); sys.stdout.flush(); sys.exit(5)']
        halfway = run(['--expected', expected, '--output', output2, '--'] + stops)
        assert halfway.returncode == 1, halfway.stderr
        assert halfway.stderr.startswith('run_example: the program exited with status 5'), (
            halfway.stderr)
        assert '-two' in halfway.stderr, halfway.stderr
        assert not os.path.exists(output2), (
            'the output file must not be written on a nonzero exit status')
        if os.name == 'posix':
            # A crash, killed by a signal after part of its output: the signal is named.
            crashes = [sys.executable, '-c',
                       'import os, sys; sys.stdout.write("one\\n"); sys.stdout.flush(); '
                       'os.abort()']
            crashed = run(['--expected', expected, '--output', output2, '--'] + crashes)
            assert crashed.returncode == 1, crashed.stderr
            assert crashed.stderr.startswith(
                'run_example: the program was killed by signal SIGABRT'), crashed.stderr
            assert '-two' in crashed.stderr, crashed.stderr
            assert not os.path.exists(output2), (
                'the output file must not be written when the program crashes')
        # The standard input is the --input file, else nothing, never the runner's own: here a
        # pipe that stays open, as a terminal does, which a program reading it would wait on.
        given = os.path.join(scratch, 'input')
        with open(given, 'w', newline='') as out:
            out.write('one\ntwo\n')
        empty = os.path.join(scratch, 'empty')
        with open(empty, 'w', newline='') as out:
            out.write('0\n')
        echoes = [sys.executable, '-c', 'import sys; sys.stdout.write(sys.stdin.read())']
        counts = [sys.executable, '-c', 'import sys; print(len(sys.stdin.read()))']
        read, write = os.pipe()
        try:
            fed = run(['--input', given, '--expected', expected, '--output', output, '--']
                      + echoes, stdin=read)
            assert fed.returncode == 0, fed.stderr
            unfed = run(['--expected', empty, '--output', output, '--'] + counts, stdin=read)
            assert unfed.returncode == 0, unfed.stderr
        finally:
            os.close(read)
            os.close(write)
        module = os.path.join(scratch, 'example.wasm')
        with open(module, 'wb') as out:
            out.write(b'\0asm')
        unstartable = run(['--expected', expected, '--output', output2, '--', module])
        assert unstartable.returncode == 2, unstartable.stderr
        assert unstartable.stderr.count('\n') == 1, unstartable.stderr
        assert module in unstartable.stderr, unstartable.stderr
        assert 'testing.launcher=wasmtime' in unstartable.stderr, unstartable.stderr
        assert not os.path.exists(output2), (
            'the output file must not be written when the program cannot start')
    print('run_example.py: ok')


if __name__ == '__main__':
    main()
