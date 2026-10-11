#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/ci/assemble.py: the site's own pages land at the root, the docs index at docs/,
each library's page under libs/<name>/ and the report under report/, or, without one, a page
that says no results were given; the site's header and its stylesheet head every page of docs/
and libs/, each link relative from its page; the catalogue gives each library's page its title,
description, canonical URL, Open Graph, Twitter card and JSON-LD, and a library whose title is
too long, or which the catalogue and the docs do not both have, fails, naming it. On the preview
channel every page of the site carries noindex, the report's as report.py wrote them included,
and a page of the site's own without it fails, naming it; on the release channel none does, and
a page that does fails; a channel other than the two is a usage error. Then --check:
every link resolves, the home links the libraries page and that page links every library; a
link to no file, to no fragment, from the server's root or out of the site is named and fails,
and so does an index built for the tree; an output directory that holds something is refused.
Run with the names of some cases to run only those."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ASSEMBLE = Path(__file__).resolve().parent / 'assemble.py'
BASE = 'https://webcpporg.github.io/'
# What the site's renderer writes in every page's head on the preview (site/src/head.ts).
NOINDEX = '<meta name="robots" content="noindex">'
ROBOTS = re.compile(r'<meta name="robots" content="([^"]*)">')
# The two headers the site renders: the light pages' (Asciidoctor's), whose mark is the light one,
# and the site's own, whose mark follows the reader's theme.
CHROME = ('<header class="site"><a class="logo" href="./"><img src="assets/logo-light.svg" '
          'alt="webcpp"></a><nav><a href="libraries/">Libraries</a>'
          '<a href="report/">Report</a></nav></header>')
SITE_CHROME = CHROME.replace('assets/logo-light.svg', 'assets/logo.svg')


def page(path: Path, body: str, title: str = 'a page', body_tag: str = '<body>',
         head: str = '') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
                    f'<title>{title}</title>\n{head}<style>p {{ margin: 0; }}</style>\n</head>\n'
                    f'{body_tag}\n{body}\n</body>\n</html>\n')


@dataclass
class Built:
    """The inputs of a run, as b2 site gives them: the site's rendered pages, the docs where
    `b2 doc -sWEBCPP_INDEX=site` writes them, the report, the header and the catalogue."""

    pages: Path
    docs: Path
    report: Path
    chrome: Path
    site_chrome: Path
    catalogue: Path


def built(scratch: Path, docs_index: str = '', links: str = '../libs/{name}/',
          home: str = '<a href="libraries/">Libraries</a>',
          titles: dict[str, str] | None = None, channel: str = 'preview') -> Built:
    """Inputs for the libraries alpha, a port, and beta, webcpp's own, the site's own pages
    rendered for channel. links is how the docs index links a library's page; home is the body of
    the site's home."""
    titles = titles or {'alpha': 'alpha: the first library', 'beta': 'beta: the second one'}
    robots = '<meta name="robots" content="{}">\n'.format(
        'noindex' if channel == 'preview' else 'index, follow')
    pages = scratch / 'pages'
    page(pages / 'index.html', f'<header class="site"></header>{home}<a href="docs/">Docs</a>'
         '<a href="report/">Report</a><a href="llms.txt">llms.txt</a>', 'Home - webcpp',
         head=robots)
    page(pages / 'libraries/index.html',
         '<a href="../libs/alpha/">alpha</a><a href="../libs/beta/">beta</a>',
         'Libraries - webcpp', head=robots)
    (pages / 'assets').mkdir()
    (pages / 'assets/site.css').write_text('body { margin: 0; }\n')
    (pages / 'assets/chrome.css').write_text('header.site { margin: 0; }\n')
    (pages / 'assets/logo.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>\n')
    (pages / 'assets/logo-light.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>\n')
    (pages / 'llms.txt').write_text('# webcpp\n')
    for name in ('alpha', 'beta'):
        (pages / 'cards/libs').mkdir(parents=True, exist_ok=True)
        (pages / f'cards/libs/{name}.png').write_bytes(b'\x89PNG')
    docs = scratch / 'tree'
    library_links = ''.join(f'<a href="{links.format(name=name)}">{name}</a>'
                            for name in ('alpha', 'beta'))
    page(docs / 'doc/html/index.html',
         f'{library_links}<a href="https://webcpporg.github.io/report/">matrix</a>'
         f'<a href="#top" id="top">top</a>{docs_index}', 'webcpp', '<body class="article">')
    page(docs / 'libs/alpha/doc/html/index.html',
         '<h2 id="usage">Usage</h2><a href="#usage">usage</a>'
         '<a href="https://github.com/webcpporg/alpha">source</a>', titles['alpha'],
         '<body class="article toc2 toc-left">')
    page(docs / 'libs/beta/doc/html/index.html', '<a name="old">old</a><a href="#old">old</a>',
         titles['beta'], '<body class="article">')
    (docs / 'libs/beta/doc/html/.DS_Store').write_bytes(b'Finder')
    report = scratch / 'report'
    page(report / 'index.html', '<a href="alpha.html#row">alpha</a>')
    page(report / 'alpha.html', '<tr id="row"><td><a href="output/gcc-14/x.txt">x</a></td></tr>')
    (report / 'output/gcc-14').mkdir(parents=True)
    (report / 'output/gcc-14/x.txt').write_text('output\n')
    chrome = scratch / 'docs-header.html'
    chrome.write_text(CHROME)
    site_chrome = scratch / 'site-header.html'
    site_chrome.write_text(SITE_CHROME)
    catalogue = scratch / 'libraries.json'
    catalogue.write_text(json.dumps([
        {'key': 'alpha', 'name': 'alpha', 'description': 'The first library, a port of Alpha.',
         'category': ['Parsing'], 'targets': ['emscripten', 'native'],
         'port_of': {'name': 'Alpha', 'language': 'JavaScript', 'version': '1.2.3',
                     'url': 'https://github.com/example/alpha', 'licence': 'MIT'},
         'page': 'libs/alpha/', 'repository': 'https://github.com/webcpporg/alpha'},
        {'key': 'beta', 'name': 'beta', 'description': 'The second library, webcpp\'s own.',
         'category': ['Concurrent'], 'targets': ['native', 'wasip2'], 'port_of': None,
         'page': 'libs/beta/', 'repository': 'https://github.com/webcpporg/beta'},
    ], indent=4))
    return Built(pages, docs, report, chrome, site_chrome, catalogue)


def lay_out(inputs: Built, out: Path, report: str | None = None,
            channel: str | None = 'preview') -> subprocess.CompletedProcess:
    """assemble.py's first form over inputs, for channel, or with no --channel when it is None."""
    return subprocess.run([sys.executable, str(ASSEMBLE), '--pages', str(inputs.pages),
                           '--docs', str(inputs.docs), '--report', report or str(inputs.report),
                           '--chrome', str(inputs.chrome), '--site-chrome', str(inputs.site_chrome),
                           '--catalogue', str(inputs.catalogue),
                           '--base', BASE, *(['--channel', channel] if channel else []),
                           '--out', str(out)],
                          capture_output=True, text=True, check=False)


def check(site: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ASSEMBLE), '--check', str(site)],
                          capture_output=True, text=True, check=False)


def assembled(inputs: Built, out: Path) -> subprocess.CompletedProcess:
    """Lays the site out, which must succeed, and returns the check of its links."""
    result = lay_out(inputs, out)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    return check(out)


def graph(html: str) -> list[dict]:
    found = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert found, html
    return json.loads(found.group(1))['@graph']


def test_the_site_pages_land_at_the_root_and_the_docs_index_at_docs(scratch: Path) -> None:
    out = scratch / 'site'
    result = assembled(built(scratch), out)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert '2 libraries, every link resolving' in result.stdout, result.stdout
    for name in ('index.html', 'libraries/index.html', 'assets/site.css', 'docs/index.html',
                 'libs/alpha/index.html', 'libs/beta/index.html', 'report/index.html',
                 'report/alpha.html', 'report/output/gcc-14/x.txt'):
        assert (out / name).is_file(), name
    assert 'Home - webcpp' in (out / 'index.html').read_text()
    assert not (out / 'doc').exists() and not (out / 'libs/alpha/doc').exists()
    assert not (out / 'libs/beta/.DS_Store').exists()
    assert 'href="../libs/alpha/"' in (out / 'docs/index.html').read_text()


def test_without_a_report_a_page_says_none_was_given(scratch: Path) -> None:
    out = scratch / 'site'
    result = lay_out(built(scratch), out, report='-')
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    report = (out / 'report/index.html').read_text()
    assert 'No test results were given to this build' in report
    # The site's own page, headed with the site's own header, whose mark follows the reader's theme
    # as the page itself does, and styled as the site's pages are.
    assert report.index('<body>\n<header class="site">') > 0, report
    assert 'src="../assets/logo.svg"' in report, report
    assert 'logo-light' not in report, report
    assert report.index('href="../assets/chrome.css"') < report.index('href="../assets/site.css"')
    result = check(out)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)


def test_the_header_and_the_stylesheet_head_every_docs_and_library_page(scratch: Path) -> None:
    out = scratch / 'site'
    result = assembled(built(scratch), out)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    for name, root in (('docs/index.html', '../'), ('libs/alpha/index.html', '../../'),
                       ('libs/beta/index.html', '../../')):
        html = (out / name).read_text()
        header = (f'<header class="site"><a class="logo" href="{root}"><img '
                  f'src="{root}assets/logo-light.svg" alt="webcpp"></a><nav><a '
                  f'href="{root}libraries/">Libraries</a><a href="{root}report/">Report</a>'
                  '</nav></header>')
        assert re.search(r'<body[^>]*>\n?' + re.escape(header), html), (name, html)
        assert html.count('<header class="site">') == 1, name
        stylesheet = f'<link rel="stylesheet" href="{root}assets/chrome.css">'
        assert html.index(stylesheet) < html.index('</head>'), name
        assert html.index('<style>') < html.index(stylesheet), name
    assert '<body class="article toc2 toc-left">' in (out / 'libs/alpha/index.html').read_text()
    # The site's own pages carry their header already.
    assert (out / 'index.html').read_text().count('<header class="site">') == 1


def test_the_catalogue_gives_each_library_page_its_head(scratch: Path) -> None:
    out = scratch / 'site'
    result = lay_out(built(scratch, channel='release'), out, channel='release')
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    html = (out / 'libs/alpha/index.html').read_text()
    head = html[:html.index('</head>')]
    canonical = f'{BASE}libs/alpha/'
    for text in ('<title>alpha: the first library - webcpp</title>',
                 '<meta name="description" content="The first library, a port of Alpha.">',
                 f'<link rel="canonical" href="{canonical}">',
                 '<meta name="robots" content="index, follow">',
                 '<meta property="og:title" content="alpha: the first library - webcpp">',
                 '<meta property="og:description" content="The first library, a port of Alpha.">',
                 f'<meta property="og:url" content="{canonical}">',
                 '<meta property="og:site_name" content="webcpp">',
                 f'<meta property="og:image" content="{BASE}cards/libs/alpha.png">',
                 '<meta property="og:image:width" content="1200">',
                 '<meta name="twitter:card" content="summary_large_image">',
                 '<meta name="twitter:title" content="alpha: the first library - webcpp">',
                 f'<meta name="twitter:image" content="{BASE}cards/libs/alpha.png">'):
        assert text in head, (text, head)
    assert head.count('<title>') == 1, head
    nodes = {node['@type']: node for node in graph(head)}
    software = nodes['SoftwareSourceCode']
    assert software['name'] == 'alpha' and software['programmingLanguage'] == 'C++', software
    assert software['codeRepository'] == 'https://github.com/webcpporg/alpha', software
    assert software['license'] == 'https://www.boost.org/LICENSE_1_0.txt', software
    assert software['runtimePlatform'] == ['WebAssembly', 'Emscripten', 'native'], software
    assert software['isBasedOn']['name'] == 'Alpha', software
    assert software['isBasedOn']['version'] == '1.2.3', software
    article = nodes['TechArticle']
    assert article['headline'] == 'alpha: the first library', article
    assert article['url'] == canonical, article
    assert article['about'] == {'@id': software['@id']}, article
    beta = {node['@type']: node for node in graph((out / 'libs/beta/index.html').read_text())}
    assert 'isBasedOn' not in beta['SoftwareSourceCode'], beta
    assert beta['SoftwareSourceCode']['runtimePlatform'] == ['WebAssembly', 'WASI 0.2', 'native']


def robots_of(site: Path) -> dict[str, list[str]]:
    """Every HTML page of site, by its path from the root, with the content of each of its
    robots metas."""
    return {page.relative_to(site).as_posix(): ROBOTS.findall(page.read_text(encoding='utf-8'))
            for page in sorted(site.rglob('*.html'))}


def test_on_the_preview_every_page_carries_noindex(scratch: Path) -> None:
    # The preview is the development version, never indexed (the owner, 2026-10-11): the site's
    # own pages carry noindex from its renderer, and assemble.py writes it into every page it lays
    # out, the docs', the libraries', and the report's, whether report.py wrote them or not.
    inputs = built(scratch)
    for report in (None, '-'):
        out = scratch / f'site{report or ""}'
        result = lay_out(inputs, out, report=report)
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
        robots = robots_of(out)
        expected = {'index.html', 'libraries/index.html', 'docs/index.html',
                    'libs/alpha/index.html', 'libs/beta/index.html', 'report/index.html'}
        if report is None:
            expected.add('report/alpha.html')
        assert set(robots) == expected, robots
        assert all(found == ['noindex'] for found in robots.values()), robots
        assert check(out).returncode == 0


def test_on_the_release_no_page_carries_noindex(scratch: Path) -> None:
    inputs = built(scratch, channel='release')
    for report in (None, '-'):
        out = scratch / f'site{report or ""}'
        result = lay_out(inputs, out, report=report, channel='release')
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
        robots = robots_of(out)
        assert not any('noindex' in content for found in robots.values() for content in found), (
            robots)
        assert robots['libs/alpha/index.html'] == ['index, follow'], robots


def test_a_site_page_without_noindex_fails_on_the_preview(scratch: Path) -> None:
    # The site's renderer writes the robots meta of the channel it is given: a page rendered for
    # the release, or with none, laid out as the preview's, fails rather than be indexed.
    inputs = built(scratch, channel='release')
    result = lay_out(inputs, scratch / 'site')
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    for name in ('index.html', 'libraries/index.html'):
        assert f'{name}: no {NOINDEX}' in result.stderr, (name, result.stderr)
    assert 'docs/index.html' not in result.stderr, result.stderr


def test_a_page_with_noindex_fails_on_the_release(scratch: Path) -> None:
    inputs = built(scratch)
    result = lay_out(inputs, scratch / 'site', channel='release')
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    for name in ('index.html', 'libraries/index.html'):
        assert f'{name}: noindex, which no page of the release carries' in result.stderr, (
            name, result.stderr)


def test_a_channel_is_preview_or_release(scratch: Path) -> None:
    for channel in (None, 'draft'):
        out = scratch / 'site'
        result = lay_out(built(scratch / str(channel)), out, channel=channel)
        assert result.returncode == 2, (channel, result.returncode, result.stderr)
        assert '--channel' in result.stderr, (channel, result.stderr)
        assert not out.exists(), channel


def test_a_library_whose_title_is_too_long_fails_naming_it(scratch: Path) -> None:
    titles = {'alpha': 'alpha: a library whose title says far more than a title ever should',
              'beta': 'beta: the second one'}
    result = lay_out(built(scratch, titles=titles), scratch / 'site')
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert 'libs/alpha: the title "alpha: a library whose title' in result.stderr, result.stderr
    assert 'more than 60' in result.stderr, result.stderr


def test_a_library_whose_title_does_not_name_it_fails(scratch: Path) -> None:
    titles = {'alpha': 'alpha: the first library', 'beta': 'Another library'}
    result = lay_out(built(scratch, titles=titles), scratch / 'site')
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert 'libs/beta: the title "Another library" does not start with "beta: "' in (
        result.stderr), result.stderr


def test_the_catalogue_and_the_docs_must_hold_the_same_libraries(scratch: Path) -> None:
    inputs = built(scratch)
    catalogue = json.loads(inputs.catalogue.read_text())
    inputs.catalogue.write_text(json.dumps(catalogue[:1] + [dict(catalogue[1], key='gamma',
                                                                 name='gamma',
                                                                 page='libs/gamma/')]))
    result = lay_out(inputs, scratch / 'site')
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    for text in ('libs/beta: no library of the catalogue has the key beta',
                 'the catalogue\'s library gamma has no page'):
        assert text in result.stderr, (text, result.stderr)


def test_a_library_without_its_card_fails(scratch: Path) -> None:
    inputs = built(scratch)
    (inputs.pages / 'cards/libs/beta.png').unlink()
    result = lay_out(inputs, scratch / 'site')
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert 'cards/libs/beta.png, the social card of libs/beta/, does not exist' in (
        result.stderr), result.stderr


def test_a_link_that_does_not_resolve_is_named(scratch: Path) -> None:
    inputs = built(scratch, '<a href="../libs/gamma/">gamma</a>'
                            '<a href="../libs/alpha/index.html#nowhere">a</a>'
                            '<img src="/logo.png" alt="logo">'
                            '<a href="/x">x</a>'
                            '<a href="../../elsewhere.html">out</a>')
    result = assembled(inputs, scratch / 'site')
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    for text in ('docs/index.html: ../libs/gamma/: libs/gamma does not exist',
                 "libs/alpha/index.html has no id 'nowhere'",
                 "docs/index.html: /logo.png: a path from the server's root",
                 "docs/index.html: /x: a path from the server's root",
                 '../../elsewhere.html: outside the site',
                 '5 faults in the links of'):
        assert text in result.stderr, (text, result.stderr)


def test_an_index_built_for_the_tree_fails(scratch: Path) -> None:
    # `b2 doc` without -sWEBCPP_INDEX=site: the index's links climb out of the site.
    inputs = built(scratch, links='../../libs/{name}/doc/html/index.html')
    result = assembled(inputs, scratch / 'site')
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert 'docs/index.html: ../../libs/beta/doc/html/index.html: outside the site' in (
        result.stderr), result.stderr


def test_the_home_must_link_the_libraries_page(scratch: Path) -> None:
    result = assembled(built(scratch, home=''), scratch / 'site')
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert 'index.html: no link to libraries/, the page of every library' in result.stderr, (
        result.stderr)


def test_the_libraries_page_links_every_library(scratch: Path) -> None:
    inputs = built(scratch)
    page(inputs.pages / 'libraries/index.html', '<a href="../libs/alpha/">alpha</a>',
         head=f'{NOINDEX}\n')
    result = assembled(inputs, scratch / 'site')
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert 'libraries/index.html: no link to libs/beta/, the page of the library beta' in (
        result.stderr), result.stderr


def test_a_library_without_its_page_fails(scratch: Path) -> None:
    inputs = built(scratch)
    (inputs.docs / 'libs/beta/doc/html/index.html').unlink()
    result = lay_out(inputs, scratch / 'site')
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert f'{inputs.docs / "libs/beta/doc/html/index.html"} does not exist' in result.stderr, (
        result.stderr)


def test_a_missing_page_fails(scratch: Path) -> None:
    inputs = built(scratch)
    (inputs.report / 'index.html').unlink()
    result = lay_out(inputs, scratch / 'site')
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert f'{inputs.report / "index.html"} does not exist' in result.stderr, result.stderr


def test_a_site_page_that_takes_a_place_of_the_docs_fails(scratch: Path) -> None:
    inputs = built(scratch)
    page(inputs.pages / 'docs/index.html', '<a href="../">home</a>')
    result = lay_out(inputs, scratch / 'site')
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert 'docs/: the site\'s pages hold it, and it is the docs index\'s place' in (
        result.stderr), result.stderr


def test_an_output_that_holds_something_is_refused(scratch: Path) -> None:
    inputs = built(scratch)
    out = scratch / 'site'
    out.mkdir()
    (out / 'left.html').write_text('left over\n')
    result = lay_out(inputs, out)
    assert result.returncode == 2, (result.returncode, result.stderr)
    assert 'is not an empty directory' in result.stderr, result.stderr


CASES: list[Callable[[Path], None]] = [
    test_the_site_pages_land_at_the_root_and_the_docs_index_at_docs,
    test_without_a_report_a_page_says_none_was_given,
    test_the_header_and_the_stylesheet_head_every_docs_and_library_page,
    test_the_catalogue_gives_each_library_page_its_head,
    test_on_the_preview_every_page_carries_noindex,
    test_on_the_release_no_page_carries_noindex,
    test_a_site_page_without_noindex_fails_on_the_preview,
    test_a_page_with_noindex_fails_on_the_release,
    test_a_channel_is_preview_or_release,
    test_a_library_whose_title_is_too_long_fails_naming_it,
    test_a_library_whose_title_does_not_name_it_fails,
    test_the_catalogue_and_the_docs_must_hold_the_same_libraries,
    test_a_library_without_its_card_fails,
    test_a_link_that_does_not_resolve_is_named,
    test_an_index_built_for_the_tree_fails,
    test_the_home_must_link_the_libraries_page,
    test_the_libraries_page_links_every_library,
    test_a_library_without_its_page_fails,
    test_a_missing_page_fails,
    test_a_site_page_that_takes_a_place_of_the_docs_fails,
    test_an_output_that_holds_something_is_refused,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'assemble_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='webcpp site ') as scratch:
            case(Path(scratch))
        print(f'{case.__name__}: ok')
    print('assemble_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
