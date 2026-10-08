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
it is not there; `b2 doc` builds the index page from every library's meta/libraries.json,
linking each page in the tree, or, with -sWEBCPP_INDEX=site, where the site serves it, and fails
on a library whose doc Jamfile declares no page, or one that is not there; a page
shows the counts its build computes, of the programs b2 recorded and of the twins of the fixture
library oracle_demo, whose divergent twin's output the page must show; and a page's link into
another library's page, in either layout, is checked against that page, built first; the
reference of the fixture library component_demo parses natively, with the requirements its doc
Jamfile gives, the header of its world, which builds only for WASI, documents it and fails on an
undocumented function of it, and without those requirements fails naming the header; the Doc
Comments of the header's wasip3 branch, which that reference does not parse, are checked with
the other requirements the doc Jamfile gives, and an undocumented function, a detail symbol
without a brief and an undocumented macro there each fail it, the first the page too; and
MrDocs and clang++ given at paths that hold a space are found.

Each case builds a scratch superproject, at a path that holds a space, whose libs/demo is the
fixture library demo, a git repository of its own as a library's submodule is; the cases of
twins and links add oracle_demo beside it, and the case of WASI component_demo. Run with the
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

COMPONENT_PAGE = 'libs/component_demo/doc/html/index.html'
WORLD = 'libs/component_demo/include/webcpp/component_demo/world.hpp'

ORACLE_PAGE = 'libs/oracle_demo/doc/html/index.html'
ORACLE_SOURCE = 'libs/oracle_demo/doc/oracle_demo.adoc'
ORACLE_HEADER = 'libs/oracle_demo/include/webcpp/oracle_demo.hpp'

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


def add_oracle_demo(root: Path) -> None:
    """Places the fixture library oracle_demo beside demo in the scratch superproject root, a git
    repository of its own too."""
    shutil.copytree(harness.FIXTURES / 'oracle_demo', root / 'libs/oracle_demo',
                    ignore=harness.built)
    subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=root / 'libs/oracle_demo', check=True)


def add_component_demo(root: Path) -> None:
    """Places the fixture library component_demo beside demo in the scratch superproject root, a
    git repository of its own too, with this checkout's wit-bindgen and WIT, which its bindings
    need."""
    shutil.copytree(harness.FIXTURES / 'component_demo', root / 'libs/component_demo',
                    ignore=harness.built)
    subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=root / 'libs/component_demo',
                   check=True)
    harness.link_wasi_tools(root)


def add_paged(root: Path, name: str) -> Path:
    """Places a library name, with a page of its own whose one section is #only-<name> and a
    header its tests compile alone, in the scratch superproject root, a git repository of its
    own too, and returns its directory."""
    library = root / 'libs' / name
    guard = f'WEBCPP_{name.upper()}_HPP'
    (library / 'include/webcpp').mkdir(parents=True)
    (library / 'doc').mkdir()
    (library / 'build.jam').write_text(f'project /webcpp/{name} ;\n\n'
                                       f'alias {name} : : : : <include>include ;\n')
    (library / 'README.md').write_text(f'# {name}\n')
    (library / 'test').mkdir()
    (library / 'test/Jamfile').write_text('import webcpp ;\n\n'
                                          f'webcpp.headers-alone {name} : ../include ;\n')
    (library / f'include/webcpp/{name}.hpp').write_text(
        f'#ifndef {guard}\n#define {guard}\n\nnamespace webcpp::{name} {{\n\n'
        '/** Returns three.\n\n    @return 3.\n*/\nconstexpr int three() noexcept {\n'
        f'    return 3;\n}}\n\n}}  // namespace webcpp::{name}\n\n#endif\n')
    (library / 'doc/Jamfile').write_text(f'import webcpp ;\n\nwebcpp.doc {name} : {name}.adoc ;\n'
                                         f'webcpp.reference {name} ;\n')
    (library / f'doc/{name}.adoc').write_text(f'= {name}\n\n[#only-{name}]\n== Only here\n\n'
                                              f'{name} returns three.\n\n[#reference]\n'
                                              '== Reference\n\ninclude::{reference}'
                                              '[leveloffset=+1]\n')
    subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=library, check=True)
    return library


def add_third(root: Path) -> None:
    """Places a third library, third, with a page of its own whose one section is #only-third, in
    the scratch superproject root."""
    add_paged(root, 'third')


def page_text(root: Path, page: str = PAGE) -> str:
    """The text of a page's content, the demo page's by default, without its markup, as a reader
    sees it, its lines joined."""
    html = (root / page).read_text()
    content = html[html.index('<div id="content">'):]
    return ' '.join(re.sub(r'<[^>]+>', '', content).split())


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
    # The reference starts at the library's namespace: the sections of the global namespace
    # and of webcpp, which hold one row each, are gone, and nothing links to them.
    assert 'Global namespace' not in html and 'id="index"' not in html, html
    assert 'id="webcpp"' not in html and 'href="#webcpp"' not in html, html
    # A name of the reference may break after each :: (postprocess.mjs).
    assert re.search(r'<h3 id="webcpp-demo">(<a class="anchor"[^>]*></a>)?webcpp::<wbr>demo</h3>',
                     html), html
    # Its source links to the library's repository, and detail is MrDocs's to hide.
    assert 'https://github.com/webcpporg/demo/blob/main/include/webcpp/demo/answer.hpp#L' in html
    assert 'id="webcpp-demo-detail-sum"' not in html, html
    # The first row of MrDocs's tables, which names their columns, is their header; and the page
    # has no footer, which would hold nothing.
    assert re.search(r'<thead>\s*<tr>\s*<th\b[^>]*>Name</th>\s*<th\b[^>]*>Description</th>',
                     html), html
    assert 'id="footer"' not in html, html
    # Each table is in a box of its own, which scrolls when the table is too wide for the page.
    assert html.count('<div class="table-scroll">\n<table class="tableblock') == \
        html.count('<table class="tableblock') > 0, html
    # MrDocs's escapes are decoded: what MrDocs read as _ and - shows as _ and -.
    assert 'fixture&apos;s' not in html and '&hyphen;' not in html and HYPHEN not in html, html
    # An apostrophe of a brief reads as the guide's, curly, and one in code stays straight.
    assert 'the fixture&#8217;s test expects, the value of <code class="whole">L\'*\'</code> and ' \
        'never of <code class="whole">L\'x\'</code>.' in html, html
    # A name too long for a phone's line breaks after each _, in its heading and in the table
    # that links it, and never inside a listing or an attribute.
    broken = 'a_|very_|long_|snake_|case_|name'.replace('|', '<wbr class="part">')
    assert re.search(r'<h3 id="webcpp-demo-a_very_long_snake_case_name">(<a class="anchor"[^>]*>'
                     rf'</a>)?webcpp::<wbr><a href="#webcpp-demo">demo</a>::<wbr>{broken}</h3>',
                     html), html
    assert (f'<a href="#webcpp-demo-a_very_long_snake_case_name"><code>{broken}</code></a>'
            in html), html
    listings = re.findall(r'<pre\b[^>]*>.*?</pre>', html, flags=re.S)
    assert any('a_very_long_snake_case_name' in block for block in listings), listings
    assert all('<wbr' not in block for block in listings), listings
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


def test_declarator_sharing_a_comment_fails(root):
    # clang gives green the comment of red, and MrDocs counts it as documented.
    prepare(root)
    edit(root, HEADER, '}  // namespace webcpp::demo',
         '/** The colours. */\n'
         'enum class colour {\n'
         '    /** Red. */\n'
         '    red, green,\n'
         '};\n\n'
         '}  // namespace webcpp::demo')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), False,
                   f'{at(root, HEADER, "red, green,")}: webcpp::demo::colour::green: has no Doc '
                   'Comment of its own; clang gives it the one of webcpp::demo::colour::red')


def test_undocumented_enumerator_fails(root):
    prepare(root)
    edit(root, HEADER, '}  // namespace webcpp::demo',
         '/** The colours. */\n'
         'enum class colour {\n'
         '    red,\n'
         '};\n\n'
         '}  // namespace webcpp::demo')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), False,
                   f'{at(root, HEADER, "    red,")}:',
                   'webcpp::demo::colour::red: Missing documentation for enum value')


def test_macros_are_documented_and_listed(root):
    prepare(root)
    edit(root, HEADER, 'namespace webcpp::demo {\n',
         '#define WEBCPP_DEMO_UNDOCUMENTED 1\n\n'
         'namespace webcpp::demo {\n')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), False,
                   f'{at(root, HEADER, "#define WEBCPP_DEMO_UNDOCUMENTED")}:',
                   'WEBCPP_DEMO_UNDOCUMENTED: macro is undocumented')
    # Documented, it has a section of its own, and the reference lists the library's macros.
    edit(root, HEADER, '#define WEBCPP_DEMO_UNDOCUMENTED 1\n',
         '/** The answer, as a macro. */\n#define WEBCPP_DEMO_UNDOCUMENTED 1\n')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), True)
    html = (root / PAGE).read_text()
    assert 'id="WEBCPP_DEMO_UNDOCUMENTED"' in html, html
    assert re.search(r'<h3 id="webcpp-demo-macros">(<a class="anchor"[^>]*></a>)?Macros</h3>',
                     html), html
    assert re.search(r'<a href="#WEBCPP_DEMO_UNDOCUMENTED"><code( class="whole")?>'
                     r'WEBCPP_DEMO_UNDOCUMENTED</code></a>', html), html
    assert 'Global namespace' not in html, html


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


def test_library_settings_only_present_the_reference(root):
    prepare(root)
    settings = (root / 'libs/demo/doc/mrdocs.yml').resolve()
    text = settings.read_text()
    # A key of how the reference is presented is the library's to set.
    settings.write_text(text + 'sort-members: false\n')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), True)
    generated = (root / 'bin/libs/demo/doc/mrdocs.yml').read_text()
    assert 'sort-members: false\n' in generated, generated
    # Any other is refused, naming the file, the line and the key: one that narrows what is
    # documented, one that loosens the strictness, and one MrDocs does not know.
    for key, value in (('exclude-symbols', "\n  - 'webcpp::demo::answer'"),
                       ('warn-as-error', ' false'),
                       ('include-symbols', "\n  - 'webcpp::demo::twice'"),
                       ('implementation-defined', "\n  - 'webcpp::demo'"),
                       ('see-below', "\n  - 'webcpp::demo::answer'"),
                       ('no-such-key', ' true')):
        settings.write_text(text + f'{key}:{value}\n')
        line = text.count('\n') + 1
        harness.expect(harness.run_b2(root, 'libs/demo/doc'), False,
                       f'{settings}:{line}: {key} is not a setting a library may give its '
                       'reference')


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


def test_page_shows_the_counts_of_its_programs(root):
    # Counted from what demo's test and example Jamfiles declare, as b2 recorded it: each program
    # once, and each header compiled alone one.
    prepare(root)
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), True)
    text = page_text(root)
    assert ('demo has 2 examples: 2 built natively, 1 for wasip2 and 2 for wasip3. It has 9 '
            'tests, 1 of them a Boost.Test suite: 9 run natively, 6 on wasip2 and 6 on wasip3. '
            'Each of its 2 headers compiles alone.') in text, text
    # A program more is counted at the next build.
    edit(root, 'libs/demo/test/Jamfile', 'webcpp.run pass :',
         'webcpp.run pass_again : pass.cpp : <library>/webcpp/demo//demo : wasip2 ;\n'
         'webcpp.run pass :')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), True)
    assert 'It has 10 tests, 1 of them a Boost.Test suite: 9 run natively, 7 on wasip2 and 6 ' \
        'on wasip3.' in page_text(root), page_text(root)
    # A library that compiles no header alone has no header count, and no page.
    edit(root, 'libs/demo/test/Jamfile', 'webcpp.headers-alone demo : ../include ;\n', '')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), False,
                   'demo declares no webcpp.headers-alone: its headers are not counted',
                   'webcpp.doc demo: tools/doc/counts.py could not count')


def test_page_shows_twins_and_their_counts(root):
    prepare(root)
    add_oracle_demo(root)
    # No Node: the twins are counted, not run.
    harness.expect(harness.run_b2(root, 'libs/oracle_demo/doc'), True)
    text = page_text(root, ORACLE_PAGE)
    assert ('Of its 3 examples, 2 have a twin, the same program in JavaScript: 1 prints what its '
            'example prints, and 1 prints an output of its own. 1 has no twin.') in text, text
    # The twin's code and its own output, from the twins' directory webcpp.twins declares.
    html = (root / ORACLE_PAGE).read_text()
    assert 'Half of 7 is 3.5.' in html and 'squared is' in html, html
    # And the page must show every divergent twin's own output: doc-check is given the twins.
    edit(root, ORACLE_SOURCE, '[listing]\n----\ninclude::{twins}/half.expected[]\n----\n', '')
    harness.expect(harness.run_b2(root, 'libs/oracle_demo/doc'), False,
                   'half.expected: the page does not show this difference from the original')


def test_links_between_pages(root):
    prepare(root)
    add_oracle_demo(root)
    link = 'link:{webcpp-libs}/demo/{webcpp-page}#quick-start[demo]'
    edit(root, ORACLE_SOURCE, 'superproject.\n', f'superproject. It is built as {link} is.\n')
    reference = 'doc' + ': demo#holds'
    edit(root, ORACLE_HEADER, 'namespace webcpp::oracle_demo {\n',
         f'// See ({reference}).\nnamespace webcpp::oracle_demo {{\n')
    # In the tree, the link goes from libs/oracle_demo/doc/html/ to demo's page there; on the
    # site, from libs/oracle_demo/ to libs/demo/. Either is checked against demo's page, which
    # is built first.
    layouts = (((), '../../../demo/doc/html/index.html'),
               (('-sWEBCPP_INDEX=site',), '../demo/index.html'))
    for options, href in layouts:
        harness.expect(harness.run_b2(root, *options, 'libs/oracle_demo/doc'), True)
        html = (root / ORACLE_PAGE).read_text()
        assert f'href="{href}#quick-start"' in html, html
    assert list((root / 'bin/libs/demo/doc').rglob('index.html')), 'demo\'s page was not built'
    for options, href in layouts:
        for anchor, fault in (('nowhere', 'names no anchor of the page of demo: demo#nowhere'),
                              ('quick-start-01', 'demo#quick-start-01 ends in the number MrDocs '
                                                 'gives an overload')):
            edit(root, ORACLE_SOURCE, '#quick-start[demo]', f'#{anchor}[demo]')
            harness.expect(harness.run_b2(root, *options, 'libs/oracle_demo/doc'), False,
                           f'{href}#{anchor}: {fault}')
            edit(root, ORACLE_SOURCE, f'#{anchor}[demo]', '#quick-start[demo]')
    # A reference of the library's code to an anchor of another library's page.
    edit(root, ORACLE_HEADER, reference, 'doc' + ': demo#gone')
    harness.expect(harness.run_b2(root, 'libs/oracle_demo/doc'), False,
                   f'{at(root, ORACLE_HEADER, "// See (")}: names no anchor of the page of demo: '
                   'demo#gone')
    # And one to a library that has no page.
    edit(root, ORACLE_HEADER, 'demo#gone', 'nowhere#gone')
    harness.expect(harness.run_b2(root, 'libs/oracle_demo/doc'), False,
                   'libs/oracle_demo links the page of nowhere, and libs/nowhere/doc/Jamfile does '
                   'not exist')


def test_links_into_two_pages(root):
    # Two linked pages, each read for its own library's anchors: #only-third is third's alone,
    # and third is the second library the page links.
    prepare(root)
    add_oracle_demo(root)
    add_third(root)
    edit(root, ORACLE_SOURCE, 'superproject.\n',
         'superproject. It is built as link:{webcpp-libs}/demo/{webcpp-page}#quick-start[demo] '
         'and link:{webcpp-libs}/third/{webcpp-page}#only-third[third] are.\n')
    harness.expect(harness.run_b2(root, 'libs/oracle_demo/doc'), True)
    pages = {name: next((root / f'bin/libs/{name}/doc').rglob('index.html')).read_text()
             for name in ('demo', 'third')}
    assert 'id="only-third"' in pages['third'] and 'id="only-third"' not in pages['demo']
    assert 'id="quick-start"' in pages['demo'] and 'id="quick-start"' not in pages['third']
    # And each anchor is still looked for in its own library's page only.
    edit(root, ORACLE_SOURCE, '#only-third[third]', '#quick-start[third]')
    harness.expect(harness.run_b2(root, 'libs/oracle_demo/doc'), False,
                   '../../../third/doc/html/index.html#quick-start: names no anchor of the page '
                   'of third: third#quick-start')


def test_reference_reads_a_header_built_only_for_wasi(root):
    prepare(root)
    add_component_demo(root)
    # The header of the world builds only for WASI. The reference parses it natively, with the
    # requirements of the doc Jamfile: the bindings of wasip2, which their -headers target
    # generates on the native toolset, and the macro of p2.
    harness.expect(harness.run_b2(root, 'libs/component_demo/doc//reference'), True)
    reference = next((root / 'bin/libs/component_demo/doc').rglob('reference.adoc')).read_text()
    assert '[#webcpp-component_demo-text_of]' in reference, reference
    assert 'Returns the text a string of the world' in reference, reference
    assert (root / 'bin/generated/component_demo/demo-bindings-p2/demo_world.h').is_file()
    # The page shows it, and counts the header among those compiled alone, though only WASI
    # compiles it.
    harness.expect(harness.run_b2(root, 'libs/component_demo/doc'), True)
    text = page_text(root, COMPONENT_PAGE)
    assert ('component_demo has 5 tests: 2 run natively, 4 on wasip2 and 4 on wasip3; wasmtime '
            'serves 1 of them. Each of its 2 headers compiles alone') in text, text
    # An undocumented function of the header fails the reference, naming it.
    edit(root, WORLD, '}  // namespace webcpp::component_demo',
         'int undocumented(int value);\n\n}  // namespace webcpp::component_demo')
    harness.expect(harness.run_b2(root, 'libs/component_demo/doc//reference'), False,
                   f'{at(root, WORLD, "int undocumented(")}:',
                   'undocumented: function is undocumented')
    edit(root, WORLD, 'int undocumented(int value);\n\n', '')
    # Without the requirements a native parse needs, the header is not parsed, and the build
    # fails naming it.
    edit(root, 'libs/component_demo/doc/Jamfile',
         ' : <library>/webcpp/component_demo//demo-bindings-p2-headers\n'
         '  <define>WEBCPP_COMPONENT_DEMO_P2\n'
         '  : <library>/webcpp/component_demo//demo-bindings-p3-headers'
         ' <define>WEBCPP_COMPONENT_DEMO_P3 ;\n', ' ;\n')
    harness.expect(harness.run_b2(root, 'libs/component_demo/doc//reference'), False,
                   f'{at(root, WORLD, "#error")}:2: error: "webcpp/component_demo/world.hpp '
                   'builds for wasip2 or wasip3')


def test_reference_checks_each_branch_of_a_header(root):
    prepare(root)
    add_component_demo(root)
    # The header of the world has a branch for each WASI version, and the reference parses p2's.
    # The doc Jamfile gives p3's requirements too, with which the Doc Comments of the other branch
    # are checked, its bindings generated on the native toolset.
    harness.expect(harness.run_b2(root, 'libs/component_demo/doc//reference'), True)
    assert (root / 'bin/generated/component_demo/demo-bindings-p3/demo_world.h').is_file()
    # The reference's own parse sees p2's bindings alone: the check is its sibling, whose usage
    # requirements never reach it.
    database = (root / 'bin/libs/component_demo/doc/compile_commands.json').read_text()
    assert 'demo-bindings-p2' in database and 'demo-bindings-p3' not in database, database
    # In p3's branch alone, an undocumented function fails the page, built through its install
    # alone, as when another page links it; it, a detail symbol without a brief and an
    # undocumented macro each fail the reference, named, with p3's macro.
    branch = '    return "p3";\n}\n'
    edit(root, WORLD, branch, f'{branch}\nint undocumented_p3(int value);\n')
    harness.expect(harness.run_b2(root, 'libs/component_demo/doc//html'), False,
                   f'{at(root, WORLD, "int undocumented_p3(")}:',
                   'undocumented_p3: function is undocumented')
    assert not (root / COMPONENT_PAGE).exists()
    edit(root, WORLD, f'{branch}\nint undocumented_p3(int value);\n', branch)
    for planted, declared, message in (
            ('int undocumented_p3(int value);\n', 'int undocumented_p3(',
             'undocumented_p3: function is undocumented'),
            ('namespace detail {\ninline int helper_p3() {\n    return 3;\n}\n'
             '}  // namespace detail\n', 'inline int helper_p3(',
             'webcpp::component_demo::detail::helper_p3: a detail symbol needs a brief'),
            ('#define WEBCPP_COMPONENT_DEMO_ONLY_P3 3\n', '#define WEBCPP_COMPONENT_DEMO_ONLY_P3',
             'WEBCPP_COMPONENT_DEMO_ONLY_P3: macro is undocumented')):
        edit(root, WORLD, branch, f'{branch}\n{planted}')
        harness.expect(harness.run_b2(root, 'libs/component_demo/doc//reference'), False,
                       f'{at(root, WORLD, declared)}:', message,
                       '--define "WEBCPP_COMPONENT_DEMO_P3"')
        edit(root, WORLD, f'{branch}\n{planted}', branch)
    harness.expect(harness.run_b2(root, 'libs/component_demo/doc//reference'), True)


def test_tools_given_at_paths_with_spaces(root):
    # b2 splits the value of -s at its spaces; MrDocs and clang++ are found at a path that holds
    # one, as the scratch superproject's does.
    prepare(root)
    clang = shutil.which('clang++')
    assert clang, 'no clang++ on PATH'
    tools = root / 'linked tools'
    tools.mkdir()
    for name, tool in (('mrdocs', mrdocs_root() / 'bin/mrdocs'), ('clang++', Path(clang))):
        wrapper = tools / name
        wrapper.write_text(f'#!/bin/sh\nexec "{tool}" "$@"\n')
        wrapper.chmod(0o755)
    (root / '.local/mrdocs').unlink()
    harness.expect(harness.run_b2(root, f'-sMRDOCS={tools}/mrdocs', f'-sCLANG={tools}/clang++',
                                  'libs/demo/doc'), True)
    assert (root / PAGE).is_file()


def test_page_outside_git(root):
    # A library that is not a git checkout loads, and builds what needs no git; only the check
    # of its page, which reads the files git lists, names it.
    (root / '.local/mrdocs').symlink_to(mrdocs_root())
    harness.expect(harness.run_b2(root, 'libs/demo/doc//reference'), True)
    harness.expect(harness.run_b2(root, '-n', 'libs/demo/doc'), True)
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), False,
                   f'{(root / "libs/demo").resolve()}: is not a git checkout')


def test_counts_warn_and_fail_through_the_build(root):
    # A library's own counts.py: what it writes on its standard error is shown and is no count;
    # its failure stops the build with its message.
    prepare(root)
    script = root / 'libs/demo/doc/counts.py'
    script.write_text('import sys\n'
                      'print("counts.py: a warning, n-cases=99", file=sys.stderr, flush=True)\n'
                      'print("n-cases=3")\n')
    edit(root, 'libs/demo/doc/demo.adoc', 'compiles alone.\n', 'compiles alone. {n-cases} cases.\n')
    result = harness.run_b2(root, 'libs/demo/doc')
    harness.expect(result, True, 'counts.py: a warning, n-cases=99')
    assert 'compiles alone. 3 cases.' in page_text(root), page_text(root)
    script.write_text('import sys\nsys.exit("counts.py: no case file in fixtures")\n')
    harness.expect(harness.run_b2(root, 'libs/demo/doc'), False,
                   'counts.py: no case file in fixtures',
                   'webcpp.doc demo: tools/doc/counts.py could not count')


def test_index_lists_every_library(root):
    prepare(root)
    # A second library, a port, with a page of its own to link to.
    other = add_paged(root, 'other').resolve()
    (other / 'meta').mkdir()
    (other / 'meta/libraries.json').write_text(
        '{\n'
        '    "key": "other",\n'
        '    "name": "Other",\n'
        '    "authors": ["WebCpp.org"],\n'
        '    "description": "A port, whose description holds C++, a_b, a | and {braces}. It\'s '
        'the original\'s, but `it\'s` and https://example.org/it\'s stay \'straight\'.",\n'
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
    # The index links a library's page only when there is one: a doc Jamfile that declares no
    # page, empty or with the reference alone, fails the index, naming it, as does a page it
    # declares that is not there.
    declared = (other / 'doc/Jamfile').read_text()
    no_page = (f'{other}/doc/Jamfile: declares no page, webcpp.doc other : <page>.adoc ;, and '
               'every library of libs/ has a page, which the index links to')
    for jamfile in ('', 'import webcpp ;\n\nwebcpp.reference other ;\n',
                    'import webcpp ;\n\n# webcpp.doc other : other.adoc ;\n'
                    'webcpp.reference other ;\n'):
        (other / 'doc/Jamfile').write_text(jamfile)
        harness.expect(harness.run_b2(root, 'doc'), False, no_page)
    (other / 'doc/Jamfile').write_text(declared)
    (other / 'doc/other.adoc').rename(other / 'doc/moved.adoc')
    listed = subprocess.run([sys.executable, str(root / 'tools/doc/libraries.py'),
                             '--root', str(root), '--output', str(root / 'libraries.adoc')],
                            capture_output=True, text=True, check=False)
    assert listed.returncode == 1, (listed.returncode, listed.stdout, listed.stderr)
    assert (f'{other}/doc/other.adoc: there is no such file; libs/other/doc/Jamfile declares it '
            'the page of other, which the index links to') in listed.stdout, listed.stdout
    (other / 'doc/moved.adoc').rename(other / 'doc/other.adoc')
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
        ['Other', 'A port, whose description holds C++, a_b, a | and {braces}. It\u2019s the '
                  "original\u2019s, but `it's` and https://example.org/it's stay 'straight'.",
         'original.js 1.2.3, in JavaScript (MIT)'],
    ], cells
    assert '<a href="../../libs/demo/doc/html/index.html">demo</a>' in html, html
    assert '<a href="../../libs/other/doc/html/index.html">Other</a>' in html, html
    assert '<a href="https://github.com/webcpporg/original">original.js 1.2.3</a>' in html, html
    # And each library's page, which the index links to, is built with it.
    assert (root / PAGE).is_file()
    assert (other / 'doc/html/index.html').is_file()
    # For the site, where each library's page is libs/<name>/ beside the index, the same index
    # links there; tools/ci/assemble.py lays the site out so.
    result = harness.run_b2(root, 'doc', '-sWEBCPP_INDEX=site')
    harness.expect(result, True)
    html = (root / 'doc/html/index.html').read_text()
    assert '<a href="libs/demo/">demo</a>' in html, html
    assert '<a href="libs/other/">Other</a>' in html, html
    assert '../../libs/' not in html, html
    harness.expect(harness.run_b2(root, 'doc', '-sWEBCPP_INDEX=elsewhere'), False,
                   '-sWEBCPP_INDEX=elsewhere is neither tree nor site')
    # Without it, the index links the pages in the tree again.
    harness.expect(harness.run_b2(root, 'doc'), True)
    html = (root / 'doc/html/index.html').read_text()
    assert '<a href="../../libs/demo/doc/html/index.html">demo</a>' in html, html
    # A library without meta/libraries.json is named.
    (other / 'meta/libraries.json').unlink()
    harness.expect(harness.run_b2(root, 'doc'), False,
                   f'{other}/meta/libraries.json: there is no such file')


CASES = [
    test_page_builds_with_its_reference,
    test_undocumented_function_fails_naming_it,
    test_what_mrdocs_defaults_would_hide_fails,
    test_declarator_sharing_a_comment_fails,
    test_undocumented_enumerator_fails,
    test_macros_are_documented_and_listed,
    test_missing_tparam_fails_naming_the_template,
    test_detail_without_brief_fails_naming_it,
    test_page_needs_its_reference,
    test_mrdocs_is_found_or_named,
    test_clang_is_given,
    test_library_settings_only_present_the_reference,
    test_doc_check_and_rendered_check_run,
    test_page_shows_the_counts_of_its_programs,
    test_page_shows_twins_and_their_counts,
    test_links_between_pages,
    test_links_into_two_pages,
    test_reference_reads_a_header_built_only_for_wasi,
    test_reference_checks_each_branch_of_a_header,
    test_tools_given_at_paths_with_spaces,
    test_page_outside_git,
    test_counts_warn_and_fail_through_the_build,
    test_index_lists_every_library,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('doc_test', CASES, sys.argv[1:]))
