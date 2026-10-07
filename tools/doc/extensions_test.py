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
    assert '<p>Returns x-y, <code>a_b</code>, {braces}, an apostrophe\'s and &lt;angle&gt;.</p>' \
        in html, html
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
    assert ('<code class="words"><span>get(a,</span> <span>b)</span></code>' in html), html
    assert '<code>--recursive</code>' in html, html


CASES: list[Callable[[None], None]] = [
    test_prose_shows_what_mrdocs_read,
    test_synopsis_keeps_its_links,
    test_plain_listing_shows_what_it_holds,
    test_inline_code_breaks_between_words,
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
