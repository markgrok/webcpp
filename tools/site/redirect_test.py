#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks tools/site/redirect.py: it writes index.html and 404.html, each with the meta refresh
to the new address, its canonical link and noindex, as every page of webcpporg.github.io carries;
the script of each maps a path under the prefix to the
same path at the new address, its query and its fragment kept, the prefix itself to the new
root; and --to without https://, or a --prefix that is not a path between slashes, fails and
writes nothing. The script's target(location) is cut from each page between its markers and run
with node on objects shaped like window.location. Both pages are valid HTML by the rules the
site's own pages are checked with, site/.htmlvalidate.json, run with the site's html-validate,
installed as b2 installs it (tools/node/install.py); without the site checked out at site/ there
is no html-validate to run, which that case says, and passes. Run with the names of some cases to
run only those."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
REDIRECT = HERE / 'redirect.py'
SITE = ROOT / 'site'

TO = 'https://webcpporg.github.io/'
PREFIX = '/webcpp/'
PAGES = ('index.html', '404.html')

# The text between these two comments of a page's script defines target(location).
TARGET = re.compile(r'/\* target: begin \*/(.*?)/\* target: end \*/', re.DOTALL)


def run(out: Path, to: str = TO, prefix: str = PREFIX) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(REDIRECT), '--to', to, '--prefix', prefix,
                           '--out', str(out)],
                          capture_output=True, text=True, check=False, timeout=60)


def written(root: Path) -> Path:
    """The redirect site written into a fresh directory under root, with the plan's options."""
    out = root / 'redirect'
    result = run(out)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    return out


def location(url: str) -> dict[str, str]:
    """An object shaped like window.location for url."""
    parts = urlsplit(url)
    return {
        'href': url,
        'origin': f'{parts.scheme}://{parts.netloc}',
        'protocol': f'{parts.scheme}:',
        'host': parts.netloc,
        'hostname': parts.hostname or '',
        'port': '',
        'pathname': parts.path,
        'search': f'?{parts.query}' if parts.query else '',
        'hash': f'#{parts.fragment}' if parts.fragment else '',
    }


def targets(page: Path, urls: list[str]) -> list[str]:
    """What the page's target(location) returns for each url, run with node."""
    node = shutil.which('node')
    assert node is not None, 'node is not on PATH; the test runs the page\'s script with it'
    found = TARGET.search(page.read_text(encoding='utf-8'))
    assert found is not None, f'{page}: no script between /* target: begin */ and /* target: end */'
    program = (found.group(1) + '\nconst locations = JSON.parse(process.argv[1])\n'
               'process.stdout.write(JSON.stringify(locations.map(target)))\n')
    result = subprocess.run([node, '-e', program, json.dumps([location(url) for url in urls])],
                            capture_output=True, text=True, check=False, timeout=60)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    return json.loads(result.stdout)


def test_both_pages_exist_with_the_refresh_the_canonical_and_noindex(root: Path) -> None:
    out = written(root)
    for name in PAGES:
        page = out / name
        assert page.is_file(), f'{page} was not written'
        text = page.read_text(encoding='utf-8')
        assert f'<meta http-equiv="refresh" content="0; url={TO}">' in text, text
        assert f'<link rel="canonical" href="{TO}">' in text, text
        assert '<meta name="robots" content="noindex">' in text, text


def test_a_page_and_its_fragment_map_to_the_root(root: Path) -> None:
    out = written(root)
    for name in PAGES:
        assert targets(out / name, [
            'https://webcpporg.github.io/webcpp/libs/pratt/#pratt-limits',
        ]) == ['https://webcpporg.github.io/libs/pratt/#pratt-limits'], name


def test_the_prefix_maps_to_the_root(root: Path) -> None:
    out = written(root)
    for name in PAGES:
        assert targets(out / name, [
            'https://webcpporg.github.io/webcpp/',
            'https://webcpporg.github.io/webcpp',
        ]) == [TO, TO], name


def test_a_query_is_kept(root: Path) -> None:
    out = written(root)
    for name in PAGES:
        assert targets(out / name, [
            'https://webcpporg.github.io/webcpp/report/?lane=x',
        ]) == ['https://webcpporg.github.io/report/?lane=x'], name


def test_both_pages_are_valid_html(root: Path) -> None:
    if not (SITE / 'package-lock.json').is_file():
        print(f'{SITE} is not checked out: no html-validate to check the pages with')
        return
    install = subprocess.run([sys.executable, str(ROOT / 'tools/node/install.py'), str(SITE)],
                             capture_output=True, text=True, check=False, timeout=600)
    assert install.returncode == 0, (install.returncode, install.stdout, install.stderr)
    out = written(root)
    result = subprocess.run([str(SITE / 'node_modules/.bin/html-validate'),
                             '--config', str(SITE / '.htmlvalidate.json'),
                             *(str(out / name) for name in PAGES)],
                            capture_output=True, text=True, check=False, timeout=120,
                            env={**os.environ, 'FORCE_COLOR': '0'})
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)


def test_to_without_https_fails(root: Path) -> None:
    for to in ('http://webcpporg.github.io/', 'webcpporg.github.io/', 'https://'):
        out = root / 'redirect'
        result = run(out, to=to)
        assert result.returncode == 2, (to, result.returncode, result.stdout, result.stderr)
        assert '--to' in result.stderr and to in result.stderr, (to, result.stderr)
        assert not out.exists(), f'{out} was written for --to {to}'


def test_a_prefix_that_is_not_a_path_between_slashes_fails(root: Path) -> None:
    for prefix in ('webcpp/', '/webcpp', '/', '//'):
        out = root / 'redirect'
        result = run(out, prefix=prefix)
        assert result.returncode == 2, (prefix, result.returncode, result.stdout, result.stderr)
        assert '--prefix' in result.stderr, (prefix, result.stderr)
        assert not out.exists(), f'{out} was written for --prefix {prefix}'


CASES = [
    test_both_pages_exist_with_the_refresh_the_canonical_and_noindex,
    test_a_page_and_its_fragment_map_to_the_root,
    test_the_prefix_maps_to_the_root,
    test_a_query_is_kept,
    test_both_pages_are_valid_html,
    test_to_without_https_fails,
    test_a_prefix_that_is_not_a_path_between_slashes_fails,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'redirect_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='webcpp redirect ') as scratch:
            case(Path(scratch))
        print(f'{case.__name__}: ok')
    print('redirect_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
