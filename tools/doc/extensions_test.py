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

Asciidoctor.js comes from tools/doc/node_modules, which install.py installs and links.
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

# The break between two parts of a name that only a phone's style keeps (postprocess.mjs).
PART = '<wbr class="part">'


def installed() -> None:
    """Installs tools/doc's packages as the doc build does, with install.py, which does nothing
    when they are there."""
    subprocess.run([sys.executable, str(HERE / 'install.py'), str(HERE)], check=True)


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


def test_a_flag_keeps_its_leading_hyphen(_: None) -> None:
    # A word too long for a phone's line may break at one of its hyphens, but never right after
    # the hyphens that open a flag, which would end a line with them alone, read as a dash: they
    # stay with the flag's first character, which the style keeps on one line. A hyphen inside a
    # word, and a word short enough to stay whole, are left as they were.
    html = body(convert('Link with `<linkflags>-mexec-model=reactor`, compile with '
                        '`-mllvm -wasm-use-legacy-eh=false`, give `--a-flag-wider-than-a-line`, '
                        'but `-short` and `a-name-with-hyphens-past-24` stay as they are.\n'))
    assert '<code>&lt;linkflags&gt;<span class="lead">-m</span>exec-model=reactor</code>' in html, (
        html)
    assert ('<code class="words"><span class="whole">-mllvm</span> '
            '<span><span class="lead">-w</span>asm-use-legacy-eh=false</span></code>' in html), html
    assert '<code><span class="lead">--a</span>-flag-wider-than-a-line</code>' in html, html
    assert '<code class="whole">-short</code>' in html, html
    assert '<code>a-name-with-hyphens-past-24</code>' in html, html
    lead = [(media, declarations) for media, selectors, declarations in page_style()
            for selector in selectors if selector.endswith('.lead')]
    assert lead == [(None, {'white-space': 'nowrap'})], lead


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


def parts(html: str) -> str:
    """The html with each | written as the break between two parts of a name that only a phone's
    style keeps; a break after a :: is written as it is, <wbr>, which every style keeps."""
    return html.replace('|', PART)


def test_reference_headings_break_after_scopes(_: None) -> None:
    # A name of the reference breaks after a ::, at every width, and after a _, on a phone; never
    # between two letters. The anchor and the links of the heading are left as they are.
    html = body(convert('[#webcpp-box-make]\n== webcpp::link:#webcpp-box[box]::make&lowbar;box\n'))
    heading = re.search(r'<h2 id="webcpp-box-make">(.*?)</h2>', html, flags=re.S)
    assert heading is not None, html
    assert heading.group(1).endswith(
        parts('webcpp::<wbr><a href="#webcpp-box">box</a>::<wbr>make_|box')), heading.group(1)


def test_long_names_break_between_their_parts(_: None) -> None:
    # A name of code too long for a phone's line may break after a ::, a _, a / or a . between
    # letters, before the ( or the < that ends a name, and between the words of a name in camel
    # case, never between two letters of a word; prose, a listing, an attribute and a word short
    # enough to stay whole are left as they are.
    name = 'a_very_long_snake_case_name'
    broken = parts('a_|very_|long_|snake_|case_|name')
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
    for code in (f'<code>{broken}{PART}(value)</code>',
                 f'<code>webcpp::<wbr>demo::<wbr>{broken}</code>',
                 parts('<code>std::<wbr>optional|&lt;boost::<wbr>json::<wbr>value&gt;</code>'),
                 parts('<code>libs/|xstate/|test/|oracle//|update-expected</code>'),
                 parts('<code>xstate.|done.|state.|coffee.|preparation</code>'),
                 '<code class="whole">short_name</code>',
                 parts('<code class="words"><span>get_|initial_|microsteps|(machine,</span> '
                       '<span class="whole">options)</span></code>'),
                 parts('<code>resolve|History|Default|Transition</code> (JavaScript)'),
                 f'<a href="#webcpp-demo-{name}"><code>{broken}</code></a>',
                 parts('<code>&lt;<a href="https://example.org/include/webcpp/demo/'
                       'long_header_name.hpp">webcpp/|demo/|long_|header_|name.|hpp</a>&gt;'
                       '</code>'),
                 parts('<a href="https://webcpporg.github.io/webcpp/report/" class="bare">'
                       'https://|webcpporg.|github.|io/|webcpp/|report/</a>')):
        assert code in html, (code, html)
    blocks = re.findall(r'<pre\b[^>]*>.*?</pre>', html, flags=re.S)
    assert blocks and all('<wbr' not in block for block in blocks), blocks
    assert code_text(html) == [f'int {name}(int value);'], code_text(html)
    assert rendered_check(page).returncode == 0, rendered_check(page).stdout


def test_names_break_only_where_they_part(_: None) -> None:
    # The dot of a number, a run of _, the second < of <<, and a character reference are no
    # place to break: a run of _ breaks after its last, and a reference stays whole.
    html = body(convert('`boost_version_number_is_1.90.0`,\n'
                        '`some_long__double_underscore_name`,\n'
                        '`webcpp::xactor::operator&lt;&lt;(std::ostream&amp;)`,\n'
                        '`some_really_long_identifier_name&#xAB;tail`,\n'
                        '`some_really_long_identifier_name&rArr;tail`.\n'))
    for code in (parts('<code>boost_|version_|number_|is_|1.90.0</code>'),
                 parts('<code>some_|long__|double_|underscore_|name</code>'),
                 parts('<code>webcpp::<wbr>xactor::<wbr>operator|&lt;&lt;(std::<wbr>ostream&amp;)'
                       '</code>'),
                 parts('<code>some_|really_|long_|identifier_|name&#xAB;tail</code>'),
                 parts('<code>some_|really_|long_|identifier_|name&rArr;tail</code>')):
        assert code in html, (code, html)


def test_code_in_a_heading_is_broken_once(_: None) -> None:
    # Inline code of a heading has its breaks from the code's own rule, once: a word short
    # enough to stay whole has none, and a :: of a long one is followed by one break.
    html = body(convert('== The `webcpp::demo::some_really_long_name` call and `short_name`\n'))
    heading = re.search(r'<h2 id="[^"]*">(.*?)</h2>', html, flags=re.S)
    assert heading is not None, html
    assert heading.group(1) == parts(
        'The <code>webcpp::<wbr>demo::<wbr>some_|really_|long_|name</code> call and '
        '<code class="whole">short_name</code>'), heading.group(1)


def test_linked_code_is_whole_or_breaks_between_its_parts(_: None) -> None:
    # Inline code that holds a link, as MrDocs writes the name of a header, is a word as a reader
    # reads it: short enough, it stays whole; with a space, it breaks between its parts.
    html = body(convert('Declared in `&lt;link:https://example.org/x.hpp[webcpp/demo/x.hpp]&gt;`,\n'
                        'and `call link:#x[some_really_long_name_for_this] now`.\n'))
    for code in ('<code class="whole">&lt;<a href="https://example.org/x.hpp">webcpp/demo/x.hpp'
                 '</a>&gt;</code>',
                 parts('<code>call <a href="#x">some_|really_|long_|name_|for_|this</a> now'
                       '</code>')):
        assert code in html, (code, html)


def test_reference_apostrophes_read_as_the_guide_s(_: None) -> None:
    # MrDocs writes each ' as &apos;, which Asciidoctor's replacements, which make the guide's
    # apostrophe curly, never see. Its reference, as reference.py finishes it, shows the same
    # apostrophes as the guide: curly in a word, and straight in code and where the guide keeps
    # one straight.
    prose = 'The fixture{0}s test, the actors{0} queue and the {0}90s'
    mrdocs = (prose.format('&apos;') + ', with `L&apos;x&apos;` and '
              'link:#x[`x`]&apos;s brief&period;\n')
    reference_html = body(convert(reference.finished(mrdocs, 'sample')))
    guide_html = body(convert(prose.format("'") + '.\n'))
    shown = ('The fixture&#8217;s test, the actors\' queue and the \'90s')
    assert f'<p>{shown}.</p>' in guide_html, guide_html
    assert (f'<p>{shown}, with <code class="whole">L\'x\'</code> and <a href="#x"><code '
            'class="whole">x</code></a>\'s brief.</p>') in reference_html, reference_html


def test_reference_apostrophes_stay_straight_in_code_and_targets(_: None) -> None:
    # An apostrophe of MrDocs's that Asciidoctor would read as code, as a passthrough, or as part
    # of a link's target or of a URL stays as MrDocs wrote it; one in a paragraph after a backtick
    # that does not close is prose; and one in the text of a synopsis's link stays straight.
    mrdocs = ('A ``it&apos;s``s span, +it&apos;s+, pass:[it&apos;s], +&apos;x&apos;+,\n'
              'pass:c[&apos;y&apos;], link:pages/it&apos;s.html[a page],\n'
              'link:https://example.org/it&apos;s[the fixture&apos;s page] and\n'
              'https://example.org/don&apos;t[the other&apos;s]&period;\n\n'
              'An unclosed `tick&period;\n\n'
              'The fixture&apos;s test `x`&period;\n\n'
              '[source,cpp,subs="verbatim,replacements,macros,-callouts"]\n----\n'
              'auto link:#x[it&apos;s] = 1;\n----\n')
    html = body(convert(reference.finished(mrdocs, 'sample')))
    for shown in ("A <code class=\"whole\">it's</code>s span, it's, it's, 'x',\n'y',",
                  '<a href="pages/it\'s.html">a page</a>',
                  '<a href="https://example.org/it\'s">the fixture&#8217;s page</a>',
                  '<a href="https://example.org/don\'t">the other&#8217;s</a>.',
                  '<p>The fixture&#8217;s test <code class="whole">x</code>.</p>',
                  '<a href="#x">it\'s</a>'):
        assert shown in html, (shown, html)
    assert code_text(html) == ["auto it's = 1;"], code_text(html)


def test_tables_scroll_in_their_own_box(_: None) -> None:
    # Every table of the page, one inside a cell and one with an id included, is in a box of its
    # own, which scrolls when a word of the table is too long for the page; a note, which
    # Asciidoctor lays out as a table, is not. A table with an id is labelled as any other.
    long = 'xstate::failure<T>(xstate::errc::implementation&lowbar;failed);'
    html = body(convert('[cols="1,1,1",options="header"]\n|===\n| XState | Fixed | Computed\n\n'
                        f'| `a` | `{long}` | `c`\n|===\n\n'
                        '[cols="1,1"]\n|===\n| Outer\na|\n'
                        '[cols="1"]\n!===\n! Inner\n!===\n|===\n\n'
                        '[#named,cols="1,1,1",options="header"]\n|===\n| A | B | C\n\n'
                        '| x | y | z\n|===\n\n'
                        'NOTE: A note.\n'))
    opened = re.findall(r'<table\b[^>]*>', html)
    assert len(opened) == 5, opened
    wrapped = re.findall(r'<div class="table-scroll">\n<table\b[^>]*\bclass="tableblock\b', html)
    assert len(wrapped) == 4 == html.count('<div class="table-scroll">'), html
    assert re.search(r'<div class="table-scroll">\s*<table class="tableblock[^"]*">'
                     rf'(?:(?!<table)[\s\S])*?implementation_{PART}failed'
                     r'(?:(?!<table)[\s\S])*?</table>\s*</div>', html), html
    # Each box closes where its table does, the inner one inside the outer cell, and nothing
    # else closes one: a note's table is followed by its own block's end alone.
    assert '<div class="content"><div class="table-scroll">' in html, html
    assert '</table>\n</div></div></td>' in html, html
    assert html.count('<div') == html.count('</div>'), html
    assert re.search(r'<div class="admonitionblock note">\s*<table>[\s\S]*?</table>\n</div>\n'
                     r'</div>\n<div id="footer">', html), html
    assert re.search(r'<div class="table-scroll">\n<table id="named" class="tableblock', html), \
        html
    assert re.findall(r'<td [^>]*data-label="([^"]*)"', html)[-3:] == ['A', 'B', 'C'], html


def css_rules(text: str) -> list[tuple[str | None, list[str], dict[str, str]]]:
    """The rules of a stylesheet, each as its media query (None outside one), its selectors and
    its declarations."""
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    rules: list[tuple[str | None, list[str], dict[str, str]]] = []

    def read(block: str, media: str | None) -> None:
        position = 0
        while True:
            opening = block.find('{', position)
            if opening < 0:
                return
            prelude = block[position:opening].strip()
            if prelude.startswith('@media'):
                depth, end = 1, opening + 1
                while depth:
                    depth += {'{': 1, '}': -1}.get(block[end], 0)
                    end += 1
                read(block[opening + 1:end - 1], prelude[len('@media'):].strip())
                position = end
                continue
            closing = block.index('}', opening)
            declarations = {}
            for declaration in block[opening + 1:closing].split(';'):
                if ':' in declaration:
                    key, value = declaration.split(':', 1)
                    declarations[key.strip()] = ' '.join(value.split())
            selectors = [re.sub(r'\s*([>+~])\s*', r'\1', ' '.join(selector.split()))
                         for selector in prelude.split(',')]
            rules.append((media, selectors, declarations))
            position = closing + 1

    read(text, None)
    return rules


def page_style() -> list[tuple[str | None, list[str], dict[str, str]]]:
    """The rules of the style every page adds to Asciidoctor's, docinfo.html's."""
    docinfo = (HERE / 'docinfo.html').read_text()
    return css_rules(docinfo[docinfo.index('<style>') + 7:docinfo.index('</style>')])


def test_style_breaks_a_word_only_when_it_must(_: None) -> None:
    # Each rule of Asciidoctor's style that lets text break anywhere, the page's own included, is
    # met by one of the page's that breaks a word only when it alone is wider than its line.
    default = (HERE / 'node_modules/@asciidoctor/core/data/asciidoctor-default.css').read_text()
    anywhere = [selector for media, selectors, declarations in css_rules(default)
                if media is None and 'anywhere' in (declarations.get('word-wrap', '') +
                                                    declarations.get('overflow-wrap', ''))
                for selector in selectors]
    assert anywhere, 'Asciidoctor\'s style no longer breaks anywhere: drop this test'
    breaking = {selector for media, selectors, declarations in page_style()
                if media is None and declarations.get('overflow-wrap') == 'break-word'
                for selector in selectors}
    assert set(anywhere) <= breaking, (anywhere, breaking)


def test_style_keeps_part_breaks_to_a_phone(_: None) -> None:
    # From 600px a break between two parts of a name is no box, in a heading, a URL and inline
    # code alike, and below it every break is live; a break after a :: of a heading is live at
    # every width.
    hidden = [(media, selector) for media, selectors, declarations in page_style()
              if declarations.get('display') == 'none'
              for selector in selectors if 'wbr' in selector]
    assert sorted(hidden) == sorted([
        ('screen and (min-width: 37.5em)', 'wbr.part'),
        ('screen and (min-width: 37.5em)', '#content :not(pre):not([class^=L])>code wbr'),
    ]), hidden


def test_style_scrolls_a_wide_table_in_its_box(_: None) -> None:
    # The box of a table scrolls sideways, holds the table's margin, and shows a shadow at an
    # edge with more of the table beyond it: a cover moves with the table and hides the shadow
    # where there is nothing more, so a table that fits looks as it did.
    rules = {selector: declarations for media, selectors, declarations in page_style()
             if media is None for selector in selectors}
    box = rules['.table-scroll']
    assert box.get('overflow-x') == 'auto' and box.get('margin-bottom') == '1.25em', box
    assert box.get('background-attachment') == 'local, local, scroll, scroll', box
    table = rules['.table-scroll>table.tableblock']
    assert table == {'margin-bottom': '0', 'background': 'none'}, table


def ems(value: str) -> float:
    """A length in em, as a float: 14em is 14.0."""
    found = re.fullmatch(r'(\d+(?:\.\d+)?)em', value)
    assert found, value
    return float(found.group(1))


def test_style_gives_the_content_a_right_gutter_from_the_toc(_: None) -> None:
    # Wherever Asciidoctor sets the table of contents at the left of the content, the page gives
    # the content a gutter at its right, an em or more, taken from the table's width: the
    # content keeps the width Asciidoctor gives it, so every line breaks where it did, and the
    # table and its padding still meet.
    default = (HERE / 'node_modules/@asciidoctor/core/data/asciidoctor-default.css').read_text()
    beside = {}
    for media, selectors, declarations in css_rules(default):
        if media and 'body.toc2' in selectors:
            pixels = re.fullmatch(r'screen and \(min-width:(\d+)px\)', media)
            assert pixels, media
            beside[f'screen and (min-width: {int(pixels.group(1)) / 16:g}em)'] = (
                ems(declarations['padding-left']))
    assert sorted(beside.values()) == [15.0, 20.0], beside
    page = {(media, selector): declarations for media, selectors, declarations in page_style()
            for selector in selectors}
    for media, width in beside.items():
        body = page.get((media, 'body.toc2.toc-left'), {})
        toc = page.get((media, 'body.toc2.toc-left #toc.toc2'), {})
        assert body and toc, (media, body, toc)
        gutter = ems(body['padding-right'])
        assert gutter >= 1, (media, body)
        assert ems(body['padding-left']) + gutter == width, (media, body, width)
        assert ems(toc['width']) == ems(body['padding-left']), (media, toc, body)


CASES: list[Callable[[None], None]] = [
    test_prose_shows_what_mrdocs_read,
    test_synopsis_keeps_its_links,
    test_plain_listing_shows_what_it_holds,
    test_inline_code_breaks_between_words,
    test_short_inline_code_stays_whole,
    test_a_flag_keeps_its_leading_hyphen,
    test_wide_table_labels_its_cells,
    test_reference_headings_break_after_scopes,
    test_long_names_break_between_their_parts,
    test_names_break_only_where_they_part,
    test_code_in_a_heading_is_broken_once,
    test_linked_code_is_whole_or_breaks_between_its_parts,
    test_reference_apostrophes_read_as_the_guide_s,
    test_reference_apostrophes_stay_straight_in_code_and_targets,
    test_tables_scroll_in_their_own_box,
    test_style_breaks_a_word_only_when_it_must,
    test_style_keeps_part_breaks_to_a_phone,
    test_style_scrolls_a_wide_table_in_its_box,
    test_style_gives_the_content_a_right_gutter_from_the_toc,
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
