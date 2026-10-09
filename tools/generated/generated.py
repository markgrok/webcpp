#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Runs the generators of webcpp.generated, and checks or writes what they write.

Usage: generated.py check|update BUILD WRITER STEP...

A STEP is the words NAME DIRECTORY SCRIPT N ARGUMENT... M OUTPUT...: the Python script SCRIPT, run
in DIRECTORY as `SCRIPT ARGUMENT... PATH...`, writes each of the M committed files OUTPUT at the
PATH given in its place, BUILD/<mode>/NAME/<position>/<file name>: check and update each write
under a directory of their own, so that one b2 request may run both at once. No output is named
twice, by one step or by two. WRITER is the b2 target that writes the committed files again,
libs/<library>/test//update-generated, which check's message names.

check runs each step, then compares each output with its committed file, byte for byte, with
tools/oracle/compare.py --files, which names every difference; it names each output a generator
did not write, and exits 1 when a generator fails or an output differs or is missing. It writes
nothing but its build directory. update removes what a killed update left staged beside a committed
file, refuses a committed output that is not a file, runs every step and, only once every generator
has succeeded and written each of its outputs, copies them beside the committed files, then renames
each over its committed file, so that a generator that fails, or a copy that fails, leaves every
committed file as it was; a rename that fails, which a full disk or a file made read-only meanwhile
could cause, is named with the files already replaced and those left as they were. Exit 0 when all
is well, 1 on a failure, 2 on a usage error.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

COMPARE = Path(__file__).resolve().parents[1] / 'oracle/compare.py'


@dataclass
class Step:
    """One generator: what it is named, where it runs, and what it writes."""
    name: str
    directory: Path
    script: Path
    arguments: list[str]
    outputs: list[Path]


class Usage(Exception):
    """The words given do not make steps."""


def count(words: list[str], at: int) -> int:
    """The count at words[at], which the words after it must hold."""
    try:
        value = int(words[at])
    except (IndexError, ValueError):
        raise Usage(f'a count was expected at word {at + 1}') from None
    if value < 0 or at + 1 + value > len(words):
        raise Usage(f'the count {value} at word {at + 1} runs past the last word')
    return value


def parse(words: list[str]) -> list[Step]:
    """The steps the words give, in order; no output is named twice, by one step or by two."""
    steps = []
    writers: dict[str, str] = {}
    at = 0
    while at < len(words):
        if at + 3 > len(words):
            raise Usage('a step needs a name, a directory and a script')
        name, directory, script = words[at:at + 3]
        at += 3
        arguments_count = count(words, at)
        arguments = words[at + 1:at + 1 + arguments_count]
        at += 1 + arguments_count
        outputs_count = count(words, at)
        if outputs_count == 0:
            raise Usage(f'{name}: a generator writes at least one output')
        outputs = [Path(word) for word in words[at + 1:at + 1 + outputs_count]]
        at += 1 + outputs_count
        for output in outputs:
            key = os.path.normpath(output)
            if writers.get(key) == name:
                raise Usage(f'{name}: {output} is named twice')
            if key in writers:
                raise Usage(f'{name}: {output} is written by {writers[key]} already')
            writers[key] = name
        steps.append(Step(name, Path(directory), Path(script), arguments, outputs))
    if not steps:
        raise Usage('no step was given')
    return steps


def generate(scratch: Path, step: Step) -> list[Path] | None:
    """Runs step's generator into scratch/<name>, emptied first, and returns where it was told to
    write each output; None, once it has said why, when the generator failed or the directory
    could not be made ready, since a stale output left there could pass as written."""
    directory = scratch / step.name
    paths = [directory / str(position) / output.name
             for position, output in enumerate(step.outputs, start=1)]
    try:
        if os.path.lexists(directory):
            shutil.rmtree(directory)
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f'generated: {step.name}: cannot make {directory} ready: {error}', file=sys.stderr)
        return None
    completed = subprocess.run([sys.executable, str(step.script), *step.arguments,
                                *map(str, paths)], cwd=step.directory, check=False)
    if completed.returncode != 0:
        print(f'generated: {step.name}: {step.script.name} exited with status '
              f'{completed.returncode}', file=sys.stderr)
        return None
    return paths


def not_written(step: Step, path: Path) -> str:
    """What says that step's generator did not write path."""
    return (f'generated: {step.name}: {step.script.name} wrote no {path}; it must write each '
            'output it is given')


def check(build: Path, writer: str, steps: list[Step]) -> int:
    failed = False
    for step in steps:
        paths = generate(build / 'check', step)
        if paths is None:
            failed = True
            continue
        for output, path in zip(step.outputs, paths):
            if not path.is_file():
                failed = True
                print(not_written(step, path), file=sys.stderr)
                continue
            compared = subprocess.run([sys.executable, str(COMPARE), '--files', str(output),
                                       str(path)], check=False)
            if compared.returncode != 0:
                failed = True
                print(f'generated: {step.name}: {output} is not what {step.script.name} '
                      f'writes; `b2 {writer}` writes it again', file=sys.stderr)
    return 1 if failed else 0


def beside(output: Path) -> Path:
    """Where update stages output, beside it."""
    return output.with_name(output.name + '.generated')


def update(build: Path, steps: list[Step]) -> int:
    # What a killed update left staged goes first, whatever this one does; then a committed output
    # that no rename could replace stops it before anything is written.
    try:
        for step in steps:
            for output in step.outputs:
                beside(output).unlink(missing_ok=True)
    except OSError as error:
        print(f'generated: {error}', file=sys.stderr)
        return 1
    for step in steps:
        for output in step.outputs:
            if os.path.lexists(output) and not output.is_file():
                print(f'generated: {step.name}: {output} is not a file; update-generated '
                      'replaces files only', file=sys.stderr)
                return 1
    generated = []
    for step in steps:
        paths = generate(build / 'update', step)
        if paths is None:
            return 1
        missing = [path for path in paths if not path.is_file()]
        if missing:
            for path in missing:
                print(not_written(step, path), file=sys.stderr)
            return 1
        generated.append((step, paths))
    # Every output is copied beside its committed file first, and renamed over it only once all
    # are there: os.replace is atomic, a copy is not.
    staged: list[tuple[Path, Path, str]] = []
    for step, paths in generated:
        for output, path in zip(step.outputs, paths):
            staged.append((beside(output), output, step.name))
            try:
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, beside(output))
            except OSError as error:
                for copy, _, _ in staged:
                    copy.unlink(missing_ok=True)
                print(f'generated: {step.name}: cannot stage {beside(output)}: {error}',
                      file=sys.stderr)
                return 1
    for done, (copy, output, name) in enumerate(staged):
        try:
            os.replace(copy, output)
        except OSError as error:
            print(f'generated: {name}: cannot replace {output}: {error}', file=sys.stderr)
            for _, replaced, _ in staged[:done]:
                print(f'generated: replaced {replaced}', file=sys.stderr)
            for left, kept, _ in staged[done:]:
                left.unlink(missing_ok=True)
                print(f'generated: not replaced {kept}', file=sys.stderr)
            return 1
        print(f'generated: {name}: wrote {output}')
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[0] not in ('check', 'update'):
        print('usage: generated.py check|update BUILD WRITER STEP...', file=sys.stderr)
        return 2
    try:
        steps = parse(argv[3:])
    except Usage as error:
        print(f'generated.py: {error}', file=sys.stderr)
        return 2
    build = Path(argv[1])
    return check(build, argv[2], steps) if argv[0] == 'check' else update(build, steps)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
