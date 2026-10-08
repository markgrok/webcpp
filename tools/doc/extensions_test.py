#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks the extensions every page is converted with, highlighter.mjs and postprocess.mjs, by
converting samples with Asciidoctor.js as webcpp.doc does.

MrDocs writes its reference with an HTML character reference in place of each character that
AsciiDoc could read as markup, &lowbar; for _ and &hyphen; for -, and links inside its synopses.
The page must show the characters MrDocs read, the ASCII hyphen among them, and keep those links;
and a listing that is plain code must show what it holds, a character reference included.

Asciidoctor.js comes from tools/doc/node_modules, which npm ci installs when it is missing.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from html import unescape
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import reference  # noqa: E402
ASCIIDOCTOR = HERE / 'node_modules/asciidoctor/bin/asciidoctor'

# U+2010, which &hyphen; stands for, written as an escape.
HYPHEN = '\u2010'

# The page MrDocs's text is included in, as a library's page includes its reference.
HEADER = '= Sample\n:source-language: cpp\n\n'


def installed() -> None:
    """Installs tools/doc's packages with npm ci when they are missing."""
    if not ASCIIDOCTOR.is_file():
        subprocess.run(['npm', 'ci', '--no-audit', '--no-fund', '--prefer-offline',
                        '--loglevel=error'], cwd=HERE, check=True)


def convert(text: str) -> str:
    """The HTML Asciidoctor.js writes for the AsciiDoc text, with the extensions and the options
    of webcpp.doc."""
    with tempfile.TemporaryDirectory(prefix='doc extensions ') as scratch:
        source = Path(scratch) / 'page.adoc'
        source.write_text(HEADER + text)
        output = Path(scratch) / 'page.html'
        command = ['node', str(ASCIIDOCTOR), '-r', str(HERE / 'highlighter.mjs'), '-r',
                   str(HERE / 'postprocess.mjs'), '-v', '--failure-level', 'INFO', '-S', 'unsafe',
                   '-a', 'source-highlighter=hljs-static', '-o', str(output), str(source)]
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, check=False)
        assert completed.returncode == 0, completed.stdout
        # -v prints the file it converts, and any message besides would be a fault.
        said = [line for line in completed.stdout.splitlines()
                if not line.startswith('converting file ')]
        assert said == [], completed.stdout
        return output.read_text()


def body(html: str) -> str:
    """The page's content, without its head, whose style holds the highlighter's theme."""
    return html[html.index('<div id="content">'):]


def code_text(html: str) -> list[str]:
    """The text of each listing of the page, with its markup removed and its references read, as
    a reader sees it."""
    blocks = re.findall(r'<pre\b[^>]*>(.*?)</pre>', html, flags=re.S)
    return [unescape(re.sub(r'<[^>]+>', '', block)) for block in blocks]


def rendered_check(page: str) -> subprocess.CompletedProcess:
    """doc-check.py --rendered on the page."""
    with tempfile.TemporaryDirectory(prefix='doc extensions ') as scratch:
        path = Path(scratch) / 'index.html'
        path.write_text(page)
        return subprocess.run([sys.executable, str(HERE / 'doc-check.py'), '--rendered', str(path)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              check=False)


def test_prose_shows_what_mrdocs_read(_: None) -> None:
    page = convert('Returns x&hyphen;y, `a&lowbar;b`, &lcub;braces&rcub;, '
                   'an apostrophe&apos;s and &lt;angle&gt;&period;\n\n'
                   f'A hyphen MrDocs wrote itself: a{HYPHEN}b.\n\n'
                   'Written in C&plus;&plus; and {cpp}, with a &grave;tick&grave;.\n')
    html = body(page)
    assert ('<p>Returns x-y, <code class="whole">a_b</code>, {braces}, an apostrophe\'s and '
            '&lt;angle&gt;.</p>') in html, html
    assert '<p>A hyphen MrDocs wrote itself: a-b.</p>' in html, html
    assert HYPHEN not in html, html
    assert re.search(r'&(hyphen|lowbar|lcub|rcub|apos|period|plus|grave);', html) is None, html
    # A + and a backtick stay references, as Asciidoctor writes {cpp}: in a page's text, a
    # literal ++ or backtick is the mark of a fault the check of the rendered page looks for.
    assert '<p>Written in C&#43;&#43; and C&#43;&#43;, with a &#96;tick&#96;.</p>' in html, html
    assert rendered_check(page).returncode == 0, rendered_check(page).stdout


def test_synopsis_keeps_its_links(_: None) -> None:
    html = body(convert('[#box]\n== box\n\n'
                        '[source,cpp,subs="verbatim,replacements,macros,-callouts"]\n'
                        '----\n'
                        'template&lt;class&period;&period;&period; Ts&gt;\n'
                        'link:#box[box&lt;int&gt;]\n'
                        'make&lowbar;box(\n'
                        '    link:#box[box&lt;int&gt;] const& other,\n'
                        '    int value&hyphen;&hyphen;) &hyphen;&gt; int;\n'
                        'std::strong&lowbar;ordering\n'
                        'operator&lt;&equals;&gt;(int a, int b);\n'
                        '----\n'))
    assert html.count('<a href="#box">box&lt;int&gt;</a>') == 2, html
    assert code_text(html) == ['template<class... Ts>\n'
                               'box<int>\n'
                               'make_box(\n'
                               '    box<int> const& other,\n'
                               '    int value--) -> int;\n'
                               'std::strong_ordering\n'
                               'operator<=>(int a, int b);'], code_text(html)
    # Highlighted as C++: the keywords are, and a name joined by &lowbar; is one word.
    assert '<span class="hljs-keyword">template</span>' in html, html
    assert '<span class="hljs-title">make_box</span>' in html and 'link:' not in html, html


def test_plain_listing_shows_what_it_holds(_: None) -> None:
    # A listing that is code, with no substitution but the special characters, shows a character
    # reference as written: an example that escapes HTML prints &lt;.
    html = body(convert('[source]\n----\nstd::string escaped = "&lt;" + std::string("a_b");\n'
                        '----\n\n'
                        '[source,bash]\n----\nb2 --a link:#x[y] -> z\n----\n'))
    assert code_text(html) == ['std::string escaped = "&lt;" + std::string("a_b");',
                               'b2 --a link:#x[y] -> z'], code_text(html)


def test_inline_code_breaks_between_words(_: None) -> None:
    html = body(convert('Call `get(a, b)` and `--recursive`.\n'))
    assert ('<code class="words"><span class="whole">get(a,</span> <span class="whole">b)</span>'
            '</code>' in html), html
    assert '<code class="whole">--recursive</code>' in html, html


def test_short_inline_code_stays_whole(_: None) -> None:
    # A word of 24 characters or fewer, as a reader reads it, is marked whole, so that a phone's
    # style keeps it on one line; a longer one may break, as it is wider than a phone's line.
    long = 'webcpp-xactor-invariant-36'
    angles = 'a&lt;b&gt;c&lt;d&gt;e&lt;f&gt;g&lt;h&gt;ij'
    html = body(convert(f'Read `#xactor-invariant-13`, `{long}`, `{angles}`,\n'
                        f'`one {long}` and link:#x[`linked-name`].\n'))
    assert '<code class="whole">#xactor-invariant-13</code>' in html, html
    assert f'<code>{long}</code>' in html, html
    assert f'<code class="whole">{angles}</code>' in html, html
    assert (f'<code class="words"><span class="whole">one</span> <span>{long}</span></code>'
            in html), html
    assert '<a href="#x"><code class="whole">linked-name</code></a>' in html, html


def test_wide_table_labels_its_cells(_: None) -> None:
    # A table of three columns or more labels each cell with its column's header, which a phone's
    # style shows above the cell once the header row is hidden; a table of two columns reads
    # stacked without labels.
    html = body(convert('[cols="1,1,2",options="header"]\n|===\n'
                        '| Status | Value | What it "keeps"\n\n'
                        '| `active`\n| 1\n| Its mailbox.\n\n'
                        '| `done`\n| 2\n| Its output.\n|===\n\n'
                        '[cols="1,3",options="header"]\n|===\n| Name | Description\n\n'
                        '| `x`\n| The x.\n|===\n'))
    tables = re.findall(r'<table\b.*?</table>', html, flags=re.S)
    assert len(tables) == 2, html
    labels = re.findall(r'<td [^>]*data-label="([^"]*)"', tables[0])
    assert labels == ['Status', 'Value', 'What it &quot;keeps&quot;'] * 2, labels
    assert 'data-label' not in tables[1], tables[1]


def test_reference_headings_break_after_scopes(_: None) -> None:
    # A name of the reference breaks after a :: and a _, never between two letters; the anchor
    # and the links of the heading are left as they are.
    html = body(convert('[#webcpp-box-make]\n== webcpp::link:#webcpp-box[box]::make&lowbar;box\n'))
    heading = re.search(r'<h2 id="webcpp-box-make">(.*?)</h2>', html, flags=re.S)
    assert heading is not None, html
    assert heading.group(1).endswith(
        'webcpp::<wbr><a href="#webcpp-box">box</a>::<wbr>make_<wbr>box'), heading.group(1)


def test_long_names_break_between_their_parts(_: None) -> None:
    # A name of code too long for a phone's line may break after a ::, a _, a / or a . between
    # letters, before the ( or the < that ends a name, and between the words of a name in camel
    # case, never between two letters of a word; prose, a listing, an attribute and a word short
    # enough to stay whole are left as they are.
    name = 'a_very_long_snake_case_name'
    broken = 'a_<wbr>very_<wbr>long_<wbr>snake_<wbr>case_<wbr>name'
    header = 'webcpp/demo/long&lowbar;header&lowbar;name.hpp'
    page = convert(f'[#webcpp-demo-{name}]\n== webcpp::link:#x[demo]::{name}\n\n'
                   f'Call `{name}(value)`, `webcpp::demo::{name}`,\n'
                   '`std::optional&lt;boost::json::value&gt;`,\n'
                   '`libs/xstate/test/oracle//update-expected`,\n'
                   '`xstate.done.state.coffee.preparation`, `short_name`,\n'
                   '`get_initial_microsteps(machine, options)`,\n'
                   '`resolveHistoryDefaultTransition` (JavaScript),\n'
                   f'link:#webcpp-demo-{name}[`{name}`] and\n'
                   f'`&lt;link:https://example.org/include/{header}[{header}]&gt;`,\n'
                   'as https://webcpporg.github.io/webcpp/report/ shows.\n\n'
                   f'[source,cpp]\n----\nint {name}(int value);\n----\n')
    html = body(page)
    heading = re.search(rf'<h2 id="webcpp-demo-{name}">(.*?)</h2>', html, flags=re.S)
    assert heading is not None, html
    assert heading.group(1).endswith(f'webcpp::<wbr><a href="#x">demo</a>::<wbr>{broken}'), \
        heading.group(1)
    for code in (f'<code>{broken}<wbr>(value)</code>',
                 f'<code>webcpp::<wbr>demo::<wbr>{broken}</code>',
                 '<code>std::<wbr>optional<wbr>&lt;boost::<wbr>json::<wbr>value&gt;</code>',
                 '<code>libs/<wbr>xstate/<wbr>test/<wbr>oracle//<wbr>update-expected</code>',
                 '<code>xstate.<wbr>done.<wbr>state.<wbr>coffee.<wbr>preparation</code>',
                 '<code class="whole">short_name</code>',
                 '<code class="words"><span>get_<wbr>initial_<wbr>microsteps<wbr>(machine,</span> '
                 '<span class="whole">options)</span></code>',
                 '<code>resolve<wbr>History<wbr>Default<wbr>Transition</code> (JavaScript)',
                 f'<a href="#webcpp-demo-{name}"><code>{broken}</code></a>',
                 '<code>&lt;<a href="https://example.org/include/webcpp/demo/long_header_name.hpp">'
                 'webcpp/<wbr>demo/<wbr>long_<wbr>header_<wbr>name.<wbr>hpp</a>&gt;</code>',
                 '<a href="https://webcpporg.github.io/webcpp/report/" class="bare">'
                 'https://<wbr>webcpporg.<wbr>github.<wbr>io/<wbr>webcpp/<wbr>report/</a>'):
        assert code in html, (code, html)
    blocks = re.findall(r'<pre\b[^>]*>.*?</pre>', html, flags=re.S)
    assert blocks and all('<wbr>' not in block for block in blocks), blocks
    assert code_text(html) == [f'int {name}(int value);'], code_text(html)
    assert rendered_check(page).returncode == 0, rendered_check(page).stdout


def test_reference_apostrophes_read_as_the_guide_s(_: None) -> None:
    # MrDocs writes each ' as &apos;, which Asciidoctor's replacements, which make the guide's
    # apostrophe curly, never see. Its reference, as reference.py finishes it, shows the same
    # apostrophes as the guide: curly in a word, and straight in code and where the guide keeps
    # one straight.
    prose = 'The fixture{0}s test, the actors{0} queue and the {0}90s'
    mrdocs = (prose.format('&apos;') + ', with `L&apos;x&apos;` and '
              'link:#x[`x`]&apos;s brief&period;\n\n'
              '[source,cpp,subs="verbatim,replacements,macros,-callouts"]\n----\n'
              'auto it&apos;s = L&apos;x&apos;;\n----\n')
    reference_html = body(convert(reference.finished(mrdocs, 'sample')))
    guide_html = body(convert(prose.format("'") + '.\n'))
    shown = ('The fixture&#8217;s test, the actors\' queue and the \'90s')
    assert f'<p>{shown}.</p>' in guide_html, guide_html
    assert (f'<p>{shown}, with <code class="whole">L\'x\'</code> and <a href="#x"><code '
            'class="whole">x</code></a>\'s brief.</p>') in reference_html, reference_html
    assert code_text(reference_html) == ["auto it's = L'x';"], code_text(reference_html)


CASES: list[Callable[[None], None]] = [
    test_prose_shows_what_mrdocs_read,
    test_synopsis_keeps_its_links,
    test_plain_listing_shows_what_it_holds,
    test_inline_code_breaks_between_words,
    test_short_inline_code_stays_whole,
    test_wide_table_labels_its_cells,
    test_reference_headings_break_after_scopes,
    test_long_names_break_between_their_parts,
    test_reference_apostrophes_read_as_the_guide_s,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'extensions_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    installed()
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        case(None)
        print(f'{case.__name__}: ok')
    print('extensions_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
