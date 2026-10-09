#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks the compiled Boost libraries the Jamroot builds from Boost's sources: /webcpp//boost_url
links natively, on wasip2, wasip3 and emscripten, and in a user's build without exceptions, each
time an archive of the build's own, never the system's; a program that uses Boost.URL without it
does not link; and the sources are -sBOOST_SOURCE=<dir>, else user-config.jam's BOOST_SOURCE, else
.local/boost-source, a missing tree, a tree of another Boost version and a tree without the
library's sources each stopping the build by name, while a build that needs none never looks.
Each case builds a scratch superproject with the fixture library demo, whose path holds a space.
Run with the names of some cases to run only those."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import harness

WASIP2 = ('toolset=clang-wasip2', 'testing.launcher=wasmtime')
WASIP3 = ('toolset=clang-wasip3', 'testing.launcher=wasmtime')
EMSCRIPTEN = ('toolset=emscripten',)

PASSED = re.compile(r'^\*\*passed\*\* (.*)$', re.MULTILINE)

URLS_JAMFILE = ('import webcpp ;\n'
                '\n'
                'webcpp.targets native wasip2 wasip3 emscripten ;\n'
                '\n'
                'webcpp.run urls : urls.cpp : <library>/webcpp//boost_url ;\n')

# ipv4_address(bytes_type) and to_bytes() are defined in Boost.URL's compiled sources alone, which
# is why formats needs the library (WEBCPP_FORMATS_SPEC section 8.2).
URLS_SOURCE = r'''#include <boost/url/ipv4_address.hpp>
#include <boost/url/parse.hpp>

#include <cstdio>

int main() {
    boost::urls::ipv4_address::bytes_type const bytes{{127, 0, 0, 1}};
    boost::urls::ipv4_address const address(bytes);
    auto const parsed = boost::urls::parse_uri("http://example.com/a?b#c");
    bool const ok = parsed.has_value() && parsed->host() == "example.com" &&
                    address.to_bytes() == bytes;
    std::puts(ok ? "parsed" : "not parsed");
    return ok ? 0 : 1;
}
'''


def passed(result):
    """The tests b2 reports as passed, by name."""
    return {path.rsplit('/', 1)[-1].removesuffix('.test') for path in PASSED.findall(result.stdout)}


def archives(root: Path) -> list[Path]:
    """Every libboost_url.a the build made under the scratch superproject's bin/."""
    return sorted((root / 'bin').rglob('libboost_url.a'))


def add_urls(root: Path, jamfile: str = URLS_JAMFILE) -> None:
    harness.add_library(root, 'urls', jamfile, {'urls.cpp': URLS_SOURCE})


def fake_sources(directory: Path, version: int, with_url: bool = True) -> Path:
    """Writes in directory a tree of Boost's sources that is only a version.hpp defining version,
    such as 109100, and, with_url, one source of Boost.URL; returns it."""
    (directory / 'boost').mkdir(parents=True)
    (directory / 'boost/version.hpp').write_text(f'#define BOOST_VERSION {version}\n')
    if with_url:
        (directory / 'libs/url/src').mkdir(parents=True)
        (directory / 'libs/url/src/fake.cpp').write_text('int fake_url() { return 0; }\n')
    return directory


def test_boost_url_links_on_every_target(root: Path) -> None:
    harness.link_emsdk(root)
    add_urls(root)
    gcc = harness.gcc_request(root)
    requests = ((), WASIP2, WASIP3, EMSCRIPTEN, ('exception-handling=off',),
                (*WASIP2, 'exception-handling=off'), *((gcc,) if gcc else ()))
    for count, request in enumerate(requests, start=1):
        result = harness.run_b2(root, '-d+2', *request, 'libs/urls/test')
        harness.expect(result, True)
        assert passed(result) == {'urls'}, (request, passed(result), result.stdout[-4000:])
        # One archive more for each variant, built from the sources: never the system's own
        # libboost_url, which Homebrew ships.
        assert len(archives(root)) == count, (request, archives(root))
        assert '-lboost_url' not in result.stdout, (request, result.stdout[-4000:])


def test_without_the_library_a_program_does_not_link(root: Path) -> None:
    add_urls(root, URLS_JAMFILE.replace(' : <library>/webcpp//boost_url', ''))
    result = harness.run_b2(root, '-a', 'libs/urls/test')
    harness.expect(result, False)
    assert re.search(r'^\.\.\.failed .*urls', result.stdout, re.MULTILINE), result.stdout[-4000:]


def test_missing_sources_are_refused_naming_the_fix(root: Path) -> None:
    harness.without_boost_source(root)
    add_urls(root)
    result = harness.run_b2(root, 'libs/urls/test')
    harness.expect(result, False,
                   "Boost's sources, which a compiled Boost library of /webcpp is built from, "
                   'were not found: no -sBOOST_SOURCE=<dir> was given',
                   'install.sh source .local/boost-source')
    harness.expect(harness.run_b2(root, 'libs/demo/test//pass'), True)


def test_sources_of_another_version_are_refused(root: Path) -> None:
    sources = fake_sources(root / 'old sources', 109100)
    add_urls(root)
    result = harness.run_b2(root, f'-sBOOST_SOURCE={sources}', 'libs/urls/test')
    harness.expect(result, False, "holds Boost 1.91.0's sources", 'is 1.92.0')


def test_a_tree_without_the_library_s_sources_is_refused(root: Path) -> None:
    sources = fake_sources(root / 'no url', 109200, with_url=False)
    add_urls(root)
    result = harness.run_b2(root, f'-sBOOST_SOURCE={sources}', 'libs/urls/test')
    harness.expect(result, False, 'libs/url/src holds no .cpp file')


def test_sources_named_by_user_config(root: Path) -> None:
    # The CI's path: the Boost action's modules.poke in user-config.jam, and no -sBOOST_SOURCE.
    harness.without_boost_source(root)
    text = harness.user_config(root).read_text()
    harness.configure(root, text + f'modules.poke : BOOST_SOURCE : "{harness.boost_source()}" ;\n')
    add_urls(root)
    result = harness.run_b2(root, 'libs/urls/test')
    harness.expect(result, True)
    assert passed(result) == {'urls'}, (passed(result), result.stdout[-4000:])
    missing = root / 'no sources'
    harness.configure(root, text + f'modules.poke : BOOST_SOURCE : "{missing}" ;\n')
    harness.expect(harness.run_b2(root, 'libs/urls/test'), False,
                   f"user-config.jam's BOOST_SOURCE, {missing}, holds no boost/version.hpp")


def test_the_command_line_wins(root: Path) -> None:
    # Over .local/boost-source and over user-config.jam's BOOST_SOURCE, which b2 reads after the
    # command line and which would replace its -s value; a missing tree is named as given there.
    harness.without_boost_source(root)
    fake_sources(root / '.local/boost-source', 109100)
    poked = fake_sources(root / 'poked sources', 109100)
    harness.configure(root, harness.user_config(root).read_text()
                      + f'modules.poke : BOOST_SOURCE : "{poked}" ;\n')
    add_urls(root)
    result = harness.run_b2(root, f'-sBOOST_SOURCE={harness.boost_source()}', 'libs/urls/test')
    harness.expect(result, True)
    assert passed(result) == {'urls'}, (passed(result), result.stdout[-4000:])
    missing = root / 'no sources'
    harness.expect(harness.run_b2(root, f'-sBOOST_SOURCE={missing}', 'libs/urls/test'), False,
                   f'-sBOOST_SOURCE={missing} holds no boost/version.hpp')


CASES = [
    test_boost_url_links_on_every_target,
    test_without_the_library_a_program_does_not_link,
    test_missing_sources_are_refused_naming_the_fix,
    test_sources_of_another_version_are_refused,
    test_a_tree_without_the_library_s_sources_is_refused,
    test_sources_named_by_user_config,
    test_the_command_line_wins,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('boost_libraries_test', CASES, sys.argv[1:]))
