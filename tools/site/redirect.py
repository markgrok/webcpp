#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Writes the redirect site of an old address: index.html and 404.html, which send a reader of
any page under the old prefix to the same page at the new address.

Usage: redirect.py --to <https://host/path/> --prefix </path/> --out <dir>

The CI publishes it where the site used to be, https://webcpporg.github.io/webcpp/, as

    redirect.py --to https://webcpporg.github.io/ --prefix /webcpp/ --out <dir>

GitHub Pages serves index.html for the prefix itself and 404.html for every other path under
it, so the two pages are the same. Each holds a script that replaces the location with the same
path without the prefix at the new address, its query and its fragment kept
(/webcpp/libs/pratt/#pratt-limits becomes https://webcpporg.github.io/libs/pratt/#pratt-limits),
and, for a browser that runs no script, a meta refresh to the new root and a link to it. Its
canonical link names the new root, and it carries noindex, as every page of webcpporg.github.io
does: the address is the development version's, which no search engine indexes (the owner,
2026-10-11).

The script's function target(location) stands between the comments /* target: begin */ and
/* target: end */, so that tools/site/redirect_test.py can run it alone.

--to is an https:// address that ends with a slash, and --prefix a path between slashes, each of
letters, digits and . _ ~ - alone, so that both go into the HTML and the script as they are. Any
other value is a usage error: nothing is written, and the exit status is 2.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

# The pages GitHub Pages serves under the prefix: index.html at the prefix, 404.html elsewhere.
PAGES = ('index.html', '404.html')

# A segment of a path, of characters that need no escaping in HTML, JavaScript or a URL.
SEGMENT = r'[A-Za-z0-9._~-]+'
TO = re.compile(rf'https://[A-Za-z0-9.-]+(:[0-9]+)?/({SEGMENT}/)*')
PREFIX = re.compile(rf'/({SEGMENT}/)+')

PAGE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>webcpp has moved</title>
<link rel="canonical" href="{to_attribute}">
<meta name="robots" content="noindex">
<script>
/* target: begin */
function target(location) {{
    var to = {to_script};
    var prefix = {prefix_script};
    var path = location.pathname;
    if (path.slice(0, prefix.length) === prefix) {{
        path = path.slice(prefix.length);
    }} else if (path + '/' === prefix) {{
        path = '';
    }} else {{
        path = path.replace(/^\\/+/, '');
    }}
    return to + path + location.search + location.hash;
}}
/* target: end */
window.location.replace(target(window.location));
</script>
<meta http-equiv="refresh" content="0; url={to_attribute}">
</head>
<body>
<p>webcpp's site has moved to <a href="{to_attribute}">{to_text}</a>.</p>
</body>
</html>
'''


def page(to: str, prefix: str) -> str:
    """The redirect page from prefix to to, both already checked."""
    return PAGE.format(to_attribute=html.escape(to), to_text=html.escape(to),
                       to_script=json.dumps(to), prefix_script=json.dumps(prefix))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description='Writes index.html and 404.html, which redirect every path under --prefix '
                    'to the same path at --to.')
    parser.add_argument('--to', required=True)
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--out', required=True, type=Path)
    options = parser.parse_args(argv)
    if not TO.fullmatch(options.to):
        parser.error(f'--to {options.to} is not an https:// address that ends with a slash, '
                     'such as https://webcpporg.github.io/')
    if not PREFIX.fullmatch(options.prefix):
        parser.error(f'--prefix {options.prefix} is not a path between slashes, such as '
                     '/webcpp/')
    text = page(options.to, options.prefix)
    options.out.mkdir(parents=True, exist_ok=True)
    for name in PAGES:
        (options.out / name).write_text(text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
