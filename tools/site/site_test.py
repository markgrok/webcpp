#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks `b2 site` (tools/site/site.jam), in a scratch copy of the superproject, committed to a
git repository of its own, whose path holds a space: run with -sWEBCPP_SITE_DOCS naming a fixture
of the pages `b2 doc -sWEBCPP_INDEX=site` writes, it writes bin/site/ whole, the site's pages at
the root, the docs index at docs/, every library's page under the site's header, the report's
page saying no results were given, the indexing files, every link checked; a page deleted from
the site's pages/ between two runs is gone from the second bin/site/, its card and its line of
the sitemap with it. -sWEBCPP_SITE=release without -sWEBCPP_SITE_VERSION fails, naming the
option, and so does any channel but preview and release, naming the two.

It needs b2, node and npm, and the site checked out at site/; without the site there is nothing
to build, which it says, and passes. The site's node packages are linked into the copy from the
checkout's own install (tools/node/install.py), so no run installs them again. Run with the names
of some cases to run only those."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
USER_CONFIG = ROOT / '.local/user-config.jam'
# What a copy of the superproject leaves out: what a build writes, and the installs of node
# packages, which the copy links from the checkout's.
IGNORED = shutil.ignore_patterns('.git', 'bin', 'build', 'node_modules', '.node-modules',
                                 '__pycache__', '.DS_Store', 'html', '.local')
# A page the first run builds and the second, once it is deleted, must not hold.
EXTRA_PAGE = '\n'.join([
    '// Copyright (c) 2026 WebCpp.org',
    '//',
    '// Distributed under the Boost Software License, Version 1.0. (See',
    '// accompanying file LICENSE_1_0.txt or copy at',
    '// https://www.boost.org/LICENSE_1_0.txt)',
    '',
    'root = Page("A page that goes", "A page of the test of b2 site, built by its first run and '
    'deleted before its second, which must leave nothing of it in bin/site.", [text])',
    'text = Text("This page is deleted before the second run.")',
    '',
])


def b2(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """b2 at root, as AGENTS.md runs it: without the include paths a shell may set."""
    environment = {name: value for name, value in os.environ.items()
                   if name not in ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH')}
    command = ['b2']
    if USER_CONFIG.is_file():
        command.append(f'--user-config={USER_CONFIG}')
    return subprocess.run([*command, *arguments], cwd=root, env=environment, capture_output=True,
                          text=True, check=False)


def git(root: Path, *arguments: str) -> None:
    subprocess.run(['git', '-c', 'user.name=webcpp', '-c', 'user.email=test@webcpp.invalid',
                    '-c', 'commit.gpgsign=false', *arguments], cwd=root, check=True,
                   capture_output=True)


def linked_installs(source: Path, destination: Path) -> None:
    """Gives destination/.node-modules the installs of source/.node-modules, each file a hard link
    where the system allows one, else a copy, so that install.py finds the install of the same
    lockfile there and installs nothing."""
    def link(source_file: str, destination_file: str) -> None:
        try:
            os.link(source_file, destination_file)
        except OSError:
            shutil.copy2(source_file, destination_file)
    installs = source / '.node-modules'
    for install in installs.iterdir():
        if install.is_dir() and not install.name.startswith('.'):
            shutil.copytree(install, destination / '.node-modules' / install.name, symlinks=True,
                            copy_function=link)


def superproject(scratch: Path) -> Path:
    """A copy of the superproject, its libraries and the site, committed to a repository of its
    own, so that the build's commit and dates are read as in a checkout."""
    root = scratch / 'webcpp copy'
    root.mkdir()
    for name in ('Jamroot', 'LICENSE_1_0.txt', '.gitignore'):
        shutil.copy2(ROOT / name, root / name)
    for name in ('tools', 'libs', 'doc', 'site'):
        shutil.copytree(ROOT / name, root / name, ignore=IGNORED, symlinks=True)
    install = subprocess.run([sys.executable, str(ROOT / 'tools/node/install.py'),
                              str(ROOT / 'site')], capture_output=True, text=True, check=False)
    assert install.returncode == 0, install.stderr
    linked_installs(ROOT / 'site', root / 'site')
    git(root, 'init', '-q')
    # No git run here may pack the repository in the background, which would still be writing
    # into .git when the test removes the copy.
    git(root, 'config', 'gc.auto', '0')
    git(root, 'config', 'maintenance.auto', 'false')
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', 'The copy')
    return root


def docs_fixture(scratch: Path, root: Path) -> Path:
    """The pages `b2 doc -sWEBCPP_INDEX=site` writes, one per library of root's libs/: the index
    linking each, and each library's page titled as the real ones are, `<name>: <subject>`."""
    docs = scratch / 'docs'
    libraries = sorted(build.parent.name for build in (root / 'libs').glob('*/build.jam'))
    links = ''.join(f'<li><a href="../libs/{name}/">{name}</a></li>' for name in libraries)
    pages = {'doc/html/index.html': ('webcpp', f'<ul>{links}</ul>')}
    for name in libraries:
        pages[f'libs/{name}/doc/html/index.html'] = (
            f'{name}: a library for C&#43;&#43;',
            f'<h1>{name}</h1><h2 id="usage">Usage</h2><a href="#usage">usage</a>')
    for path, (title, body) in pages.items():
        file = docs / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
                        f'<title>{title}</title>\n</head>\n<body class="article">\n{body}\n'
                        '</body>\n</html>\n')
    return docs


def test_b2_site_builds_the_whole_site_and_forgets_a_deleted_page(scratch: Path) -> None:
    root = superproject(scratch)
    docs = docs_fixture(scratch, root)
    (root / 'site/pages/goes.oui').write_text(EXTRA_PAGE)
    first = b2(root, '-a', 'site', f'-sWEBCPP_SITE_DOCS={docs}')
    assert first.returncode == 0, (first.returncode, first.stdout[-6000:], first.stderr[-3000:])
    assert 'libraries, every link resolving' in first.stdout, first.stdout[-6000:]
    site = root / 'bin/site'
    libraries = sorted(build.parent.name for build in (root / 'libs').glob('*/build.jam'))
    for name in ('index.html', 'libraries/index.html', 'search/index.html', 'docs/index.html',
                 'report/index.html', 'assets/site.css', 'assets/chrome.css', 'assets/site.js',
                 'robots.txt',
                 'sitemap.xml', 'llms.txt', 'libraries.json', 'goes/index.html',
                 'cards/goes.png', *(f'libs/{library}/index.html' for library in libraries)):
        assert (site / name).is_file(), name
    assert 'No test results were given to this build' in (site / 'report/index.html').read_text()
    catalogue = json.loads((site / 'libraries.json').read_text())
    assert sorted(entry['key'] for entry in catalogue) == libraries, catalogue
    library = (site / f'libs/{libraries[0]}/index.html').read_text()
    assert '<header class="site">' in library, library[:3000]
    assert '<link rel="stylesheet" href="../../assets/chrome.css">' in library, library[:3000]
    assert 'assets/site.css' not in library, 'a library\'s page keeps its own style'
    assert f'<title>{libraries[0]}: a library for C++ - webcpp</title>' in library
    commit = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True,
                            text=True, check=True).stdout.strip()
    assert commit[:7] in (site / 'index.html').read_text(), 'the band names the commit'
    assert 'https://webcpporg.github.io/goes/' in (site / 'sitemap.xml').read_text()

    (root / 'site/pages/goes.oui').unlink()
    second = b2(root, '-a', 'site', f'-sWEBCPP_SITE_DOCS={docs}')
    assert second.returncode == 0, (second.returncode, second.stdout[-6000:],
                                    second.stderr[-3000:])
    assert not (site / 'goes').exists(), 'the deleted page is still in bin/site'
    assert not (site / 'cards/goes.png').exists(), 'the deleted page\'s card is still there'
    assert 'goes/' not in (site / 'sitemap.xml').read_text()
    assert (site / 'index.html').is_file()


def test_a_failed_build_leaves_the_previous_bin_site_or_none(scratch: Path) -> None:
    # tools/site/site.jam's assemble lays bin/site/ out, indexes it and checks its links in
    # bin/site.tmp/, moved onto bin/site/ only once every step passes: a link check that fails
    # (here, before valid-html ever runs) must leave the previous build, never half of a new one.
    root = superproject(scratch)
    docs = docs_fixture(scratch, root)
    first = b2(root, '-a', 'site', f'-sWEBCPP_SITE_DOCS={docs}')
    assert first.returncode == 0, (first.returncode, first.stdout[-4000:], first.stderr[-2000:])
    site = root / 'bin/site'
    before = (site / 'index.html').read_text()
    libraries = sorted(build.parent.name for build in (root / 'libs').glob('*/build.jam'))
    page = docs / f'libs/{libraries[0]}/doc/html/index.html'
    page.write_text(page.read_text().replace('</body>', '<a href="nowhere.html">gone</a></body>'))
    second = b2(root, '-a', 'site', f'-sWEBCPP_SITE_DOCS={docs}')
    assert second.returncode != 0, (second.returncode, second.stdout[-4000:], second.stderr[-2000:])
    output = second.stdout + second.stderr
    assert 'fault' in output and 'nowhere.html' in output, output[-4000:]
    # The fault is the link check's, inside site-pages, well before valid-html could run on what
    # it writes: html-validate is never invoked, so a report naming a file is only ever this one.
    assert 'html-validate' not in output, output[-4000:]
    assert site.is_dir(), 'bin/site must still exist: the previous build, never half of a new one'
    assert (site / 'index.html').read_text() == before, 'bin/site must be the previous build, unchanged'


def test_the_release_channel_needs_its_version(scratch: Path) -> None:
    root = superproject(scratch)
    result = b2(root, 'site', '-sWEBCPP_SITE=release', f'-sWEBCPP_SITE_DOCS={scratch}')
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert '-sWEBCPP_SITE_VERSION' in result.stdout + result.stderr, result.stdout
    assert not (root / 'bin/site').exists()


def test_valid_html_fails_the_build_naming_the_file(scratch: Path) -> None:
    # /webcpp/site//valid-html (site/Jamfile), b2 site's last step, runs html-validate over every
    # page of bin/site/: a page that is not valid HTML fails the build, naming the file and the
    # fault, after bin/site/ already holds this build (site-pages has moved it there).
    root = superproject(scratch)
    docs = docs_fixture(scratch, root)
    libraries = sorted(build.parent.name for build in (root / 'libs').glob('*/build.jam'))
    page = docs / f'libs/{libraries[0]}/doc/html/index.html'
    page.write_text(page.read_text().replace(
        '<h2 id="usage">Usage</h2>', '<h2 id="usage">Usage</h2><ul><li><p>Unclosed</li></ul>'))
    result = b2(root, '-a', 'site', f'-sWEBCPP_SITE_DOCS={docs}')
    assert result.returncode != 0, (result.returncode, result.stdout[-4000:], result.stderr[-2000:])
    output = result.stdout + result.stderr
    assert 'valid-html' in output, output[-4000:]
    assert f'libs/{libraries[0]}/index.html' in output, output[-4000:]


# A page of the site's own, whose text holds a line of trailing whitespace: valid-html's two
# passes (site/Jamfile) must still catch it there, on no page outside docs/ and libs/.
TRAILING_PAGE = '\n'.join([
    '// Copyright (c) 2026 WebCpp.org',
    '//',
    '// Distributed under the Boost Software License, Version 1.0. (See',
    '// accompanying file LICENSE_1_0.txt or copy at',
    '// https://www.boost.org/LICENSE_1_0.txt)',
    '',
    'root = Page("Trailing", "A page of the test of b2 site, whose text holds a line of trailing '
    'whitespace, which valid-html must still catch on the site\'s own pages.", [text])',
    'text = Text("line one\\nline two with trailing space \\nline three")',
    '',
])


def test_valid_html_allows_trailing_whitespace_inside_a_librarys_pre(scratch: Path) -> None:
    # The relaxed pass (.htmlvalidate.docs.json), for docs/ and libs/ alone, turns
    # no-trailing-whitespace off: a listing of a library's guide may show it as content.
    root = superproject(scratch)
    docs = docs_fixture(scratch, root)
    libraries = sorted(build.parent.name for build in (root / 'libs').glob('*/build.jam'))
    page = docs / f'libs/{libraries[0]}/doc/html/index.html'
    page.write_text(page.read_text().replace(
        '<h2 id="usage">Usage</h2>',
        '<h2 id="usage">Usage</h2><pre>\nline with trailing space \n</pre>'))
    result = b2(root, '-a', 'site', f'-sWEBCPP_SITE_DOCS={docs}')
    assert result.returncode == 0, (result.returncode, result.stdout[-4000:], result.stderr[-2000:])


def test_valid_html_still_fails_on_the_sites_own_trailing_whitespace(scratch: Path) -> None:
    # The strict pass (.htmlvalidate.json), for every page outside docs/ and libs/, keeps
    # no-trailing-whitespace on: the site's own pages are React's, which writes no such line on
    # its own, so one that holds any is a fault of the page's text, never formatting to allow.
    root = superproject(scratch)
    docs = docs_fixture(scratch, root)
    (root / 'site/pages/trailing.oui').write_text(TRAILING_PAGE)
    result = b2(root, '-a', 'site', f'-sWEBCPP_SITE_DOCS={docs}')
    assert result.returncode != 0, (result.returncode, result.stdout[-4000:], result.stderr[-2000:])
    output = result.stdout + result.stderr
    assert 'no-trailing-whitespace' in output, output[-4000:]
    assert 'trailing/index.html' in output, output[-4000:]


def test_a_channel_is_preview_or_release(scratch: Path) -> None:
    root = superproject(scratch)
    result = b2(root, 'site', '-sWEBCPP_SITE=draft', f'-sWEBCPP_SITE_DOCS={scratch}')
    assert result.returncode != 0, (result.stdout, result.stderr)
    output = result.stdout + result.stderr
    assert '-sWEBCPP_SITE=draft' in output and 'preview' in output and 'release' in output, (
        output)
    assert not (root / 'bin/site').exists()


CASES: list[Callable[[Path], None]] = [
    test_b2_site_builds_the_whole_site_and_forgets_a_deleted_page,
    test_a_failed_build_leaves_the_previous_bin_site_or_none,
    test_valid_html_fails_the_build_naming_the_file,
    test_valid_html_allows_trailing_whitespace_inside_a_librarys_pre,
    test_valid_html_still_fails_on_the_sites_own_trailing_whitespace,
    test_the_release_channel_needs_its_version,
    test_a_channel_is_preview_or_release,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'site_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    if not (ROOT / 'site/Jamfile').is_file():
        print('site_test: site/ is not checked out, so there is no site to build; nothing tested')
        return 0
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='webcpp site ') as scratch:
            case(Path(scratch))
        print(f'{case.__name__}: ok')
    print('site_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
