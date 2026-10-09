#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""webcpp's release tooling (AGENTS.md chapter 11), which the Jamroot's explicit targets run.

Usage: release.py check --root <superproject> --version <a.b.c>

check fails when the version disagrees anywhere: WEBCPP_VERSION and WEBCPP_LIB_VERSION of
libs/config/include/webcpp/version.hpp, the one place it is written, name different versions,
or the version the Jamroot read, --version, is not theirs. Exit 0 when nothing is wrong; 1 with
each fault on a line of its own, `<command>: <fault>`; 2 on a usage error, or when what it reads
is not there.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

HEADER = 'libs/config/include/webcpp/version.hpp'
# A value runs to the end of its line, so config writes no comment after one: its exemption from
# clang-tidy is a NOLINTNEXTLINE on the line above.
DEFINE = re.compile(r'^#define (WEBCPP_VERSION|WEBCPP_LIB_VERSION) +(.+?)\s*$', re.MULTILINE)


class Failure(Exception):
    """Faults of the tree that stop a command, said to the user, one per line; exit 1."""


class Broken(Exception):
    """A usage error, or something the tool reads that is not there; exit 2."""


@dataclass(frozen=True, order=True)
class Version:
    """A version of webcpp, which orders as its numbers do."""

    major: int
    minor: int
    patch: int

    @staticmethod
    def of_number(number: int) -> Version:
        """The version WEBCPP_VERSION's number names: 100 is 0.1.0."""
        return Version(number // 100000, number // 100 % 1000, number % 100)

    @staticmethod
    def parse(name: str) -> Version:
        """The version name writes, <major>.<minor>.<patch>."""
        match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', name)
        if match is None:
            raise Broken(f'{name} is no version <major>.<minor>.<patch>')
        return Version(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    @property
    def name(self) -> str:
        return f'{self.major}.{self.minor}.{self.patch}'

    @property
    def lib(self) -> str:
        """The version as WEBCPP_LIB_VERSION writes it: 0_1, 1_2_3."""
        return f'{self.major}_{self.minor}' + (f'_{self.patch}' if self.patch else '')

    @property
    def anchor(self) -> str:
        return self.name.replace('.', '-')

    @property
    def tag(self) -> str:
        return f'webcpp-{self.name}'


def read_version(root: Path) -> tuple[Version, str]:
    """The version WEBCPP_VERSION names, and WEBCPP_LIB_VERSION's text without its quotes."""
    header = root / HEADER
    if not header.is_file():
        raise Broken(f'{HEADER} does not exist: check out libs/config')
    try:
        text = header.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as error:
        raise Broken(f'{HEADER} cannot be read: {error}') from error
    defined = dict(DEFINE.findall(text))
    number = defined.get('WEBCPP_VERSION', '')
    lib = defined.get('WEBCPP_LIB_VERSION', '')
    if not number.isdigit() or len(lib) < 2 or lib[0] != '"' or lib[-1] != '"':
        raise Broken(f'{HEADER} has no lines `#define WEBCPP_VERSION <number>` and '
                     '`#define WEBCPP_LIB_VERSION "<text>"`')
    return Version.of_number(int(number)), lib[1:-1]


def version_findings(root: Path, version: Version) -> list[str]:
    """What disagrees about the version: version.hpp's two macros, and the Jamroot's reading."""
    written, lib = read_version(root)
    findings = []
    if lib != written.lib:
        findings.append(f'{HEADER}: WEBCPP_VERSION names {written.name}, and WEBCPP_LIB_VERSION '
                        f'"{lib}" is not "{written.lib}"')
    if version != written:
        findings.append(f'the build read the version {version.name}, and {HEADER} names '
                        f'{written.name}')
    return findings


def check(root: Path, version: Version) -> list[str]:
    """Every fault that keeps the tree from being tagged webcpp-<version>."""
    return version_findings(root, version)


# A command: given the superproject, the version and its arguments, it returns the faults that
# stop it, and prints what it writes.
Command = Callable[[Path, Version, argparse.Namespace], list[str]]

COMMANDS: dict[str, Command] = {
    'check': lambda root, version, _: check(root, version),
}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='release.py', description="webcpp's release tooling")
    commands = parser.add_subparsers(dest='command', required=True)
    for name in COMMANDS:
        command = commands.add_parser(name)
        command.add_argument('--root', type=Path, required=True)
        command.add_argument('--version', required=True)
    arguments = parser.parse_args(argv)
    try:
        version = Version.parse(arguments.version)
        findings = COMMANDS[arguments.command](arguments.root.resolve(), version, arguments)
    except Failure as failure:
        findings = str(failure).split('\n')
    except Broken as broken:
        print(f'{arguments.command}: {broken}', file=sys.stderr)
        return 2
    for finding in findings:
        print(f'{arguments.command}: {finding}')
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
