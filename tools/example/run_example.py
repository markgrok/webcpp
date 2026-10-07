# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Runs one example and compares what it prints with the committed output.

Usage: run_example.py [--launcher L] --expected FILE --output FILE -- PROGRAM [ARGS]

The program runs directly, or through the launcher (wasmtime for a wasm
build). Its standard output, with every carriage return removed, must equal
the expected file's; on success it is written to the output file, which b2
keeps as the target. Exit 0 when equal, 1 when different (with a diff) or
when the program's exit status was not zero (named, and before the output
file is written), 2 when the launcher is missing or the program cannot be
started, the way a wasm module cannot without a launcher (both named, in one
line).
"""
import argparse
import difflib
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--launcher', default='')
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
    try:
        result = subprocess.run(command, capture_output=True)
    except OSError as error:
        hint = '' if arguments.launcher else '; a wasm build needs testing.launcher=wasmtime'
        print(f'run_example: cannot start {command[0]}: {error.strerror}{hint}', file=sys.stderr)
        return 2
    printed = result.stdout.replace(b'\r', b'')
    with open(arguments.expected, 'rb') as file:
        expected = file.read().replace(b'\r', b'')
    if printed != expected:
        sys.stderr.writelines(difflib.unified_diff(
            expected.decode(errors='replace').splitlines(True),
            printed.decode(errors='replace').splitlines(True),
            arguments.expected, 'printed'))
        return 1
    if result.returncode != 0:
        print(f'run_example: the program exited with status {result.returncode}', file=sys.stderr)
        return 1
    with open(arguments.output, 'wb') as file:
        file.write(printed)
    return 0


if __name__ == '__main__':
    sys.exit(main())
