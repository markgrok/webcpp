#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Scratch superprojects for the tests of tools/release: git repositories under a directory
whose path holds a space, with libs/config, whose version.hpp names the version, libraries whose
changelogs keep AGENTS.md chapter 11's form, the index's section Releases, the notes of the
version in preparation, and built pages, which git ignores. The files are no source of the
project, and carry no notice."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import changelog

GIT = ['git', '-c', 'user.name=webcpp release test', '-c', 'user.email=release@webcpp.invalid',
       '-c', 'commit.gpgsign=false', '-c', 'tag.gpgsign=false', '-c', 'protocol.file.allow=always',
       '-c', 'advice.addEmbeddedRepo=false', '-c', 'init.defaultBranch=main']

# As config writes it: the exemption from clang-tidy on the line above WEBCPP_VERSION, and no
# comment after a value, which a reader would take for a part of it.
VERSION_HPP = ('#ifndef WEBCPP_VERSION_HPP\n#define WEBCPP_VERSION_HPP\n'
               '// NOLINTNEXTLINE(modernize-macro-to-enum)\n#define WEBCPP_VERSION {number}\n'
               '#define WEBCPP_LIB_VERSION "{lib}"\n#endif  // WEBCPP_VERSION_HPP\n')


def git(directory: Path, *arguments: str) -> str:
    """Runs git in directory as the test's author, and returns what it printed."""
    completed = subprocess.run([*GIT, '-C', str(directory), *arguments], capture_output=True,
                               text=True, check=False)
    assert completed.returncode == 0, (arguments, completed.stderr)
    return completed.stdout


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def changelog_text(name: str, unreleased: tuple[str, ...] = (),
                   released: tuple[tuple[str, tuple[str, ...]], ...] = ()) -> str:
    """A library's changelog: its Unreleased lines, then each released version's, newest first,
    each line of the file as written."""
    sections = [(f'{name}-changelog-unreleased', 'Unreleased', 'unreleased', unreleased)]
    sections += [(f'{name}-changelog-{version.replace(".", "-")}', f'webcpp {version}', version,
                  lines) for version, lines in released]
    text = f'[appendix]\n[#{name}-changelog]\n== Changelog\n\nWhat changed in {name}.\n'
    for anchor, title, tag, lines in sections:
        body = ''.join(f'{line}\n' for line in lines)
        text += f'\n[#{anchor}]\n=== {title}\n\n// tag::{tag}[]\n{body}// end::{tag}[]\n'
    return text


def notes_text(version: str, *, preparing: bool = True, new: tuple[str, ...] = (),
               updated: tuple[tuple[str, str], ...] = (), removed: tuple[str, ...] = (),
               tools: tuple[str, ...] = (), compilers: tuple[str, ...] | None = None) -> str:
    """A version's release notes: each new and removed library named, each updated one with the
    tag its include names, the lines of Tools and build as written, and the lanes, as the notes
    write a lane's name."""
    anchor = version.replace('.', '-')

    def section(slug: str, title: str, body: str) -> str:
        return f'\n[#webcpp-{anchor}-{slug}]\n== {title}\n\n{body or changelog.NONE}\n'

    text = f'[#webcpp-{anchor}]\n= webcpp {version}\n'
    if preparing:
        text += '\n' + '\n'.join(changelog.IN_PREPARATION) + '\n'
    text += section('new-libraries', 'New Libraries', '\n'.join(
        f'* link:{{library-pages}}{name}/{{library-page}}[{name}]: {name}, a library, from '
        'R.' for name in new))
    text += section('updated-libraries', 'Updated Libraries', '\n\n'.join(
        f'[#webcpp-{anchor}-{name}]\n=== link:{{library-pages}}{name}/{{library-page}}[{name}]'
        f'\n\ninclude::{{webcpp-root}}/libs/{name}/doc/changelog.adoc[tag={tag}]'
        for name, tag in updated))
    text += section('removed-libraries', 'Removed Libraries',
                    '\n'.join(f'* {name}: {name}, gone.' for name in removed))
    text += section('tools-and-build', 'Tools and build', '\n'.join(tools))
    text += section('compilers-tested', 'Compilers tested',
                    '' if compilers is None else
                    '\n'.join(f'* {changelog.notes_lane(lane)}' for lane in compilers))
    return text


def index_text(versions: tuple[str, ...]) -> str:
    """The index page, its section Releases including each version's notes, as given."""
    included = '\n\n'.join(f'include::releases/{version}.adoc[leveloffset=+2]'
                           for version in versions)
    return f'= webcpp\n\n[#releases]\n== Releases\n\nEach version.\n\n{included}\n'


@dataclass
class Tree:
    """A scratch superproject: a git checkout whose libraries are gitlinks. Its commits allow
    an unchanged tree, so that a test may write a file again as it was."""

    root: Path

    def library(self, name: str) -> Path:
        return self.root / 'libs' / name

    def add_library(self, name: str) -> None:
        """Adds library name, with what a user sees and what they do not, and a built page git
        ignores, committed in its own repository and recorded by the superproject."""
        directory = self.library(name)
        write(directory / 'build.jam', f'project /webcpp/{name} ;\n')
        write(directory / f'include/webcpp/{name}.hpp', f'// {name}\n')
        write(directory / f'test/{name}_test.cpp', 'int main() {}\n')
        write(directory / 'AGENTS.md', f'# {name}\n')
        write(directory / 'LICENSE_1_0.txt', 'Boost Software License\n')
        write(directory / 'doc/changelog.adoc', changelog_text(name))
        write(directory / '.gitattributes', '* text=auto eol=lf\n')
        write(directory / '.gitignore', 'doc/html/\n')
        write(directory / 'doc/html/index.html', f'<p>{name}</p>\n')
        git(directory, 'init', '-q')
        git(directory, 'add', '.')
        git(directory, 'commit', '-q', '-m', f'{name}: its first commit')
        self.record(name)

    def record(self, name: str) -> None:
        """Records library name's checked-out commit in the superproject."""
        git(self.root, 'add', f'libs/{name}')
        git(self.root, 'commit', '-q', '--allow-empty', '-m', f'libs/{name}: recorded')

    def change(self, name: str, path: str, text: str) -> None:
        """Commits text at path of library name, and records the commit."""
        write(self.library(name) / path, text)
        git(self.library(name), 'add', path)
        git(self.library(name), 'commit', '-q', '--allow-empty', '-m', f'{name}: {path}')
        self.record(name)

    def commit_file(self, path: str, text: str) -> None:
        """Commits text at path of the superproject."""
        write(self.root / path, text)
        git(self.root, 'add', path)
        git(self.root, 'commit', '-q', '--allow-empty', '-m', path)


def make_tree(directory: Path) -> Tree:
    """A superproject preparing 0.1.0, its first version, with config, alpha and beta, which
    every check passes, and its dot files, a script, and pages built for every library."""
    root = directory / 'super project'
    root.mkdir()
    git(root, 'init', '-q')
    write(root / '.gitignore', 'bin/\ndoc/html/\n')
    write(root / '.clang-format', 'BasedOnStyle: Google\n')
    write(root / '.github/workflows/ci.yml', 'name: CI\n')
    write(root / 'README.md', '# webcpp\n')
    write(root / 'doc/index.adoc', index_text(('0.1.0',)))
    write(root / 'doc/releases/0.1.0.adoc', notes_text('0.1.0', new=('alpha', 'beta', 'config')))
    write(root / 'tools/run.sh', '#!/bin/sh\n')
    (root / 'tools/run.sh').chmod(0o755)
    write(root / 'doc/html/index.html', '<p>webcpp</p>\n')
    git(root, 'add', '.')
    git(root, 'commit', '-q', '-m', 'The superproject')
    tree = Tree(root)
    for name in ('alpha', 'beta', 'config'):
        tree.add_library(name)
    tree.change('config', 'include/webcpp/version.hpp', VERSION_HPP.format(number=100, lib='0_1'))
    return tree
