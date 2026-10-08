# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Runs one example and compares what it prints with the committed output.

Usage: run_example.py [--launcher L] [--input FILE] --expected FILE --output FILE -- PROGRAM [ARGS]

The program runs directly, or through the launcher (wasmtime for a wasm build,
which passes its standard input through). Its standard input is the input
file, else empty, never the runner's own, so that a program reading it never
waits on a terminal. It must exit with status 0, and its standard output, with
every carriage return removed, must equal the expected file's; on success that
output is written to the output file, which b2 keeps as the target, and on a
failure nothing is written. Exit 0 when both hold; 1 when either does not: an
exit status other than 0 is named first, the signal that killed the program as
well, then a diff follows when the output differs, so a program that crashes
halfway is told from one that prints something else; 2 when the launcher is
missing, the input file cannot be read, or the program cannot be started, the
way a wasm module cannot without a launcher (each named, in one line).
"""
import argparse
import difflib
import shutil
import signal
import subprocess
import sys


def ending(status):
    """How a program that did not exit with 0 ended: a negative status is the signal that killed
    it, as subprocess reports one on POSIX."""
    if status < 0:
        try:
            name = signal.Signals(-status).name
        except ValueError:
            name = str(-status)
        return f'the program was killed by signal {name}'
    return f'the program exited with status {status}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--launcher', default='')
    parser.add_argument('--input', default='')
    parser.add_argument('--expected', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = [part for part in arguments.command if part != '--']
    if arguments.launcher:
        if shutil.which(arguments.launcher) is None:
            print(f'run_example: the launcher {arguments.launcher} is not on PATH', file=sys.stderr)
            return 2
        command = [arguments.launcher] + command
    given = None
    if arguments.input:
        try:
            with open(arguments.input, 'rb') as file:
                given = file.read()
        except OSError as error:
            print(f'run_example: cannot read the input {arguments.input}: {error.strerror}',
                  file=sys.stderr)
            return 2
    try:
        if given is None:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True)
        else:
            result = subprocess.run(command, input=given, capture_output=True)
    except OSError as error:
        hint = '' if arguments.launcher else '; a wasm build needs testing.launcher=wasmtime'
        print(f'run_example: cannot start {command[0]}: {error.strerror}{hint}', file=sys.stderr)
        return 2
    printed = result.stdout.replace(b'\r', b'')
    with open(arguments.expected, 'rb') as file:
        expected = file.read().replace(b'\r', b'')
    if result.returncode != 0:
        print(f'run_example: {ending(result.returncode)}', file=sys.stderr)
    if printed != expected:
        sys.stderr.writelines(difflib.unified_diff(
            expected.decode(errors='replace').splitlines(True),
            printed.decode(errors='replace').splitlines(True),
            arguments.expected, 'printed'))
    if result.returncode != 0 or printed != expected:
        return 1
    with open(arguments.output, 'wb') as file:
        file.write(printed)
    return 0


if __name__ == '__main__':
    sys.exit(main())
