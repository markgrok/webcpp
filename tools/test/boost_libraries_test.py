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
library's sources each stopping the build by name, while a build that needs none never looks;
/webcpp//boost_charconv links on every target, with and without exceptions; /webcpp//boost_locale
converts, and translates from a catalog, natively, on wasip2, wasip3 and emscripten, where its
sources alone are told that pthreads are there, which no public header depends on, and is refused
by name without exceptions.
Each case builds a scratch superproject with the fixture library demo, whose path holds a space.
Run with the names of some cases to run only those."""

from __future__ import annotations

import re
import shutil
import struct
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
# is why lexical needs the library (WEBCPP_FORMATS_SPEC section 8.2).
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
        # The usage requirements reach the program: Boost.URL's macros of a static library,
        # which keep MSVC's auto-link and dllimport off.
        compiles = [line for line in result.stdout.splitlines()
                    if 'urls.cpp' in line and ' -c ' in line]
        assert compiles, (request, result.stdout[-4000:])
        for define in ('-DBOOST_URL_STATIC_LINK=1', '-DBOOST_URL_NO_LIB=1'):
            assert all(define in line for line in compiles), (request, define, compiles)


def test_without_the_library_a_program_does_not_link(root: Path) -> None:
    add_urls(root, URLS_JAMFILE.replace(' : <library>/webcpp//boost_url', ''))
    result = harness.run_b2(root, '-a', 'libs/urls/test')
    harness.expect(result, False)
    # The link fails, on a definition of Boost.URL's compiled sources, not the compile.
    assert re.search(r'^\.\.\.failed \S+\.link .*urls', result.stdout, re.MULTILINE), (
        result.stdout[-4000:])
    assert 'ipv4_address' in result.stdout, result.stdout[-4000:]
    assert not re.search(r'^\.\.\.failed \S+\.compile', result.stdout, re.MULTILINE), (
        result.stdout[-4000:])


def test_missing_sources_are_refused_naming_the_fix(root: Path) -> None:
    harness.without_boost_source(root)
    add_urls(root)
    result = harness.run_b2(root, 'libs/urls/test')
    harness.expect(result, False,
                   "Boost's sources, which a compiled Boost library of /webcpp is built from, "
                   'were not found: no -sBOOST_SOURCE=<dir> was given',
                   'install.sh source .local/boost-source')
    harness.expect(harness.run_b2(root, 'libs/demo/test//pass'), True)


def with_sources_of(directory: Path, *libraries: str) -> Path:
    """Copies into the tree directory the libs/<library>/src of each of libraries from the tree
    this checkout builds with; returns it."""
    for library in libraries:
        shutil.copytree(harness.boost_source() / 'libs' / library / 'src',
                        directory / 'libs' / library / 'src')
    return directory


def test_sources_of_another_version_are_refused(root: Path) -> None:
    # Each library's alias checks the tree's version, whose sources are otherwise all there.
    sources = with_sources_of(fake_sources(root / 'old sources', 109100), 'charconv', 'locale')
    add_urls(root)
    harness.add_library(root, 'numbers', CHARCONV_JAMFILE, {'charconv.cpp': CHARCONV_SOURCE})
    add_locales(root)
    for library in ('urls', 'numbers', 'locales'):
        result = harness.run_b2(root, f'-sBOOST_SOURCE={sources}', f'libs/{library}/test')
        harness.expect(result, False, "holds Boost 1.91.0's sources", 'is 1.92.0')


def test_a_tree_without_the_library_s_sources_is_refused(root: Path) -> None:
    sources = fake_sources(root / 'no url', 109200, with_url=False)
    add_urls(root)
    harness.add_library(root, 'numbers', CHARCONV_JAMFILE, {'charconv.cpp': CHARCONV_SOURCE})
    add_locales(root)
    for library, message in (('urls', 'libs/url/src holds no .cpp file'),
                             ('numbers', 'libs/charconv/src holds no .cpp file'),
                             ('locales', 'libs/locale/src holds no Boost.Locale sources')):
        result = harness.run_b2(root, f'-sBOOST_SOURCE={sources}', f'libs/{library}/test')
        harness.expect(result, False, message, '/webcpp//boost_' + message.split('/')[1])
    # Boost.Locale's tree must hold every source a target may compile, a backend's that this one
    # does not compile too: a partial tree stops by name, not at a compile or a link elsewhere.
    with_sources_of(sources, 'charconv', 'locale')
    (sources / 'libs/locale/src/win32/lcid.cpp').unlink()
    result = harness.run_b2(root, f'-sBOOST_SOURCE={sources}', 'libs/locales/test')
    harness.expect(result, False, 'libs/locale/src holds no Boost.Locale sources, or only some')


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
                   f'BOOST_SOURCE (user-config.jam or the environment), {missing}, holds no '
                   'boost/version.hpp')


def test_sources_named_by_the_environment(root: Path) -> None:
    # b2 reads the environment's variables as it reads user-config.jam's, so an environment's
    # BOOST_SOURCE is honoured, and named as coming from either. b2 splits its value at each
    # space, as it splits every variable of the environment but a *PATH, so the tree is given
    # through a path that holds spaces.
    harness.without_boost_source(root)
    spaced = root / 'the  boost sources'
    spaced.symlink_to(harness.boost_source())
    add_urls(root)
    result = harness.run_b2(root, 'libs/urls/test', env_extra={'BOOST_SOURCE': str(spaced)})
    harness.expect(result, True)
    assert passed(result) == {'urls'}, (passed(result), result.stdout[-4000:])
    missing = root / 'no sources'
    harness.expect(harness.run_b2(root, 'libs/urls/test', env_extra={'BOOST_SOURCE': str(missing)}),
                   False, f'BOOST_SOURCE (user-config.jam or the environment), {missing}, holds '
                   'no boost/version.hpp')


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
    # b2 also takes -s and the assignment as two words.
    result = harness.run_b2(root, '-s', f'BOOST_SOURCE={harness.boost_source()}', 'libs/urls/test')
    harness.expect(result, True)
    missing = root / 'no sources'
    for words in ((f'-sBOOST_SOURCE={missing}',), ('-s', f'BOOST_SOURCE={missing}')):
        harness.expect(harness.run_b2(root, *words, 'libs/urls/test'), False,
                       f'-sBOOST_SOURCE={missing} holds no boost/version.hpp')


# The include directory of a user-config.jam's `using boost`, and its first native toolset's line.
USING_BOOST_INCLUDE = re.compile(r'^\s*using\s+boost\b[^;]*<include>"?([^";\s]+)"?', re.MULTILINE)
NATIVE_USING = re.compile(r'^\s*using\s+(?:clang|gcc)\b(?![^;]*wasip)[^;]*;', re.MULTILINE)


def test_boost_on_the_default_include_path_is_refused_naming_the_fix(root: Path) -> None:
    # Boost found on the compiler's own include path, with no `using boost`: the build cannot read
    # the configured Boost's version, so it asks for the line that names its directory.
    text = harness.user_config(root).read_text()
    include = USING_BOOST_INCLUDE.search(text)
    native = NATIVE_USING.search(text)
    assert include and native, text
    words = native.group(0).rstrip(';').rstrip()
    words += ' :' * (3 - words.count(':'))
    flagged = f'{words} <cxxflags>"-isystem{include.group(1)}" ;'
    harness.configure(root, harness.USING_BOOST.sub('', text.replace(native.group(0), flagged)))
    add_urls(root)
    harness.expect(harness.run_b2(root, 'libs/urls/test'), False,
                   "the configured Boost's version is unknown",
                   'using boost : 1.92 : <include>')
    harness.expect(harness.run_b2(root, 'libs/demo/test//pass'), True)


CHARCONV_JAMFILE = ('import webcpp ;\n'
                    '\n'
                    'webcpp.targets native wasip2 wasip3 emscripten ;\n'
                    '\n'
                    'webcpp.run charconv : charconv.cpp : <library>/webcpp//boost_charconv ;\n')

CHARCONV_SOURCE = r'''#include <boost/charconv.hpp>

#include <cstdio>
#include <cstring>
#include <system_error>

int main() {
    double value = 0;
    char const text[] = "1234567.5";
    auto const parsed = boost::charconv::from_chars(text, text + std::strlen(text), value);
    char buffer[64];
    auto const written = boost::charconv::to_chars(buffer, buffer + sizeof buffer - 1, value);
    *written.ptr = '\0';
    std::printf("%s %d\n", buffer, parsed.ec == std::errc());
    return parsed.ec == std::errc() && std::strcmp(buffer, "1234567.5") == 0 ? 0 : 1;
}
'''

# translates reads its catalog on every target, from the directory webcpp.data gives it.
LOCALE_JAMFILE = r'''import regex ;
import webcpp ;

webcpp.targets native wasip2 wasip3 emscripten ;

path-constant CATALOGS : catalogs ;
local catalogs = [ regex.replace $(CATALOGS) "\\\\" "/" ] ;
webcpp.run converts : converts.cpp : <library>/webcpp//boost_locale ;
webcpp.run translates : translates.cpp
  : <library>/webcpp//boost_locale <define>"\"WEBCPP_TEST_CATALOGS=\\\"$(catalogs)\\\"\""
    [ webcpp.data $(CATALOGS) ] ;
'''

CONVERTS_SOURCE = r'''#include <boost/locale.hpp>

#include <iostream>
#include <string>

int main() {
    for (std::string const& backend :
         boost::locale::localization_backend_manager::global().get_all_backends()) {
        std::cout << backend << ' ';
    }
    boost::locale::generator generator;
    std::locale const locale = generator("en_US.UTF-8");
    bool const utf8 = std::use_facet<boost::locale::info>(locale).utf8();
    std::string const converted = boost::locale::conv::to_utf<char>("caf\xe9", "ISO-8859-1");
    std::cout << '|' << converted << '|' << utf8 << '\n';
    return converted == "caf\xc3\xa9" && utf8 ? 0 : 1;
}
'''

TRANSLATES_SOURCE = r'''#include <boost/locale.hpp>

#include <iostream>
#include <string>

int main() {
    boost::locale::generator generator;
    generator.add_messages_path(WEBCPP_TEST_CATALOGS);
    generator.add_messages_domain("probe");
    std::locale const locale = generator("pt_BR.UTF-8");
    std::string const translated = boost::locale::translate("Hello World").str(locale);
    std::string const converted = boost::locale::conv::to_utf<char>("caf\xe9", "ISO-8859-1");
    std::cout << translated << '|' << converted << '\n';
    return translated == "Ol\xc3\xa1 Mundo" && converted == "caf\xc3\xa9" ? 0 : 1;
}
'''


def mo(messages: dict[str, str]) -> bytes:
    """A GNU message catalog holding messages, msgid to msgstr, as msgfmt writes one, without its
    optional hash table."""
    keys = sorted(messages)
    texts = [key.encode() for key in keys] + [messages[key].encode() for key in keys]
    count = len(keys)
    offset = 28 + 16 * count
    table = []
    for text in texts:
        table += [len(text), offset]
        offset += len(text) + 1
    return (struct.pack('<7I', 0x950412DE, 0, count, 28, 28 + 8 * count, 0, 0)
            + struct.pack(f'<{4 * count}I', *table) + b''.join(text + b'\0' for text in texts))


def output_of(root: Path, name: str) -> str:
    """The text of the one file named name that b2 wrote under the scratch superproject's bin/."""
    found = sorted((root / 'bin').rglob(name))
    assert len(found) == 1, (name, found)
    return found[0].read_text()


def add_locales(root: Path) -> None:
    """Adds the library locales, whose tests convert, and translate from a catalog of their own."""
    harness.add_library(root, 'locales', LOCALE_JAMFILE,
                        {'converts.cpp': CONVERTS_SOURCE, 'translates.cpp': TRANSLATES_SOURCE})
    catalog = root / 'libs/locales/test/catalogs/pt_BR/LC_MESSAGES/probe.mo'
    catalog.parent.mkdir(parents=True)
    catalog.write_bytes(mo({'': 'Content-Type: text/plain; charset=UTF-8\n',
                            'Hello World': 'Olá Mundo'}))


def test_boost_charconv_links_on_every_target(root: Path) -> None:
    harness.link_emsdk(root)
    harness.add_library(root, 'numbers', CHARCONV_JAMFILE, {'charconv.cpp': CHARCONV_SOURCE})
    gcc = harness.gcc_request(root)
    for request in ((), WASIP2, WASIP3, EMSCRIPTEN, ('exception-handling=off',),
                    (*WASIP2, 'exception-handling=off'), *((gcc,) if gcc else ())):
        result = harness.run_b2(root, '-a', '-d+2', *request, 'libs/numbers/test')
        harness.expect(result, True)
        assert passed(result) == {'charconv'}, (request, passed(result), result.stdout[-4000:])
        assert output_of(root, 'charconv.output').startswith('1234567.5 1\n'), request
        assert '-lboost_charconv' not in result.stdout, (request, result.stdout[-4000:])
        shutil.rmtree(root / 'bin')


def test_boost_locale_on_every_target(root: Path) -> None:
    harness.link_emsdk(root)
    add_locales(root)
    gcc = harness.gcc_request(root)
    for request in ((), WASIP2, WASIP3, EMSCRIPTEN, *((gcc,) if gcc else ())):
        result = harness.run_b2(root, '-a', '-d+2', *request, 'libs/locales/test')
        harness.expect(result, True)
        assert passed(result) == {'converts', 'translates'}, (request, passed(result),
                                                              result.stdout[-4000:])
        assert output_of(root, 'converts.output').startswith('posix std |café|1\n'), request
        assert output_of(root, 'translates.output').startswith('Olá Mundo|café\n'), request
        assert '-lboost_locale' not in result.stdout, (request, result.stdout[-4000:])
        shutil.rmtree(root / 'bin')


CODEPAGES_JAMFILE = ('import webcpp ;\n'
                     '\n'
                     'webcpp.targets native wasip2 wasip3 emscripten ;\n'
                     '\n'
                     'webcpp.run codepages : codepages.cpp : <library>/webcpp//boost_locale ;\n')

# Shift_JIS, a multibyte charset, which each platform's iconv must know (macOS's libiconv, the
# tables of wasi-libc's and of Emscripten's musl). converts proves that iconv is there, with
# ISO-8859-1, which Boost.Locale 1.92 too converts only through iconv (or ICU); this one, that a
# charset beyond Latin-1 converts.
CODEPAGES_SOURCE = r'''#include <boost/locale.hpp>

#include <iostream>
#include <string>

int main() {
    std::string const converted = boost::locale::conv::to_utf<char>("\x82\xa0", "Shift_JIS");
    std::cout << converted << '\n';
    return converted == "\xe3\x81\x82" ? 0 : 1;
}
'''


def test_boost_locale_converts_through_iconv(root: Path) -> None:
    harness.link_emsdk(root)
    harness.add_library(root, 'codepages', CODEPAGES_JAMFILE, {'codepages.cpp': CODEPAGES_SOURCE})
    for request in ((), WASIP2, WASIP3, EMSCRIPTEN):
        result = harness.run_b2(root, '-a', '-d+2', *request, 'libs/codepages/test')
        harness.expect(result, True)
        assert passed(result) == {'codepages'}, (request, passed(result), result.stdout[-4000:])
        assert output_of(root, 'codepages.output').startswith('\u3042\n'), request
        # The usage requirements reach the program: Boost.Locale's and, through it,
        # Boost.Charconv's macros of a static library, which keep MSVC's auto-link off.
        compiles = [line for line in result.stdout.splitlines()
                    if 'codepages.cpp' in line and ' -c ' in line]
        assert compiles, (request, result.stdout[-4000:])
        for define in ('-DBOOST_LOCALE_NO_LIB=1', '-DBOOST_CHARCONV_NO_LIB=1'):
            assert all(define in line for line in compiles), (request, define, compiles)
        shutil.rmtree(root / 'bin')


def compiled_locale_sources(output: str) -> dict[str, str]:
    """Each source of Boost.Locale that a b2 -d+2 output compiles, by its path under
    libs/locale/src, with its command."""
    found = re.findall(r'^.* -c .*libs/locale/src/([\w/]+\.cpp)".*$', output, re.MULTILINE)
    commands = [line for line in output.splitlines()
                if ' -c ' in line and 'libs/locale/src/' in line]
    return {source: next(line for line in commands if f'libs/locale/src/{source}"' in line)
            for source in found}


def test_boost_locale_on_windows_is_boost_s_configuration(root: Path) -> None:
    # No Windows machine measures it yet: a dry run for target-os=windows on this host holds the
    # branch to AGENTS.md's table until the CI's MSVC lanes build it, the winapi and std backends,
    # without iconv.
    add_locales(root)
    result = harness.run_b2(root, '-a', '-n', '-d+2', 'target-os=windows',
                            'libs/locales/test//converts')
    harness.expect(result, True)
    compiled = compiled_locale_sources(result.stdout)
    backends = {source.split('/')[0] for source in compiled}
    assert backends == {'encoding', 'shared', 'util', 'std', 'win32'}, sorted(compiled)
    assert {source for source in compiled if source.startswith('win32/')} == {
        'win32/collate.cpp', 'win32/converter.cpp', 'win32/numeric.cpp', 'win32/win_backend.cpp',
        'win32/lcid.cpp'}, sorted(compiled)
    for source, command in compiled.items():
        assert '-DBOOST_LOCALE_NO_POSIX_BACKEND=1' in command, (source, command)
        assert 'BOOST_LOCALE_WITH_ICONV' not in command, (source, command)
        assert 'BOOST_LOCALE_NO_WINAPI_BACKEND' not in command, (source, command)
    assert '-liconv' not in result.stdout, result.stdout[-4000:]


def test_boost_locale_on_emscripten_is_threaded_alone(root: Path) -> None:
    # Single-threaded emscripten has pthreads' functions as stubs, and no _POSIX_THREADS, so
    # Boost.Config turns threads off, which Boost.Thread's mutex refuses: Boost.Locale's sources
    # alone are told that pthreads are there, never a program, and nothing is built with -pthread,
    # which would make a program's memory shared.
    harness.link_emsdk(root)
    add_locales(root)
    result = harness.run_b2(root, '-a', '-n', '-d+2', *EMSCRIPTEN, 'libs/locales/test//converts')
    harness.expect(result, True)
    compiled = compiled_locale_sources(result.stdout)
    assert {source.split('/')[0] for source in compiled} == {
        'encoding', 'shared', 'util', 'std', 'posix'}, sorted(compiled)
    for source, command in compiled.items():
        assert '-DBOOST_HAS_PTHREADS' in command, (source, command)
    others = [line for line in result.stdout.splitlines()
              if ' -c ' in line and 'libs/locale/src/' not in line]
    assert any('converts.cpp' in line for line in others), result.stdout[-4000:]
    assert any('libs/charconv/src/' in line for line in others), result.stdout[-4000:]
    for line in others:
        assert 'BOOST_HAS_PTHREADS' not in line, line
    assert '-pthread' not in result.stdout, result.stdout[-4000:]


# Every public header of Boost.Locale, and a line that shows whether Boost.Config ended with
# threads.
EVERY_HEADER_JAMFILE = ('preprocessed plain : every.cpp ;\n'
                        'preprocessed threaded : every.cpp : <define>BOOST_HAS_PTHREADS ;\n')
THREADS_SEEN = 'int webcpp_test_boost_has_threads;\n'


def test_boost_locale_s_headers_ignore_its_threading_macro(root: Path) -> None:
    # What makes defining BOOST_HAS_PTHREADS for Boost.Locale's sources alone sound on emscripten:
    # no type or inline function of its public headers, nor of what they include, depends on it,
    # so a program built without it sees what the library was built with. Every header of the
    # configured Boost's boost/locale/ preprocesses to the same text with the macro and without,
    # Boost.Config's own BOOST_HAS_THREADS aside; a Boost whose headers come to depend on it fails
    # here, before an ODR mismatch.
    text = harness.user_config(root).read_text()
    include = USING_BOOST_INCLUDE.search(text)
    assert include, text
    headers = sorted(path.relative_to(include.group(1)).as_posix()
                     for path in Path(include.group(1), 'boost/locale').rglob('*.hpp'))
    assert len(headers) > 30, headers
    source = ''.join(f'#include <{header}>\n' for header in ['boost/locale.hpp', *headers])
    source += '#ifdef BOOST_HAS_THREADS\n' + THREADS_SEEN + '#endif\n'
    harness.link_emsdk(root)
    harness.add_library(root, 'headers', EVERY_HEADER_JAMFILE, {'every.cpp': source})
    harness.expect(harness.run_b2(root, '-a', *EMSCRIPTEN, 'libs/headers/test'), True)
    plain, threaded = (code_of(output_of(root, f'{name}.ii')) for name in ('plain', 'threaded'))
    seen = THREADS_SEEN.strip()
    assert seen not in plain and seen in threaded, (plain[-3:], threaded[-3:])
    assert [line for line in threaded if line != seen] == plain


def code_of(preprocessed: str) -> list[str]:
    """The lines of a preprocessed translation unit that hold code: neither empty nor the
    preprocessor's line markers, which only place it."""
    return [line for line in preprocessed.splitlines()
            if line.strip() and not re.match(r'#\s*\d+ ', line)]


def test_boost_locale_is_refused_without_exceptions(root: Path) -> None:
    add_locales(root)
    harness.expect(harness.run_b2(root, 'exception-handling=off', 'libs/locales/test'), False,
                   '/webcpp//boost_locale needs exceptions',
                   'declares <exception-handling>on in its own requirements')
    # The fix the refusal names: programs that declare it build Boost.Locale with exceptions in a
    # build without them, as the lint's twins are.
    jamfile = root / 'libs/locales/test/Jamfile'
    jamfile.write_text(jamfile.read_text().replace(
        '<library>/webcpp//boost_locale', '<library>/webcpp//boost_locale <exception-handling>on'))
    for request in ((), WASIP2):
        result = harness.run_b2(root, '-a', *request, 'exception-handling=off', 'libs/locales/test')
        harness.expect(result, True)
        assert passed(result) == {'converts', 'translates'}, (request, passed(result),
                                                              result.stdout[-4000:])


CASES = [
    test_boost_url_links_on_every_target,
    test_boost_charconv_links_on_every_target,
    test_boost_locale_on_every_target,
    test_boost_locale_converts_through_iconv,
    test_boost_locale_on_windows_is_boost_s_configuration,
    test_boost_locale_on_emscripten_is_threaded_alone,
    test_boost_locale_s_headers_ignore_its_threading_macro,
    test_boost_locale_is_refused_without_exceptions,
    test_without_the_library_a_program_does_not_link,
    test_missing_sources_are_refused_naming_the_fix,
    test_sources_of_another_version_are_refused,
    test_a_tree_without_the_library_s_sources_is_refused,
    test_sources_named_by_user_config,
    test_sources_named_by_the_environment,
    test_the_command_line_wins,
    test_boost_on_the_default_include_path_is_refused_naming_the_fix,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('boost_libraries_test', CASES, sys.argv[1:]))
