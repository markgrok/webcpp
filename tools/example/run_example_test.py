# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks run_example.py: CRLF ignored, a difference reported, a missing
launcher named, a nonzero exit status failing the comparison, a program that
cannot be started (a wasm module run without a launcher) named in one line."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, 'run_example.py')


def run(args):
    return subprocess.run([sys.executable, RUNNER] + args, capture_output=True, text=True)


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
