#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks doc-check.py: each rule fires on its own fault, and a whole page passes.

Each check runs on a library written to a scratch directory: its page under doc/, its examples
under example/, at any depth, its twins under twins/, a header, a README and a git repository
holding them, as libs/<library> of the superproject is.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECK = HERE / 'doc-check.py'

# doc-check.py reads every file of the repository, this one included, for a reference to the
# page, so the stale references below are put together where they are used rather than written
# whole.
DOC = 'doc:'
INDEX = 'index.html'

# U+2010, the hyphen MrDocs writes as &hyphen;, written as an escape.
HYPHEN = '\u2010'

PAGE = """[#machines]
== Machines

[source]
----
include::{examples}/toggle.cpp[tag=machine]
----

[listing]
----
include::{examples}/toggle.expected[]
----

[#reference]
== Reference

include::{reference}[leveloffset=+1]

[appendix]
[#differences]
== Differences

[source,javascript]
----
include::{twins}/toggle.mjs[tag=machine]
----

[listing]
----
include::{twins}/refused.expected[]
----

[listing]
----
include::{examples}/refused.expected[]
----
"""

# The line a block appended to PAGE after a blank line starts on.
NEXT = PAGE.count('\n') + 2

# What the page may show besides its includes: JSON, shell commands, a listing of its own, and
# the safe ways to write ++ outside code.
LANGUAGES = """
[source,json]
----
{"on": {"go": "next"}}
----

[source,bash]
----
b2 test && echo "i++"
----

[listing]
----
local wasi-sdk = /path/to/wasi-sdk ;
----

Written in {cpp}, with `i++`, ``j++``, `a
b++` across lines, pass:[e++] and +++f++ g+++.

// A comment, C++ and C++.
"""

README = """# Fixture

<!-- include::example/toggle.cpp[tag=machine] -->
```cpp
int main() {}
```

It prints:

<!-- include::example/toggle.expected[] -->
```
output
```

```bash
b2 test
```
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def run(*arguments: str, path: str | None = None) -> subprocess.CompletedProcess:
    """Runs doc-check.py with arguments; path, when given, is the only PATH it runs with."""
    return subprocess.run([sys.executable, str(CHECK), *arguments], capture_output=True, text=True,
                          check=False, env=None if path is None else {'PATH': path})


def check(root: Path, *extra: str, sections: list[Path] | None = None,
          page: Path | None = None) -> subprocess.CompletedProcess:
    """Runs doc-check.py on the library at root, as webcpp.doc runs it, plus extra."""
    # The files git lists are those it tracks and those it would track; adding them all checks
    # that both kinds are read.
    subprocess.run(['git', 'add', '-A'], cwd=root, check=True, capture_output=True)
    page = page or root / 'doc/page.adoc'
    if sections is None:
        sections = [root / 'doc/page.adoc']
    return run('--examples', str(root / 'example'), '--twins', str(root / 'twins'),
               '--repository', str(root), '--readme', str(root / 'README.md'), '--page',
               str(page), *extra, *(str(section) for section in sections))


def expect(result: subprocess.CompletedProcess, status: int, text: str) -> None:
    assert result.returncode == status, (status, result.returncode, result.stdout, result.stderr)
    assert text in result.stdout, (text, result.stdout)


def check_page(root: Path) -> None:
    """The rules that read the page's own text."""
    expect(check(root, '--complete'), 0, '')

    (root / 'twins/refused.mjs').unlink()
    expect(check(root), 1, 'includes the output of no twin: {twins}/refused.expected')
    write(root / 'twins/refused.mjs', '')

    write(root / 'doc/page.adoc', PAGE + '\n[source,javascript]\n----\nconst x = 1;\n----\n')
    expect(check(root), 0, '')
    expect(check(root, '--complete'), 1, 'JavaScript that is not an include of a twin')

    write(root / 'doc/page.adoc', PAGE + '\n[source]\n----\nint main() {}\n----\n')
    expect(check(root, '--complete'), 1, 'C++ that is not included from an example')
    # A section named reference writes no synopsis of its own: the reference is MrDocs's,
    # included at {reference}.
    write(root / 'doc/reference.adoc', '[source]\n----\nstruct event;\n----\n')
    reference = run('--examples', str(root / 'example'), '--page', str(root / 'doc/reference.adoc'),
                    '--complete', str(root / 'doc/reference.adoc'))
    expect(reference, 1, 'reference.adoc:1: C++ that is not included from an example')
    (root / 'doc/reference.adoc').unlink()

    # A block's language is the one Asciidoctor gives it, and any but the page's four is a fault,
    # so that neither rule can be passed by naming the language another way.
    for spelling in ('[source,js]', '[source,c++]', '[source,cxx]', '[source, typescript]'):
        write(root / 'doc/page.adoc', PAGE + f'\n{spelling}\n----\nconst x = 1;\n----\n')
        language = spelling[1:-1].split(',')[1].strip()
        expect(check(root, '--complete'), 1, f'page.adoc:{NEXT}: a block in {language}, a language')
    for spelling in ('[,javascript]', '[source,language=javascript]',
                     '[source%linenums,javascript]'):
        write(root / 'doc/page.adoc', PAGE + f'\n{spelling}\n----\nconst x = 1;\n----\n')
        expect(check(root, '--complete'), 1,
               f'page.adoc:{NEXT}: JavaScript that is not an include of a twin')
    # A block with no style is C++: the page's :source-language: makes it one.
    write(root / 'doc/page.adoc', PAGE + '\n----\nint main() {}\n----\n')
    expect(check(root, '--complete'), 1,
           f'page.adoc:{NEXT}: C++ that is not included from an example')
    write(root / 'doc/page.adoc', PAGE + '\n.A title\n[#an-anchor]\n----\nint main() {}\n----\n')
    expect(check(root, '--complete'), 1,
           f'page.adoc:{NEXT}: C++ that is not included from an example')
    # So an output or a twin is not one either: Asciidoctor would colour it as C++.
    for target in ('{examples}/toggle.expected[]', '{twins}/toggle.mjs[tag=machine]'):
        for style in ('', '[source]\n'):
            write(root / 'doc/page.adoc', PAGE + f'\n{style}----\ninclude::{target}\n----\n')
            expect(check(root, '--complete'), 1,
                   f'page.adoc:{NEXT}: C++ that is not included from an example')
    write(root / 'doc/page.adoc',
          PAGE + '\n----\ninclude::{examples}/toggle.cpp[tag=machine]\n----\n')
    expect(check(root, '--complete'), 0, '')
    # A source paragraph, a literal block styled as source, and a Markdown fence.
    write(root / 'doc/page.adoc', PAGE + '\n[source,js]\nconst x = 1;\n')
    expect(check(root, '--complete'), 1, f'page.adoc:{NEXT}: a block in js, a language')
    write(root / 'doc/page.adoc', PAGE + '\n[source]\n....\nint main() {}\n....\n')
    expect(check(root, '--complete'), 1,
           f'page.adoc:{NEXT}: C++ that is not included from an example')
    write(root / 'doc/page.adoc', PAGE + '\n```cpp\nint main() {}\n```\n')
    expect(check(root, '--complete'), 1, f'page.adoc:{NEXT}: a Markdown fence')
    # And another default language for the blocks that name none.
    write(root / 'doc/page.adoc', ':source-language: javascript\n\n' + PAGE)
    expect(check(root, '--complete'), 1, 'page.adoc:1: the blocks that name no language are C++')
    write(root / 'doc/page.adoc', ':source-language: cpp\n\n' + PAGE + LANGUAGES)
    expect(check(root, '--complete'), 0, '')

    # Two literal C++ in one paragraph make a passthrough of what lies between them, which drops
    # both ++ and shows nothing on the rendered page; a table cell is prose too, and so is a
    # constrained passthrough, which ++ breaks the same way.
    prose = PAGE + LANGUAGES + '\n'
    line = prose.count('\n') + 1
    for text, offset in (('Written in C++ and built as C++ everywhere.\n', 0),
                         ('[cols="1"]\n|===\n| A C++ cell\n|===\n', 2),
                         ('The first line,\nthen C++ on the second.\n', 1),
                         ('Uses +c++ d+ here.\n', 0)):
        write(root / 'doc/page.adoc', prose + text)
        expect(check(root), 1,
               f'page.adoc:{line + offset}: a literal ++ in prose, which Asciidoctor reads')
    write(root / 'doc/page.adoc', PAGE)


def check_reference(root: Path) -> None:
    """The page shows the reference MrDocs writes, as {reference}, one level down."""
    without = PAGE.replace('include::{reference}[leveloffset=+1]\n', 'MrDocs is not shown.\n')
    write(root / 'doc/page.adoc', without)
    expect(check(root), 0, '')
    expect(check(root, '--complete'), 1,
           'page.adoc: the page does not show the reference: include::{reference}'
           '[leveloffset=+1]')
    level = PAGE.replace('{reference}[leveloffset=+1]', '{reference}[]')
    write(root / 'doc/page.adoc', level)
    line = PAGE.splitlines().index('include::{reference}[leveloffset=+1]') + 1
    expect(check(root, '--complete'), 1,
           f'page.adoc:{line}: includes the reference without leveloffset=+1')
    write(root / 'doc/page.adoc', PAGE)


def check_examples(root: Path) -> None:
    """Every example is shown, wherever it is under the examples' directory."""
    write(root / 'example/actors/unshown.cpp', '')
    write(root / 'example/actors/unshown.expected', 'output\n')
    expect(check(root, '--complete'), 1, 'unshown.cpp: the page shows neither its code nor')
    # Shown at its depth, by its output; and the output of a program that is gone is named.
    write(root / 'doc/page.adoc',
          PAGE + '\n[listing]\n----\ninclude::{examples}/actors/unshown.expected[]\n----\n')
    expect(check(root, '--complete'), 0, '')
    (root / 'example/actors/unshown.cpp').unlink()
    expect(check(root), 1,
           'includes the output of no example: {examples}/actors/unshown.expected')
    write(root / 'doc/page.adoc', PAGE)
    (root / 'example/actors/unshown.expected').unlink()
    # A source with no expected output is no example: a helper the examples link, which no page
    # shows.
    write(root / 'example/helper.cpp', '')
    expect(check(root, '--complete'), 0, '')
    (root / 'example/helper.cpp').unlink()

    write(root / 'twins/toggle.expected', 'original output\n')
    expect(check(root, '--complete'), 1,
           'toggle.expected: the page does not show this difference from the original')
    (root / 'twins/toggle.expected').unlink()

    # A library without twins or without examples passes without either option.
    no_twins = PAGE.split('[appendix]')[0]
    write(root / 'doc/page.adoc', no_twins)
    (root / 'example/refused.cpp').unlink()
    result = run('--examples', str(root / 'example'), '--page', str(root / 'doc/page.adoc'),
                 '--complete', str(root / 'doc/page.adoc'))
    expect(result, 0, '')
    write(root / 'example/refused.cpp', '// tag::machine[]\n\nint main() {}\n\n// end::machine[]\n')
    write(root / 'doc/page.adoc', PAGE)

    expect(check(root, '--complete'), 0, '')


def check_graph(root: Path) -> None:
    """The page answers for the sections it reaches, and for its includes."""
    # Neutral while the graph and include tests below use a page of their own, one that defines
    # neither #machines nor #differences.
    write(root / 'include/header.hpp', '')

    # An orphan: the page reaches `chapter.adoc` through `entry.adoc`, but nothing reaches
    # `orphan.adoc`, so it is a fault naming the file; its own anchor must not count, either,
    # once it is gone from the walk.
    write(root / 'doc/entry.adoc', '[#entry]\n== Entry\n\ninclude::chapter.adoc[]\n')
    write(root / 'doc/chapter.adoc', '[#chapter]\n== Chapter\n')
    write(root / 'doc/orphan.adoc', '[#orphan]\n== Orphan\n')
    write(root / 'include/orphaned.hpp', f'// Why ({DOC} #orphan).\n')
    graph = [root / 'doc/entry.adoc', root / 'doc/chapter.adoc', root / 'doc/orphan.adoc']
    page = root / 'doc/entry.adoc'
    expect(check(root, sections=graph, page=page), 1, 'orphan.adoc: not reached from the page')
    expect(check(root, sections=graph, page=page), 1, 'names no anchor of the page: #orphan')
    (root / 'include/orphaned.hpp').unlink()
    (root / 'doc/orphan.adoc').unlink()
    expect(check(root, sections=[root / 'doc/entry.adoc', root / 'doc/chapter.adoc'], page=page),
           0, '')
    (root / 'doc/entry.adoc').unlink()
    (root / 'doc/chapter.adoc').unlink()

    # An include outside doc/, {examples} and {twins}: it must both resolve and stay inside one
    # of the three.
    write(root / 'outside/leaked.adoc', '== Leaked\n')
    write(root / 'doc/leak.adoc', '[#leak]\n== Leak\n\ninclude::../outside/leaked.adoc[]\n')
    expect(check(root, sections=[root / 'doc/leak.adoc'], page=root / 'doc/leak.adoc'), 1,
           'leak.adoc:4: includes a file outside doc, examples or twins: ../outside/leaked.adoc')
    write(root / 'doc/leak.adoc', '[#leak]\n== Leak\n\ninclude::missing.adoc[]\n')
    expect(check(root, sections=[root / 'doc/leak.adoc'], page=root / 'doc/leak.adoc'), 1,
           'leak.adoc:4: includes a file that is not there: missing.adoc')
    (root / 'doc/leak.adoc').unlink()
    (root / 'outside/leaked.adoc').unlink()
    write(root / 'include/header.hpp', f'// Why ({DOC} #machines).\n')


def check_references(root: Path) -> None:
    """A file of the library that sends its reader to the page names an anchor the page has."""
    write(root / 'include/header.hpp', f'// Why ({DOC} #nowhere).\n')
    expect(check(root), 1, 'names no anchor of the page: #nowhere')
    # A reference may name several anchors, a range or a list: each one after `doc:` is checked,
    # not only the first.
    write(root / 'include/header.hpp', f'// Why ({DOC} #machines to #nowhere4).\n')
    expect(check(root), 1, 'header.hpp:1: names no anchor of the page: #nowhere4')
    write(root / 'include/header.hpp',
          f'// Why ({DOC} #machines, #differences and #nowhere5).\n')
    expect(check(root), 1, 'header.hpp:1: names no anchor of the page: #nowhere5')
    write(root / 'include/header.hpp', f'// Why ({DOC} #machines to #differences).\n')
    expect(check(root), 0, '')
    # A list that goes on to the next line would leave its rest unchecked.
    write(root / 'include/header.hpp', f'// Why ({DOC} #machines and\n// #nowhere6).\n')
    expect(check(root), 1, 'header.hpp:1: a doc: reference goes on to the next line')
    write(root / 'include/header.hpp', f'// Why ({DOC} #machines).\n')

    # A stale `doc: #<anchor>` in an extensionless file, like a Jamfile: every text file is read.
    write(root / 'include/Jamfile', f'# See ({DOC} #nowhere3).\n')
    expect(check(root), 1, 'Jamfile:1: names no anchor of the page: #nowhere3')
    (root / 'include/Jamfile').unlink()

    # Every file of the repository is read, wherever it is: the build.jam, a test, the README.
    for name, comment in (('build.jam', '# '), ('test/check.sh', '# '), ('README.md', '')):
        before = (root / name).read_text() if (root / name).is_file() else ''
        write(root / name, before + f'{comment}See ({DOC} #nowhere7).\n')
        expect(check(root), 1,
               f'{name}:{before.count(chr(10)) + 1}: names no anchor of the page: #nowhere7')
        write(root / name, before)
    # And the README's links to the page, `doc/html/index.html#<anchor>`.
    write(root / 'README.md', README + f'See doc/html/{INDEX}#nowhere8.\n')
    expect(check(root), 1,
           f'README.md:{README.count(chr(10)) + 1}: names no anchor of the page: #nowhere8')
    write(root / 'README.md', README + f'See doc/html/{INDEX}#machines.\n')
    expect(check(root), 0, '')
    write(root / 'README.md', README)
    # A file git ignores is none of the repository's; one it would track, not yet added, is.
    write(root / '.gitignore', 'scratch/\n')
    write(root / 'scratch/notes.txt', f'({DOC} #nowhere9)\n')
    expect(check(root), 0, '')
    write(root / 'include/new.hpp', f'// Why ({DOC} #nowhere10).\n')
    untracked = run('--examples', str(root / 'example'), '--twins', str(root / 'twins'),
                    '--repository', str(root), '--page', str(root / 'doc/page.adoc'),
                    str(root / 'doc/page.adoc'))
    expect(untracked, 1, 'new.hpp:1: names no anchor of the page: #nowhere10')
    (root / 'include/new.hpp').unlink()
    with tempfile.TemporaryDirectory() as elsewhere:
        result = run('--examples', str(root / 'example'), '--twins', str(root / 'twins'),
                     '--repository', elsewhere, '--page', str(root / 'doc/page.adoc'),
                     str(root / 'doc/page.adoc'))
        expect(result, 1, 'is not a git checkout')


def check_see_titles(root: Path) -> None:
    """A Doc Comment's `@see "<title>"` names a section of the page by its title."""
    header = root / 'include/see.hpp'
    # The title of a section, at any level, and the one-sentence form the Doc Comments use; the
    # backslash form; a @see of a symbol, which names no title.
    write(header, '/** Brief.\n\n    @see "Machines", in the guide.\n    \\see "Differences"\n'
          '    @see toggle\n*/\n')
    expect(check(root), 0, '')
    write(header, '/** Brief.\n\n    @see "Machines", in the guide.\n'
          '    @see "Nowhere", in the guide.\n*/\n')
    expect(check(root), 1, 'see.hpp:4: @see names no section of the page: "Nowhere"')
    write(header, '/// Brief.\n///\n/// \\see "Elsewhere".\n')
    expect(check(root), 1, 'see.hpp:3: @see names no section of the page: "Elsewhere"')
    # A title wrapped onto the next line would be checked by none of its words.
    for command in ('@see', '\\see'):
        write(header, f'/** Brief.\n\n    {command} "A deeper\n    part", in the guide.\n*/\n')
        expect(check(root), 1, 'see.hpp:3: a @see title goes on to the next line; keep the '
               'title on one line')
    # Only a section's title counts: not a line of a listing, of a comment or of a comment
    # block, a block's title or an anchor.
    write(root / 'doc/page.adoc', PAGE + '\n----\n== Listed\n----\n\n// == Commented\n\n'
          '////\n== Blocked\n////\n\n.Titled\n[listing]\n----\nx\n----\n')
    for title in ('Listed', 'Commented', 'Blocked', 'Titled', 'machines'):
        write(header, f'/** Brief.\n\n    @see "{title}", in the guide.\n*/\n')
        expect(check(root), 1, f'see.hpp:3: @see names no section of the page: "{title}"')
    # A section the page does not reach is none of its sections.
    write(root / 'doc/page.adoc', PAGE)
    write(root / 'doc/apart.adoc', '[#apart]\n== Apart\n')
    write(header, '/** Brief.\n\n    @see "Apart", in the guide.\n*/\n')
    expect(check(root, sections=[root / 'doc/page.adoc', root / 'doc/apart.adoc']), 1,
           'see.hpp:3: @see names no section of the page: "Apart"')
    (root / 'doc/apart.adoc').unlink()
    # A section of an included file counts, at any depth of the include graph.
    write(root / 'doc/page.adoc', PAGE + '\ninclude::part.adoc[leveloffset=+1]\n')
    write(root / 'doc/part.adoc', '[#part]\n== Part\n\n[#deeper]\n=== A deeper part\n')
    write(header, '/** Brief.\n\n    @see "A deeper part", in the guide.\n*/\n')
    expect(check(root, sections=[root / 'doc/page.adoc', root / 'doc/part.adoc']), 0, '')
    (root / 'doc/part.adoc').unlink()
    write(root / 'doc/page.adoc', PAGE)
    header.unlink()
    expect(check(root, '--complete'), 0, '')


def check_readme(root: Path) -> None:
    """The README's copies: its C++ is an example's region, and its output the example's, each as
    the file holds it now."""
    write(root / 'README.md', README.replace('int main() {}', 'int main() { return 0; }'))
    expect(check(root), 1, 'README.md:4: differs from example/toggle.cpp[tag=machine]')
    write(root / 'README.md', README.replace('\noutput\n', '\nother\n'))
    expect(check(root), 1, 'README.md:11: differs from example/toggle.expected[]')
    write(root / 'README.md',
          README.replace('<!-- include::example/toggle.cpp[tag=machine] -->\n', ''))
    expect(check(root), 1, 'README.md:3: a C++ block that copies no example')
    write(root / 'README.md', README.replace('toggle.cpp[tag=machine]', 'gone.cpp[tag=machine]'))
    expect(check(root), 1, 'README.md:3: copies a file that is not there: example/gone.cpp')
    write(root / 'README.md', README.replace('-->\n```cpp', '-->\n\n```cpp'))
    expect(check(root), 1, 'README.md:3: names a copy, but no fenced block follows it')
    write(root / 'README.md', README)
    expect(check(root, '--complete'), 0, '')


def check_rendered(root: Path) -> None:
    """The rendered page: what Asciidoctor and MrDocs leave in it without a word.

    A cross-reference Asciidoctor left as text, which two literal C++ in one paragraph swallow
    into a passthrough, and a literal ++ outside code, which is that passthrough's mark. Inline
    code is read too: a passthrough can open in one span and close in another, which then run
    together around a backtick with whatever lay between them, a cross-reference included; and a
    span that does not close leaves its backtick in the text. MrDocs's escapes, &hyphen; and its
    kin, and the U+2010 the first stands for, are what postprocess.mjs decodes; a link of a
    synopsis left as text is a listing the highlighter broke; and a link to #index or #webcpp is
    one to a section reference.py drops. The samples are what Asciidoctor.js
    and tools/doc's extensions write."""
    rendered = root / 'html/index.html'
    page = ('<html><head><title>T</title><style>a::before { content: "++"; }</style></head>'
            '<body><h1>The C&#43;&#43; port</h1><p>See <a href="#x">X</a>.</p>'
            '<pre class="highlight"><code class="hljs">std::cout &lt;&lt; i++; `a`</code></pre>'
            '<pre class="highlight"><code class="hljs"><a href="#box">box&lt;int&gt;</a>'
            '\nmake_box(int value);</code></pre>'
            '<p>Writes <code>++i</code> and <code class="words"><span>a</span> <span>b</span>'
            '</code>, x-y and a&lt;b.</p>'
            # What MrDocs writes of a stream's operators, and of C++ in a comment.
            '<p><code>operator&lt;&lt;</code> and <code>operator&gt;&gt;</code> in C&#43;&#43;'
            ', and std::cout &lt;&lt; x &gt;&gt; y.</p>'
            '%s</body></html>')
    for sample, fault in (
            ('', None),
            ('<p>C text with &lt;&lt;overview&gt;&gt; and C again</p>',
             'a cross-reference left as text'),
            ('<p>Written in C++.</p>', 'a literal ++ outside code'),
            ('<p>Uses <code class="words"><span>a`</span> <span>and</span> <span>see</span> '
             '<span>&lt;&lt;x&gt;&gt;</span> <span>and</span> <span>`b</span></code> there.</p>',
             'a cross-reference left as text'),
            ('<p>Counts with <code class="words"><span>step`</span> <span>and</span> '
             '<span>`count</span></code> here.</p>',
             'a backtick inside inline code, two spans run together'),
            ('<p>And `c d+` here.</p>',
             'a backtick outside code, a span of inline code that did not close'),
            ('<p>Returns x&hyphen;y.</p>', 'an escape of MrDocs left undecoded: &hyphen;'),
            ('<p><code>a&lowbar;b</code></p>', 'an escape of MrDocs left undecoded: &lowbar;'),
            (f'<p>Returns x{HYPHEN}y.</p>', 'a U+2010 hyphen where MrDocs read -'),
            ('<pre class="highlight"><code class="hljs">link:<span class="hljs-meta">#box[box'
             '&lt;int&gt;]</span>\nmake_box(int value);</code></pre>',
             'a link of a listing left as text: link:#box['),
            # The sections of the global namespace and of webcpp, which reference.py drops.
            ('<h3><a href="#webcpp">webcpp</a>::demo</h3>',
             'a link to a section the reference does not keep: #webcpp'),
            ('<p><a href="#index">Global namespace</a></p>',
             'a link to a section the reference does not keep: #index')):
        write(rendered, page % sample)
        result = run('--rendered', str(rendered))
        if fault is None:
            expect(result, 0, '')
        else:
            expect(result, 1, f'index.html: {fault}')


def linked(root: Path, page: Path, site: bool = False,
           pages: tuple[str, ...] = ('other',)) -> subprocess.CompletedProcess:
    """Runs the check of the rendered page as webcpp.doc runs it for the library at root, named
    fixture, whose build made the pages of the libraries `pages` first, each where b2 builds it,
    under bin/libs/<library>/doc/: in the tree's layout, or the site's."""
    links = ('..', 'index.html') if site else ('../../..', 'doc/html/index.html')
    built = [word for library in pages
             for word in ('--linked-page',
                          str(root / f'scratch/bin/libs/{library}/doc/index.html'))]
    return run('--rendered', str(page), '--repository', str(root), '--library', 'fixture',
               '--webcpp-libs', links[0], '--webcpp-page', links[1], *built)


def check_links(root: Path) -> None:
    """A link into another library's page: the page's own check leaves it to the check of the
    rendered page, which reads the linked page as the build made it, for its anchor."""
    # Outside what git lists (check_references ignores scratch/), so that no file of the library
    # holds them.
    write(root / 'scratch/bin/libs/other/doc/index.html',
          '<html><body><h2 id="present">Present</h2><h3 id="webcpp-other-f-02">f</h3>'
          '<a name="named">n</a></body></html>')
    write(root / 'scratch/bin/libs/third/doc/index.html',
          '<html><body><h2 id="only-third">Only here</h2></body></html>')
    rendered = root / 'scratch/index.html'
    write(rendered, '<html><body><p>Clean.</p></body></html>')
    header = root / 'include/header.hpp'

    # The page's own check: an anchor of another library's is none of the page's, in a doc:
    # reference or in a link to that library's page.
    write(header, f'// Why ({DOC} other#missing).\n')
    expect(check(root, '--complete'), 0, '')
    stale = README + (f'See ../other/doc/html/{INDEX}#missing and libs/other/{INDEX}#present.\n')
    write(root / 'README.md', stale)
    expect(check(root, '--complete'), 0, '')
    # The library's own name is its own page.
    write(header, f'// Why ({DOC} fixture#nowhere11).\n')
    expect(check(root, '--library', 'fixture'), 1,
           'header.hpp:1: names no anchor of the page: #nowhere11')
    write(header, f'// Why ({DOC} fixture#machines).\n')
    expect(check(root, '--library', 'fixture'), 0, '')
    # A page links another library's with the two attributes webcpp.doc sets, never with a path
    # of one layout.
    write(root / 'doc/page.adoc', PAGE + '\nSee link:{webcpp-libs}/other/doc/html/index.html'
                                         '#present[other].\n')
    expect(check(root), 1, f'page.adoc:{NEXT}: a link into another library\'s page is written '
                           'link:{webcpp-libs}/<library>/{webcpp-page}#<anchor>[...]')
    write(root / 'doc/page.adoc', PAGE + '\nSee link:{webcpp-libs}/other/{webcpp-page}#present'
                                         '[other].\n')
    expect(check(root, '--complete'), 0, '')
    # A text that shows the form, with placeholders, writes no link.
    write(root / 'README.md',
          stale + 'Link as link:{webcpp-libs}/<library>/doc/html/index.html#<anchor>[...].\n')
    expect(check(root, '--complete'), 0, '')
    write(root / 'README.md', stale)

    # The libraries whose pages the build makes first: those the library's files link.
    write(header, f'// Why ({DOC} other#present, #named and ({DOC} third#a)).\n')
    listing = run('--linked-libraries', '--repository', str(root), '--library', 'fixture')
    assert (listing.returncode, listing.stdout) == (0, 'other\nthird\n'), listing
    write(header, f'// Why ({DOC} fixture#machines).\n')

    # The rendered check reads the linked page: each anchor a file of the library or a link of
    # the page names is there, and is not an overload's number, which MrDocs may renumber.
    expect(linked(root, rendered), 1, f'README.md:{stale.count(chr(10))}: names no anchor of the '
                                      'page of other: other#missing')
    write(root / 'README.md', README)
    write(header, f'// Why ({DOC} other#present, #named and #missing).\n')
    expect(linked(root, rendered), 1,
           'header.hpp:1: names no anchor of the page of other: other#missing')
    write(header, f'// Why ({DOC} other#present and #named).\n')
    expect(linked(root, rendered), 0, '')
    write(header, f'// Why ({DOC} other#webcpp-other-f-02).\n')
    expect(linked(root, rendered), 1, 'header.hpp:1: other#webcpp-other-f-02 ends in the number '
                                      'MrDocs gives an overload')
    # A page that the build did not make first, which it cannot read.
    write(header, f'// Why ({DOC} third#present).\n')
    expect(linked(root, rendered), 1, 'header.hpp:1: names the page of third, which the build '
                                      'did not make first')
    write(header, f'// Why ({DOC} other#present).\n')
    # A link of the rendered page, in the tree's layout and in the site's.
    for site, href in ((False, '../../../other/doc/html/index.html'),
                       (True, '../other/index.html')):
        for anchor, fault in (('#present', None), ('', None), ('#named', None),
                              ('#missing', 'names no anchor of the page of other: other#missing'),
                              ('#webcpp-other-f-02',
                               'other#webcpp-other-f-02 ends in the number MrDocs gives an '
                               'overload')):
            write(rendered, f'<html><body><p><a href="{href}{anchor}">other</a></p></body></html>')
            if fault is None:
                expect(linked(root, rendered, site=site), 0, '')
            else:
                expect(linked(root, rendered, site=site), 1, f'{href}{anchor}: {fault}')
    write(rendered, '<html><body><p><a href="../../../third/doc/html/index.html#a">t</a></p>'
                    '</body></html>')
    expect(linked(root, rendered), 1, '../../../third/doc/html/index.html#a: names the page of '
                                      'third, which the build did not make first')
    # Each page the build made is its library's, named by its path, whatever their order.
    write(header, f'// Why ({DOC} other#present and ({DOC} third#only-third)).\n')
    for pages in (('other', 'third'), ('third', 'other')):
        expect(linked(root, rendered, pages=pages), 1, '../../../third/doc/html/index.html#a: '
               'names no anchor of the page of third: third#a')
    write(rendered, '<html><body><p>Clean.</p></body></html>')
    for pages in (('other', 'third'), ('third', 'other')):
        expect(linked(root, rendered, pages=pages), 0, '')
    nameless = run('--rendered', str(rendered), '--linked-page', str(root / 'scratch/page.html'))
    expect(nameless, 2, '')
    assert 'names no libs/<library>/doc/' in nameless.stderr, nameless.stderr
    write(header, f'// Why ({DOC} other#present).\n')
    write(header, f'// Why ({DOC} #machines).\n')
    write(root / 'doc/page.adoc', PAGE)
    expect(check(root, '--complete'), 0, '')


def check_without_git(root: Path) -> None:
    """Outside a git checkout, or without git, the libraries a page links are none, which the build
    reads as a Jamfile loads; the page's own check names what it cannot read."""
    with tempfile.TemporaryDirectory() as elsewhere:
        for path in (None, ''):
            listing = run('--linked-libraries', '--repository', elsewhere, '--library', 'fixture',
                          path=path)
            assert (listing.returncode, listing.stdout, listing.stderr) == (0, '', ''), listing
    listing = run('--linked-libraries', '--repository', str(root), '--library', 'fixture',
                  path='')
    assert (listing.returncode, listing.stdout, listing.stderr) == (0, '', ''), listing
    result = run('--examples', str(root / 'example'), '--repository', str(root), '--page',
                 str(root / 'doc/page.adoc'), str(root / 'doc/page.adoc'), path='')
    expect(result, 1, f'{root}: is not a git checkout')


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='doc check ') as scratch:
        root = Path(scratch)
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        for name in ('toggle', 'refused'):
            write(root / f'example/{name}.cpp',
                  '// tag::machine[]\n\nint main() {}\n\n// end::machine[]\n')
            write(root / f'example/{name}.expected', 'output\n')
            write(root / f'twins/{name}.mjs', '// tag::machine[]\n// end::machine[]\n')
        write(root / 'twins/refused.expected', 'original output\n')
        write(root / 'include/header.hpp', f'// Why ({DOC} #machines).\n')
        write(root / 'build.jam', 'project /webcpp/fixture ;\n')
        write(root / 'README.md', README)
        write(root / 'doc/page.adoc', PAGE)
        for part in (check_page, check_reference, check_examples, check_graph, check_references,
                     check_see_titles, check_readme, check_rendered, check_links,
                     check_without_git):
            part(root)
            print(f'{part.__name__}: ok')
    print('doc-check.py: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main())
