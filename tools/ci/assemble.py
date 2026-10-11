#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Lays out webcpp's site, which `b2 site` builds into bin/site/ (tools/site/site.jam), and checks
that every link in it resolves.

Usage: assemble.py --pages DIR --docs ROOT --report DIR|- --chrome FILE --site-chrome FILE
                   --catalogue FILE --base URL --channel preview|release --out DIR
       assemble.py --check DIR

The first form lays the site out in DIR, which is empty or does not exist:

  index.html, libraries/, ...   the site's own pages, as the site's `npm run build -- --render`
                                wrote them into --pages, with assets/ and cards/;
  docs/                         the docs index, what ROOT/doc/html holds;
  libs/<name>/                  each library's page, what ROOT/libs/<name>/doc/html holds;
  report/                       the test matrix tools/report/report.py wrote into --report, or,
                                with --report -, one page saying no results were given.

ROOT holds the pages `b2 doc -sWEBCPP_INDEX=site` built, where it builds them: a superproject's
root, or a copy of its doc/html and libs/<name>/doc/html. A place the site's own pages already
hold, docs/, libs/ or report/, fails.

Every page of docs/ and libs/, and the report's page of the second kind, gets the site's header
and its style: the header's HTML, with its links from the site's root, inserted after the page's
<body> with each relative link rebased from the page; and a <link rel="stylesheet"> to
assets/chrome.css, relative from the page, goes before its </head>. That stylesheet styles the
header and nothing else, so that a page Asciidoctor styled keeps its look. Asciidoctor's pages,
light alone, get --chrome, whose mark is the light one; the report's page of the second kind is
the site's own, links site.css too and turns dark with the reader's theme, so it gets
--site-chrome, whose mark follows the theme.

--catalogue is the site's libraries.json (tools/site/catalogue.py). Each library of ROOT/libs is
one of its entries, by key, and each entry has its page. A library's page gets the head the
site's own pages have (site/src/head.ts and site/src/software.ts, mirrored here), at --base, the
channel's absolute URL ending with "/":

  <title>               the page's own title, "<name>: <subject>" as Asciidoctor wrote it from
                        the page's heading, then " - webcpp", at most 60 characters;
  description           the catalogue's description;
  canonical, Open Graph and the Twitter card, whose image is cards/libs/<key>.png, the card the
                        site's build renders for each library;
  JSON-LD               SoftwareSourceCode (isBasedOn the original of a port), TechArticle and
                        BreadcrumbList.

A page whose title does not start with "<name>: ", or is longer, with " - webcpp", than 60
characters, fails, naming the library.

--channel is the site's (tools/site/site.jam). The preview, the development version, is never
indexed (the owner, 2026-10-11): every page assemble.py lays out, of docs/, libs/ and report/,
the report's pages as report.py wrote them included, gets <meta name="robots" content="noindex">
in its head, a library's page in place of the "index, follow" its head has on the release. Then
every page of the site, the site's own too, which its renderer writes for the channel it is given
(site/src/head.ts), is checked: on the preview each must carry noindex and nothing else of robots,
on the release none may carry noindex, and each page that does not hold is named.

The first form exits 0 with the site written; 1 when an input is missing or does not agree with
the others, or a page's robots with its channel, each fault named; 2 on a usage error or when DIR
exists and is not empty. Its links are left for the second form, which b2 site runs once the
indexing files, which the pages link, are written.

The second form checks the site in DIR: the home links libraries/, and libraries/index.html links
every library of libs/; every href and src of every page that is not a URL (no scheme, not //)
names a file of the site, a directory standing for its index.html, and its fragment, if any, an
id or a name in that page. A path from the server's root fails: the site works at any address, so
every link is relative. An index built without -sWEBCPP_INDEX=site links out of the site, and
fails. Exit 0 when every link resolves; 1 when one does not, each named.
"""

from __future__ import annotations

import argparse
import html
import json
import posixpath
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

TITLE_LIMIT = 60
LICENCE = 'https://www.boost.org/LICENSE_1_0.txt'
# What schema.org's runtimePlatform names for each target, in this order (site/src/software.ts).
PLATFORMS = {'emscripten': 'Emscripten', 'wasip2': 'WASI 0.2', 'wasip3': 'WASI 0.3',
             'native': 'native'}
NO_RESULTS = 'No test results were given to this build'
# What a page tells a search engine on each channel (site/src/head.ts).
ROBOTS = {'preview': 'noindex', 'release': 'index, follow'}
NOINDEX = '<meta name="robots" content="noindex">'
# The robots metas of a page, whatever the order and quoting of their attributes.
ROBOTS_META = re.compile(r'<meta\b(?=[^>]*\bname\s*=\s*["\']?robots\b)[^>]*>', re.I)
CONTENT = re.compile(r'\bcontent\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))', re.I)


class Failure(Exception):
    """What keeps the site from being written whole, said to the user."""


class Links(HTMLParser):
    """The links of a page (each href and src) and the fragments it defines (each id and name)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.anchors: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if value is None:
                continue
            if name in ('href', 'src'):
                self.links.append(value)
            elif name == 'id' or (name == 'name' and tag == 'a'):
                self.anchors.add(value)


def read(page: Path) -> Links:
    parser = Links()
    parser.feed(page.read_text(encoding='utf-8', errors='replace'))
    parser.close()
    return parser


def copy(source: Path, destination: Path) -> None:
    """Copies the directory of pages source to destination, which it requires an index.html."""
    if not (source / 'index.html').is_file():
        raise Failure(f'{source / "index.html"} does not exist; build the pages with b2 doc')
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('.*'), dirs_exist_ok=True)


def is_relative(link: str) -> bool:
    """Whether link names a place of the site from its page: no scheme, no host, no root."""
    parts = urlsplit(link)
    return not (parts.scheme or parts.netloc or link.startswith('/') or link.startswith('#'))


def rebased(fragment: str, root: str) -> str:
    """The HTML fragment, whose relative links start at the site's root, for a page whose way
    back to the root is root ("../../"): each href and src prefixed with it, "./" the root
    itself."""
    def rebase(found: re.Match[str]) -> str:
        link = found.group(2)
        if is_relative(link):
            link = root + link.removeprefix('./') or './'
        return f'{found.group(1)}="{link}"'
    return re.sub(r'\b(href|src)="([^"]*)"', rebase, fragment)


def root_of(site: Path, page: Path) -> str:
    """The way from page, a file of site, back to the site's root: "", "../", ..."""
    return '../' * (len(page.relative_to(site).parts) - 1)


def headed(text: str, name: str, chrome: str, root: str, head: str = '') -> str:
    """The page text, named name, with head and the chrome's stylesheet before its </head>, and the
    header chrome after its <body>."""
    body = re.search(r'<body\b[^>]*>', text)
    if '</head>' not in text or not body:
        raise Failure(f'{name}: no <body> or no </head> to put the site\'s header in')
    stylesheet = f'<link rel="stylesheet" href="{root}assets/chrome.css">\n'
    text = text[:body.end()] + '\n' + rebased(chrome, root) + text[body.end():]
    return text.replace('</head>', f'{head}{stylesheet}</head>', 1)


def robots_faults(site: Path, channel: str) -> list[str]:
    """Each page of site whose robots metas are not its channel's: on the preview, noindex alone;
    on the release, anything but noindex."""
    faults = []
    for page in sorted(site.rglob('*.html')):
        name = page.relative_to(site).as_posix()
        contents = []
        for meta in ROBOTS_META.findall(page.read_text(encoding='utf-8')):
            found = CONTENT.search(meta)
            contents.append(next(group for group in found.groups() if group is not None)
                            if found else '')
        noindex = [content for content in contents if 'noindex' in content.lower()]
        if channel == 'preview' and (not noindex or len(contents) != 1):
            faults.append(f'{name}: no {NOINDEX}, which every page of the preview carries as its'
                          ' only robots, the development version being never indexed'
                          + (f' (its robots: {", ".join(contents)})' if contents else ''))
        elif channel == 'release' and noindex:
            faults.append(f'{name}: noindex, which no page of the release carries')
    return faults


def no_results() -> str:
    """The report's page when the build was given no results, which headed() then heads: the
    site's own style comes after the chrome's, whose light tokens it turns dark."""
    title = 'The test matrix - webcpp'
    return ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>{title}</title>\n</head>\n<body>\n<main>\n<h1>The test matrix</h1>\n'
            f'<p>{NO_RESULTS}. The matrix shows the results of the lanes the superproject\'s CI '
            'runs, and a local build of the site has none.</p>\n</main>\n</body>\n</html>\n')


def runtime_platform(targets: list[str]) -> list[str]:
    """The platforms a library runs on, from its targets, as site/src/software.ts names them."""
    wasm = any(target == 'emscripten' or target.startswith('wasip') for target in targets)
    return (['WebAssembly'] if wasm else []) + [
        platform for target, platform in PLATFORMS.items() if target in targets] + [
        target for target in targets if target not in PLATFORMS]


def script_json(value: Any) -> str:
    """JSON for a <script> element: every < written \\u003c, which JSON.parse reads back."""
    return json.dumps(value, ensure_ascii=False).replace('<', '\\u003c')


def library_head(library: dict[str, Any], heading: str, base: str, channel: str) -> str:
    """The head of the page of library, whose own title is heading, served at base on channel."""
    title = f'{heading} - webcpp'
    canonical = base + library['page']
    image = f'{base}cards/{library["page"].rstrip("/")}.png'
    software: dict[str, Any] = {
        '@type': 'SoftwareSourceCode',
        '@id': f'{canonical}#software',
        'name': library['name'],
        'description': library['description'],
        'url': canonical,
        'codeRepository': library['repository'],
        'programmingLanguage': 'C++',
        'license': LICENCE,
        'runtimePlatform': runtime_platform(library['targets']),
    }
    original = library.get('port_of')
    if original:
        software['isBasedOn'] = {'@type': 'SoftwareSourceCode', 'name': original['name'],
                                 'url': original['url'], 'version': original['version'],
                                 'programmingLanguage': original['language']}
    article = {
        '@type': 'TechArticle',
        '@id': f'{canonical}#article',
        'headline': heading,
        'description': library['description'],
        'url': canonical,
        'inLanguage': 'en',
        'about': {'@id': software['@id']},
        'isPartOf': {'@id': f'{base}#website'},
        'publisher': {'@id': f'{base}#organization'},
    }
    crumbs = [('webcpp', base), ('Libraries', f'{base}libraries/'), (library['name'], canonical)]
    breadcrumbs = {
        '@type': 'BreadcrumbList',
        '@id': f'{canonical}#breadcrumb',
        'itemListElement': [{'@type': 'ListItem', 'position': position, 'name': name,
                             'item': item}
                            for position, (name, item) in enumerate(crumbs, start=1)],
    }
    alt = f'{title}: the page\'s title beside webcpp\'s logo'

    def meta(key: str, name: str, content: str) -> str:
        return f'<meta {key}="{name}" content="{html.escape(content)}">'
    lines = [
        f'<title>{html.escape(title, quote=False)}</title>',
        meta('name', 'description', library['description']),
        f'<link rel="canonical" href="{html.escape(canonical)}">',
        meta('name', 'robots', ROBOTS[channel]),
        meta('property', 'og:title', title),
        meta('property', 'og:description', library['description']),
        meta('property', 'og:url', canonical),
        meta('property', 'og:type', 'article'),
        meta('property', 'og:site_name', 'webcpp'),
        meta('property', 'og:image', image),
        meta('property', 'og:image:width', '1200'),
        meta('property', 'og:image:height', '630'),
        meta('property', 'og:image:alt', alt),
        meta('name', 'twitter:card', 'summary_large_image'),
        meta('name', 'twitter:title', title),
        meta('name', 'twitter:description', library['description']),
        meta('name', 'twitter:image', image),
        meta('name', 'twitter:image:alt', alt),
        '<script type="application/ld+json">'
        + script_json({'@context': 'https://schema.org',
                       '@graph': [software, article, breadcrumbs]})
        + '</script>',
    ]
    return '\n'.join(lines) + '\n'


def page_title(text: str, name: str) -> str:
    """The title of a library's page, as Asciidoctor wrote it from its heading, with its entities
    read: "xstate: XState's state machines and actors for C++"."""
    found = re.search(r'<title>(.*?)</title>', text, re.S)
    if not found:
        raise Failure(f'libs/{name}: the page has no <title>')
    return ' '.join(html.unescape(found.group(1)).split())


def with_library_head(text: str, library: dict[str, Any], base: str,
                      channel: str) -> tuple[str, str, str]:
    """The page of library without its own <title> and description, the fault of its title or
    "", and the site's head for it, which takes their place."""
    name = library['key']
    heading = page_title(text, name)
    fault = ''
    if not heading.startswith(f'{library["name"]}: '):
        fault = (f'libs/{name}: the title "{heading}" does not start with "{library["name"]}: ", '
                 'as the head of every library\'s page does')
    elif len(f'{heading} - webcpp') > TITLE_LIMIT:
        fault = (f'libs/{name}: the title "{heading} - webcpp" is '
                 f'{len(heading) + len(" - webcpp")} characters, more than {TITLE_LIMIT}; '
                 'shorten the heading of the library\'s page')
    text = re.sub(r'<title>.*?</title>\n?', '', text, count=1, flags=re.S)
    text = re.sub(r'<meta name="description"[^>]*>\n?', '', text)
    return text, fault, library_head(library, heading, base, channel)


def assemble(pages: Path, docs: Path, report: Path | None, chrome: str, site_chrome: str,
             catalogue: list[dict[str, Any]], base: str, channel: str,
             out: Path) -> list[str]:
    """Writes the site into out, which is empty or does not exist, and returns the libraries."""
    libraries = sorted(library.name for library in (docs / 'libs').glob('*') if library.is_dir())
    if not libraries:
        raise Failure(f'{docs / "libs"} holds no library')
    entries = {entry['key']: entry for entry in catalogue}
    faults = [f'libs/{name}: no library of the catalogue has the key {name}'
              for name in libraries if name not in entries]
    faults += [f'the catalogue\'s library {key} has no page: {docs / "libs" / key} does not exist'
               for key in sorted(entries) if key not in libraries]
    faults += [f'cards/libs/{name}.png, the social card of libs/{name}/, does not exist in '
               f'{pages}; the site\'s build renders one for each library of the catalogue'
               for name in libraries if name in entries
               and not (pages / f'cards/{entries[name]["page"].rstrip("/")}.png').is_file()]
    faults += [f'{place}/: the site\'s pages hold it, and it is the {whose} place'
               for place, whose in (('docs', 'docs index\'s'), ('libs', 'libraries\''),
                                    ('report', 'report\'s'))
               if (pages / place).exists()]
    if faults:
        raise Failure('\n'.join(faults))
    copy(pages, out)
    copy(docs / 'doc/html', out / 'docs')
    for name in libraries:
        copy(docs / 'libs' / name / 'doc/html', out / 'libs' / name)
    if report:
        copy(report, out / 'report')
    else:
        (out / 'report').mkdir()
        (out / 'report/index.html').write_text(no_results(), encoding='utf-8')
    headed_pages = [*sorted((out / 'docs').rglob('*.html')),
                    *sorted((out / 'libs').rglob('*.html'))]
    if not report:
        headed_pages.append(out / 'report/index.html')
    # A page of report.py's is the site's own already, and is laid out as it was written, but for
    # the preview's noindex.
    noindex = f'{NOINDEX}\n' if channel == 'preview' else ''
    for page in sorted((out / 'report').rglob('*.html')) if report and noindex else []:
        name = page.relative_to(out).as_posix()
        text = page.read_text(encoding='utf-8')
        if '</head>' not in text:
            raise Failure(f'{name}: no </head> to put the preview\'s noindex before')
        page.write_text(text.replace('</head>', f'{noindex}</head>', 1), encoding='utf-8')
    for page in headed_pages:
        name = page.relative_to(out).as_posix()
        text = page.read_text(encoding='utf-8')
        head = noindex
        library = re.fullmatch(r'libs/([^/]+)/index\.html', name)
        if library:
            text, fault, head = with_library_head(text, entries[library.group(1)], base, channel)
            if fault:
                faults.append(fault)
        own = name == 'report/index.html'
        text = headed(text, name, site_chrome if own else chrome, root_of(out, page), head)
        if own:
            text = text.replace('</head>', '<link rel="stylesheet" href="../assets/site.css">\n'
                                '</head>', 1)
        page.write_text(text, encoding='utf-8')
    faults += robots_faults(out, channel)
    if faults:
        raise Failure('\n'.join(faults))
    return libraries


def linked(site: Path, page: str) -> set[str]:
    """What the page of site links in the site, each as its path from the site's root, a
    directory without its index.html: "libs/alpha"."""
    found = set()
    for link in read(site / page).links:
        parts = urlsplit(link)
        if not (parts.scheme or parts.netloc) and parts.path:
            target = posixpath.normpath(posixpath.join(posixpath.dirname(page),
                                                       unquote(parts.path)))
            found.add(target.removesuffix('/index.html'))
    return found


def unlinked(site: Path, libraries: list[str]) -> list[str]:
    """The home without its link to the libraries page, and each library whose page that page
    does not link."""
    faults = []
    if 'libraries' not in linked(site, 'index.html'):
        faults.append('index.html: no link to libraries/, the page of every library')
    if not (site / 'libraries/index.html').is_file():
        return faults + ['libraries/index.html does not exist; the site\'s pages hold it']
    listed = linked(site, 'libraries/index.html')
    return faults + [f'libraries/index.html: no link to libs/{name}/, the page of the library '
                     f'{name}' for name in libraries if f'libs/{name}' not in listed]


def broken_links(site: Path) -> list[str]:
    """Each link of a page of site that resolves to no file, or to no fragment of its page."""
    pages = {page.relative_to(site).as_posix(): read(page) for page in sorted(site.rglob('*.html'))}
    broken = []
    for name, page in pages.items():
        for link in page.links:
            parts = urlsplit(link)
            if parts.scheme or parts.netloc:
                continue
            path = unquote(parts.path)
            if path.startswith('/'):
                broken.append(f'{name}: {link}: a path from the server\'s root, which the site '
                              'refuses: every link is relative, so the site works at any address')
                continue
            target = name
            if path:
                target = posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
                if target == '..' or target.startswith('../'):
                    broken.append(f'{name}: {link}: outside the site')
                    continue
                if (site / target).is_dir():
                    target = posixpath.join(target, 'index.html') if target != '.' else (
                        'index.html')
                if not (site / target).is_file():
                    broken.append(f'{name}: {link}: {target} does not exist')
                    continue
            fragment = unquote(parts.fragment)
            if fragment and target in pages and fragment not in pages[target].anchors:
                broken.append(f'{name}: {link}: {target} has no id {fragment!r}')
    return broken


def counted(site: Path) -> tuple[int, int]:
    """The pages of site and its libraries."""
    pages = sum(1 for _ in site.rglob('*.html'))
    return pages, sum(1 for library in (site / 'libs').glob('*') if library.is_dir())


def libraries_said(count: int) -> str:
    return f'{count} librar{"ies" if count != 1 else "y"}'


def check(site: Path) -> int:
    """The second form: every link of the site in site checked."""
    if not (site / 'index.html').is_file():
        print(f'assemble.py: {site / "index.html"} does not exist; lay the site out first',
              file=sys.stderr)
        return 1
    libraries = sorted(library.name for library in (site / 'libs').glob('*') if library.is_dir())
    faults = unlinked(site, libraries) + broken_links(site)
    if faults:
        print('\n'.join(f'assemble.py: {text}' for text in faults), file=sys.stderr)
        print(f'assemble.py: {len(faults)} fault{"s" if len(faults) != 1 else ""} in the links '
              f'of {site}', file=sys.stderr)
        return 1
    pages, count = counted(site)
    print(f'assemble.py: checked {site}, {pages} pages, {libraries_said(count)}, every link '
          'resolving')
    return 0


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='assemble.py',
                                     description=(__doc__ or '').split('\n', 1)[0])
    parser.add_argument('--check', type=Path, metavar='DIR')
    parser.add_argument('--pages', type=Path, metavar='DIR')
    parser.add_argument('--docs', type=Path, metavar='ROOT')
    parser.add_argument('--report', metavar='DIR|-')
    parser.add_argument('--chrome', type=Path, metavar='FILE')
    parser.add_argument('--site-chrome', type=Path, metavar='FILE')
    parser.add_argument('--catalogue', type=Path, metavar='FILE')
    parser.add_argument('--base', metavar='URL')
    parser.add_argument('--channel', choices=tuple(ROBOTS))
    parser.add_argument('--out', type=Path, metavar='DIR')
    options = parser.parse_args(arguments)
    layout = ('pages', 'docs', 'report', 'chrome', 'site_chrome', 'catalogue', 'base', 'channel',
              'out')
    if options.check:
        given = [f'--{name.replace("_", "-")}' for name in layout
                 if getattr(options, name) is not None]
        if given:
            parser.error(f'--check takes no other option, and {", ".join(given)} given')
        return check(options.check)
    missing = [f'--{name.replace("_", "-")}' for name in layout if getattr(options, name) is None]
    if missing:
        parser.error(f'{", ".join(missing)} required, or --check DIR')
    if not re.fullmatch(r'https?://[^/?#]+/([^?#]*/)?', options.base):
        parser.error(f'--base {options.base} is not an absolute http(s) URL ending with "/"')
    out: Path = options.out
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        parser.error(f'--out {out} exists and is not an empty directory')
    try:
        chrome = options.chrome.read_text(encoding='utf-8')
        site_chrome = options.site_chrome.read_text(encoding='utf-8')
        catalogue = json.loads(options.catalogue.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        print(f'assemble.py: {error}', file=sys.stderr)
        return 1
    report = None if options.report == '-' else Path(options.report)
    try:
        assemble(options.pages, options.docs, report, chrome, site_chrome, catalogue,
                 options.base, options.channel, out)
    except Failure as failure:
        print('\n'.join(f'assemble.py: {line}' for line in str(failure).split('\n')),
              file=sys.stderr)
        return 1
    pages, count = counted(out)
    print(f'assemble.py: wrote {out}, {pages} pages, {libraries_said(count)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
