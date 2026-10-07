#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/doc: `b2 libs/demo/doc` builds the fixture library's page with its reference from
MrDocs; a public function without a Doc Comment, a template parameter without @tparam and a
detail symbol without a brief each fail it, naming the symbol and the file; doc-check and the
check of the rendered page run on it; MrDocs is found where the build looks for it, or named when
it is not there; and `b2 doc` builds the index page from every library's meta/libraries.json.

Each case builds a scratch superproject, at a path that holds a space, whose libs/demo is the
fixture library demo, a git repository of its own as a library's submodule is. Run with the
names of some cases to run only those.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from html import unescape
from pathlib import Path

import harness

HEADER = 'libs/demo/include/webcpp/demo/answer.hpp'

PAGE = 'libs/demo/doc/html/index.html'

# U+2010, the hyphen MrDocs writes for -, written as an escape.
HYPHEN = '\u2010'


def mrdocs_root() -> Path:
    """The directory MrDocs is installed in, which holds bin/mrdocs: $MRDOCS_ROOT, else this
    checkout's .local/mrdocs."""
    configured = os.environ.get('MRDOCS_ROOT')
    root = Path(configured) if configured else harness.ROOT / '.local/mrdocs'
    if not (root / 'bin/mrdocs').is_file():
        raise RuntimeError(f'no {root}/bin/mrdocs: install MrDocs 2026.9.29 there, or set '
                           'MRDOCS_ROOT')
    return root


def prepare(root: Path) -> None:
    """Gives the scratch superproject root the MrDocs of this checkout, in its .local, and makes
    its libs/demo a git repository, whose files doc-check reads."""
    (root / '.local/mrdocs').symlink_to(mrdocs_root())
    subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=root / 'libs/demo', check=True)


def edit(root: Path, path: str, old: str, new: str) -> None:
    """Replaces the one occurrence of old in the file path of the scratch superproject root."""
    harness.replace(root / path, old, new)


def at(root: Path, path: str, text: str) -> str:
    """<path>:<line>, the line being the one of path where text is, which must be there once; the
    path is the real one, which b2 and the tools it runs name, macOS's /var being /private/var."""
    lines = [number for number, line in enumerate((root / path).read_text().splitlines(), 1)
             if text in line]
    assert len(lines) == 1, (path, text, lines)
    return f'{(root / path).resolve()}:{lines[0]}'


def page_text(root: Path) -> str:
    """The text of the demo page's content, without its markup, as a reader sees it."""
    html = (root / PAGE).read_text()
    content = html[html.index('<div id="content">'):]
    return re.sub(r'<[^>]+>', '', content)


def test_page_builds_with_its_reference(root):
    prepare(root)
    result = harness.run_b2(root, 'libs/demo/doc')
    harness.expect(result, True)
    html = (root / PAGE).read_text()
    # The page, the example and its output, and the reference of every public symbol.
    assert '<h1>demo: the fixture library</h1>' in html, html[:2000]
    assert 'The answer is 42.' in html and 'caught: boom' in html, html
    for anchor in ('webcpp-demo-answer', 'webcpp-demo-twice'):
        assert f'id="{anchor}"' in html, (anchor, html)
    text = page_text(root)
    assert 'Returns a value added to itself.' in text, text
    assert 'An arithmetic type.' in text and 'Twice the value.' in text, text
    # Its source links to the library's repository, and detail is MrDocs's to hide.
    assert 'https://github.com/webcpporg/demo/blob/main/include/webcpp/demo/answer.hpp#L' in html
    assert 'id="webcpp-demo-detail-sum"' not in html, html
    # The first row of MrDocs's tables, which names their columns, is their header; and the page
    # has no footer, which would hold nothing.
    assert re.search(r'<thead>\s*<tr>\s*<th\b[^>]*>Name</th>\s*<th\b[^>]*>Description</th>',
                     html), html
    assert 'id="footer"' not in html, html
    # MrDocs's escapes are decoded: what MrDocs read as _ and - shows as _ and -.
    assert 'fixture&apos;s' not in html and '&hyphen;' not in html and HYPHEN not in html, html
    assert "the fixture's test expects" in text, text
    # The page lives in the library, and is built again from scratch the same.
    assert (root / 'libs/demo/doc/html/index.html').is_file()
    again = harness.run_b2(root, '-a', 'libs/demo/doc')
    harness.expect(again, True)
    assert (root / PAGE).read_text() == html


def test_undocumented_function_fails_naming_it(root):
    prepare(root)
    edit(root, HEADER, '}  // namespace webcpp::demo',
         'int undocumented(int value);\n\n}  // namespace webcpp::demo')
    result = harness.run_b2(root, 'libs/demo/doc')
    harness.expect(result, False, f'{at(root, HEADER, "int undocumented(")}:',
                   'undocumented: function is undocumented')
    # MrDocs's request for a bug report, which follows each warning, is not a bug.
    assert 'please report it' not in result.stdout, result.stdout[-4000:]
    assert not (root / PAGE).exists()


def test_what_mrdocs_defaults_would_hide_fails(root):
    # With its defaults, MrDocs documents a parameter with the brief of its type
    # (auto-function-metadata), and counts a class that a documented function returns as
    # documented (auto-relates).
    prepare(root)
    edit(root, HEADER, '}  // namespace webcpp::demo',
         '/** A box of one value. */\n'
         'struct box {\n'
         '    /** The value. */\n'
         '    int value;\n'
         '};\n\n'
         '/** Returns the value a box holds.\n\n'
         '    @return The value.\n'
         '*/\n'
         'int unbox(box held);\n\n'
         'struct widget {};\n\n'
         '/** Makes a widget.\n\n'
         '    @return The widget.\n'
         '*/\n'
         'widget make_widget();\n\n'
         '}  // namespace webcpp::demo')
    result = harness.run_b2(root, 'libs/demo/doc')
    harness.expect(result, False,
                   f'{at(root, HEADER, "int unbox(box held);")}:',
                   "unbox: Missing documentation for parameter 'held'",
                   f'{at(root, HEADER, "struct widget {};")}:', 'widget: record is undocumented')


def test_missing_tparam_fails_naming_the_template(root):
    prepare(root)
    edit(root, HEADER, '    @tparam T An arithmetic type.\n', '')
    result = harness.run_b2(root, 'libs/demo/doc')
    harness.expect(result, False,
                   f'{at(root, HEADER, "constexpr T twice(")}: webcpp::demo::twice: the template '
                   'parameter T has no @tparam')
    assert not (root / PAGE).exists()


def test_detail_without_brief_fails_naming_it(root):
    prepare(root)
    edit(root, HEADER,
         '/** Returns the sum of two values, with which twice adds a value to itself. */\n', '')
    result = harness.run_b2(root, 'libs/demo/doc')
    harness.expect(result, False,
                   f'{at(root, HEADER, "constexpr T sum(")}: webcpp::demo::detail::sum: a detail '
                   'symbol needs a brief')


def test_page_needs_its_reference(root):
    prepare(root)
    jamfile = 'libs/demo/doc/Jamfile'
    edit(root, jamfile, 'webcpp.reference demo ;\n', '')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), False,
                   'webcpp.doc demo: the page includes the library\'s reference, and '
                   'libs/demo/doc/Jamfile declares none; add webcpp.reference demo ;')
    # A page or a reference is the library's whose doc directory declares it.
    edit(root, jamfile, 'webcpp.doc demo : demo.adoc ;\n', 'webcpp.reference other ;\n')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), False,
                   f'webcpp.reference is declared in {(root / "libs/demo/doc").resolve()}, which '
                   'is not libs/other/doc')


def test_mrdocs_is_found_or_named(root):
    prepare(root)
    installed = mrdocs_root()
    (root / '.local/mrdocs').unlink()
    # Nowhere: not at -sMRDOCS, not in .local and not on PATH.
    result = harness.run_b2(root, 'libs/demo/doc')
    harness.expect(result, False, 'MrDocs', f'{root.resolve()}/.local/mrdocs/bin/mrdocs', 'PATH',
                   '-sMRDOCS=<path>')
    # On PATH.
    path = f'{installed}/bin{os.pathsep}{os.environ["PATH"]}'
    harness.expect(harness.run_b2(root, 'libs/demo/doc', env_extra={'PATH': path}), True)
    shutil.rmtree(root / 'libs/demo/doc/html')
    # At -sMRDOCS, which names a file that must be there.
    harness.expect(harness.run_b2(root, '-a', f'-sMRDOCS={installed}/bin/mrdocs',
                                  'libs/demo/doc'), True)
    assert (root / PAGE).is_file()
    harness.expect(harness.run_b2(root, '-sMRDOCS=/nowhere/mrdocs', 'libs/demo/doc'), False,
                   '-sMRDOCS=/nowhere/mrdocs', 'is not a file')


def test_clang_is_given(root):
    prepare(root)
    clang = shutil.which('clang++')
    assert clang, 'no clang++ on PATH'
    harness.expect(harness.run_b2(root, f'-sCLANG={clang}', 'libs/demo/doc'), True)
    harness.expect(harness.run_b2(root, '-sCLANG=/nowhere/clang++', 'libs/demo/doc'), False,
                   '-sCLANG=/nowhere/clang++ is not a file')


def test_library_settings_replace_the_shared_ones(root):
    prepare(root)
    edit(root, HEADER, '}  // namespace webcpp::demo',
         'int undocumented(int value);\n\n}  // namespace webcpp::demo')
    settings = (root / 'libs/demo/doc/mrdocs.yml').resolve()
    with settings.open('a') as file:
        file.write('exclude-symbols:\n  - \'webcpp::demo::undocumented\'\n')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), True)
    assert 'webcpp-demo-undocumented' not in (root / PAGE).read_text()
    # What makes the reference strict is the shared settings' alone.
    with settings.open('a') as file:
        file.write('warn-as-error: false\n')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), False,
                   f'{settings}:', 'warn-as-error is set for every library by '
                   'tools/doc/mrdocs.yml.in')


def test_doc_check_and_rendered_check_run(root):
    prepare(root)
    page = 'libs/demo/doc/demo.adoc'
    # doc-check, with --complete: every example is shown.
    edit(root, page, '[listing]\n----\ninclude::{examples}/catches.expected[]\n----\n', '')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), False,
                   'catches.cpp: the page shows neither its code nor its output')
    edit(root, page, 'on:\n\n', 'on:\n\n[listing]\n----\ninclude::{examples}/catches.expected[]'
                                '\n----\n')
    # doc-check reads the library's files for references to the page.
    stale = 'doc' + ': #nowhere'
    edit(root, HEADER, 'namespace webcpp::demo {\n',
         f'// Why ({stale}).\nnamespace webcpp::demo {{\n')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), False,
                   'answer.hpp:10: names no anchor of the page: #nowhere')
    edit(root, HEADER, f'// Why ({stale}).\n', '')
    # The rendered page: a span of inline code that does not close.
    edit(root, page, 'it.\n\n[#quick-start]', 'it, `unclosed.\n\n[#quick-start]')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), False,
                   'a backtick outside code, a span of inline code that did not close')
    assert not (root / PAGE).exists()


def test_index_lists_every_library(root):
    prepare(root)
    # A second library, a port, with a page of its own to link to.
    other = (root / 'libs/other').resolve()
    (other / 'meta').mkdir(parents=True)
    (other / 'doc').mkdir()
    (other / 'build.jam').write_text('project /webcpp/other ;\n')
    (other / 'doc/Jamfile').write_text('')
    (other / 'meta/libraries.json').write_text(
        '{\n'
        '    "key": "other",\n'
        '    "name": "Other",\n'
        '    "authors": ["WebCpp.org"],\n'
        '    "description": "A port, whose description holds C++, a_b, a | and {braces}.",\n'
        '    "category": ["Testing"],\n'
        '    "cxxstd": "20",\n'
        '    "port-of": {\n'
        '        "name": "original.js",\n'
        '        "language": "JavaScript",\n'
        '        "version": "1.2.3",\n'
        '        "url": "https://github.com/webcpporg/original",\n'
        '        "licence": "MIT"\n'
        '    }\n'
        '}\n')
    result = harness.run_b2(root, 'doc')
    harness.expect(result, True)
    html = (root / 'doc/html/index.html').read_text()
    rows = re.findall(r'<tr>(.*?)</tr>', html, flags=re.S)
    cells = [[unescape(re.sub(r'<[^>]+>', '', cell)).strip()
              for cell in re.findall(r'<t[dh]\b[^>]*>(.*?)</t[dh]>', row, flags=re.S)]
             for row in rows]
    assert cells == [
        ['Library', 'Description', 'Ports'],
        ['demo', 'The smallest library the superproject builds, which the tests of its build '
                 'place in libs/demo.', 'original'],
        ['Other', 'A port, whose description holds C++, a_b, a | and {braces}.',
         'original.js 1.2.3, in JavaScript (MIT)'],
    ], cells
    assert '<a href="../../libs/demo/doc/html/index.html">demo</a>' in html, html
    assert '<a href="../../libs/other/doc/html/index.html">Other</a>' in html, html
    assert '<a href="https://github.com/webcpporg/original">original.js 1.2.3</a>' in html, html
    # And each library's page, which the index links to, is built with it.
    assert (root / PAGE).is_file()
    # A library without meta/libraries.json is named.
    (other / 'meta/libraries.json').unlink()
    harness.expect(harness.run_b2(root, 'doc'), False,
                   f'{other}/meta/libraries.json: there is no such file')


CASES = [
    test_page_builds_with_its_reference,
    test_undocumented_function_fails_naming_it,
    test_what_mrdocs_defaults_would_hide_fails,
    test_missing_tparam_fails_naming_the_template,
    test_detail_without_brief_fails_naming_it,
    test_page_needs_its_reference,
    test_mrdocs_is_found_or_named,
    test_clang_is_given,
    test_library_settings_replace_the_shared_ones,
    test_doc_check_and_rendered_check_run,
    test_index_lists_every_library,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('doc_test', CASES, sys.argv[1:]))
