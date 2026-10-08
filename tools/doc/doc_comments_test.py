#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks doc_comments.py: a public template without a @tparam for each of its parameters fails,
naming the template, the parameter, the file and the line; so does a detail symbol without a
brief; and a documented library passes.

Each case writes the headers of a library demo under a scratch directory whose path holds a space,
and runs doc_comments.py on a translation unit that includes them, with the clang++ of $CLANG, or
of PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECK = HERE / 'doc_comments.py'

# A library whose every symbol is documented as webcpp requires: each kind of template with a
# @tparam for each named parameter, and each detail symbol with a brief. A detail template needs
# no @tparam, an undocumented public function is MrDocs's to report, and an out-of-line
# definition may rename the parameters its declaration documents.
DOCUMENTED = """\
#include <concepts>
#include <cstddef>

namespace webcpp::demo {

namespace detail {

/** Adds two values. */
template <class T, class U>
constexpr auto sum(T left, U right) { return left + right; }

/** The storage of a box. */
struct storage {
    /** The bytes held. */
    std::size_t size;
};

/** The kinds of storage. */
enum class kind {
    small, ///< One value held in place.
    /** Nothing held. */
    empty,
};

/** The type a box holds its value as. */
template <class T>
using held = T;

/** Whether a type is small. */
template <class T>
constexpr bool is_small = sizeof(T) <= 8;

namespace inner::detail {

/** A helper two namespaces down. */
inline int deep() { return 1; }

}  // namespace inner::detail

}  // namespace detail

/** Returns a value added to itself.

    @tparam T An arithmetic type.
    @param value The value.
    @return Twice the value.
*/
template <class T>
constexpr T twice(T value) { return detail::sum(value, value); }

/** Holds a value.

    @tparam T The value's type.
    @tparam N How many it holds.
*/
template <class T, int N = 1>
class box {
public:
    /** Converts the value.

        @tparam U The type to convert to.
        @return The value as a U.
    */
    template <class U>
    U as() const;

    /** Compares two boxes.

        @tparam V The other box's type.
        @param left A box.
        @param right Another box.
        @return Whether they hold the same value.
    */
    template <class V>
    friend bool operator==(box const& left, box<V> const& right) { return true; }

    /** The value. */
    T value;

private:
    template <class W>
    void hidden(W);
};

template <class T, int N>
template <class X>
X box<T, N>::as() const { return X(value); }

/** Holds a pointer.

    @tparam T The pointee's type.
*/
template <class T>
class box<T*, 1> {
public:
    /** The pointer. */
    T* value;
};

/** A box of one value.

    @tparam T The value's type.
*/
template <class T>
using single = box<T, 1>;

/** Whether a type is a box.

    @tparam T The type.
*/
template <class T>
constexpr bool is_box = false;

/** Something that can be boxed.

    @tparam T The type.
*/
template <class T>
concept boxable = std::copyable<T>;

/** Boxes a value of any type, its parameter named by the compiler.

    @param value The value.
    @return The value.
*/
inline auto any(auto value) { return value; }

/** Takes an unnamed template parameter, which nothing can name.

    @return Nothing.
*/
template <class>
void unnamed() {}

int undocumented();

/** Uses the detail templates, so that their instantiations are in the dump. */
inline int used() { return detail::sum(1, 2) + int(detail::is_small<int>) + twice(1); }

}  // namespace webcpp::demo
"""

# A header of another library, which the check does not read.
OTHER = """\
namespace webcpp::other {

template <class T>
void elsewhere(T) {}

}  // namespace webcpp::other
"""


class Library:
    """A scratch library demo: its headers under include/webcpp/demo/ and a translation unit
    that includes them."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.include = root / 'include'
        (self.include / 'webcpp/demo').mkdir(parents=True)
        (self.include / 'webcpp/other').mkdir(parents=True)
        self.headers: list[str] = []

    def header(self, name: str, text: str) -> Path:
        """Writes the header webcpp/demo/<name> and returns its path."""
        path = self.include / 'webcpp/demo' / name
        path.write_text(text)
        if name not in self.headers:
            self.headers.append(name)
        return path

    def check(self) -> subprocess.CompletedProcess:
        """Runs doc_comments.py on the library, and returns what it printed in stdout."""
        (self.include / 'webcpp/other/other.hpp').write_text(OTHER)
        source = self.root / 'all.cpp'
        source.write_text('#include <webcpp/other/other.hpp>\n' + ''.join(
            f'#include <webcpp/demo/{name}>\n' for name in self.headers))
        command = [sys.executable, str(CHECK), '--clang', clang(), '--library', 'demo',
                   '--include', str(self.include), '--', '-std=c++20', f'-I{self.include}',
                   str(source)]
        return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, check=False)


def clang() -> str:
    """The clang++ the check runs: $CLANG, else the one on PATH."""
    found = os.environ.get('CLANG') or shutil.which('clang++')
    if not found:
        raise RuntimeError('no clang++ on PATH, and CLANG is not set')
    return found


def line_of(path: Path, text: str) -> str:
    """<path>:<line>:, the line of path where text is, which must be there once."""
    lines = [number for number, line in enumerate(path.read_text().splitlines(), 1)
             if text in line]
    assert len(lines) == 1, (path, text, lines)
    return f'{path}:{lines[0]}:'


def expect(result: subprocess.CompletedProcess, status: int, *texts: str) -> None:
    assert result.returncode == status, (status, result.returncode, result.stdout)
    for text in texts:
        assert text in result.stdout, (text, result.stdout)


def findings(result: subprocess.CompletedProcess) -> list[str]:
    """The lines of the check's output that report a fault, path:line: message."""
    return [line for line in result.stdout.splitlines() if ': ' in line and '.hpp:' in line]


def test_documented_library_passes(library: Library) -> None:
    library.header('box.hpp', DOCUMENTED)
    result = library.check()
    expect(result, 0)
    assert result.stdout == '', result.stdout


def test_missing_tparam_names_the_template(library: Library) -> None:
    # A function template, the first parameter of a class template, and a member template.
    path = library.header('box.hpp', DOCUMENTED
                          .replace('    @tparam T An arithmetic type.\n', '')
                          .replace('    @tparam T The value\'s type.\n    @tparam N',
                                   '    @tparam N')
                          .replace('        @tparam U The type to convert to.\n', ''))
    result = library.check()
    expect(result, 1,
           f'{line_of(path, "constexpr T twice(T value)")} webcpp::demo::twice: the template '
           'parameter T has no @tparam',
           f'{line_of(path, "class box {")} webcpp::demo::box: the template parameter T has no '
           '@tparam',
           f'{line_of(path, "    U as() const;")} webcpp::demo::box::as: the template parameter U '
           'has no @tparam')
    # N is documented, and the out-of-line definition, whose parameter is X, is the same
    # function as the declaration.
    assert 'parameter N' not in result.stdout and 'parameter X' not in result.stdout, (
        result.stdout)
    assert len(findings(result)) == 3, result.stdout


def test_missing_tparam_in_every_kind_of_template(library: Library) -> None:
    path = library.header('box.hpp', DOCUMENTED
                          .replace('        @tparam V The other box\'s type.\n', '')
                          .replace('    @tparam T The pointee\'s type.\n', '')
                          .replace('    @tparam T The value\'s type.\n*/\ntemplate <class T>\n'
                                   'using', '*/\ntemplate <class T>\nusing')
                          .replace('    @tparam T The type.\n*/\ntemplate <class T>\n'
                                   'constexpr bool', '*/\ntemplate <class T>\nconstexpr bool')
                          .replace('    @tparam T The type.\n*/\ntemplate <class T>\nconcept',
                                   '*/\ntemplate <class T>\nconcept'))
    result = library.check()
    expect(result, 1,
           f'{line_of(path, "friend bool operator==")} webcpp::demo::box::operator==: the '
           'template parameter V has no @tparam',
           f'{line_of(path, "class box<T*, 1> {")} webcpp::demo::box, a partial specialization: '
           'the template parameter T has no @tparam',
           f'{line_of(path, "using single")} webcpp::demo::single: the template parameter T',
           f'{line_of(path, "constexpr bool is_box")} webcpp::demo::is_box: the template '
           'parameter T',
           f'{line_of(path, "concept boxable")} webcpp::demo::boxable: the template parameter T')
    assert len(findings(result)) == 5, result.stdout


def test_tparam_naming_no_parameter(library: Library) -> None:
    path = library.header('box.hpp', DOCUMENTED.replace('    @tparam T An arithmetic type.\n',
                                                        '    @tparam Q An arithmetic type.\n'))
    result = library.check()
    expect(result, 1,
           f'{line_of(path, "constexpr T twice(T value)")} webcpp::demo::twice: the template '
           'parameter T has no @tparam',
           f'{line_of(path, "constexpr T twice(T value)")} webcpp::demo::twice: @tparam Q names '
           'no template parameter')


def test_detail_symbol_without_brief(library: Library) -> None:
    path = library.header('box.hpp', DOCUMENTED
                          .replace('/** Adds two values. */\n', '')
                          .replace('    /** The bytes held. */\n', '')
                          .replace('    small, ///< One value held in place.\n', '    small,\n')
                          .replace('/** A helper two namespaces down. */\n', '')
                          .replace('/** The type a box holds its value as. */\n',
                                   '/** @tparam T The type. */\n'))
    result = library.check()
    expect(result, 1,
           f'{line_of(path, "constexpr auto sum(")} webcpp::demo::detail::sum: a detail symbol '
           'needs a brief',
           f'{line_of(path, "std::size_t size;")} webcpp::demo::detail::storage::size: a detail '
           'symbol needs a brief',
           f'{line_of(path, "    small,")} webcpp::demo::detail::kind::small: a detail symbol',
           f'{line_of(path, "inline int deep()")} webcpp::demo::detail::inner::detail::deep: a '
           'detail symbol',
           f'{line_of(path, "using held = T;")} webcpp::demo::detail::held: a detail symbol')
    # Each once: the instantiations of sum and is_small that used() makes are not declarations
    # of the library's.
    assert len(findings(result)) == 5, result.stdout


# Declarators that clang gives one Doc Comment: it attaches a comment to each declaration that
# follows it up to a ;, a {, a }, a # or an @, so a comma does not stop it.
SHARED = """\
namespace webcpp::demo {

/** The colours. */
enum class colour {
    /** Red. */
    red, green,
};

/** A point. */
struct point {
    /** The x. */
    int x, y;
};

/** The lowest. */
inline constexpr int low = 0, high = 9;

namespace detail {

/** The detail colours. */
enum class shade {
    /** Dark. */
    dark, light,
};

/** A detail point. */
struct spot {
    /** The a. */
    int a, b;
};

/** The first. */
inline constexpr int first = 0, second = 1;

}  // namespace detail

}  // namespace webcpp::demo
"""


def test_declarators_have_comments_of_their_own(library: Library) -> None:
    path = library.header('shared.hpp', SHARED)
    result = library.check()
    expect(result, 1, *(
        f'{line_of(path, line)} webcpp::demo::{name}: has no Doc Comment of its own; clang gives '
        f'it the one of webcpp::demo::{first}'
        for line, name, first in (('    red, green,', 'colour::green', 'colour::red'),
                                  ('    int x, y;', 'point::y', 'point::x'),
                                  ('int low = 0, high = 9;', 'high', 'low'),
                                  ('    dark, light,', 'detail::shade::light',
                                   'detail::shade::dark'),
                                  ('    int a, b;', 'detail::spot::b', 'detail::spot::a'),
                                  ('int first = 0, second = 1;', 'detail::second',
                                   'detail::first'))))
    # Each once, and only those: the first of each takes the comment as its own.
    assert len(findings(result)) == 6, result.stdout


def test_brief_is_one_sentence(library: Library) -> None:
    path = library.header('box.hpp', DOCUMENTED.replace(
        '/** Returns a value added to itself.\n',
        '/** Returns a value added to itself. It is twice the value!\n'))
    result = library.check()
    expect(result, 1,
           f'{line_of(path, "constexpr T twice(T value)")} webcpp::demo::twice: the brief, the '
           'first paragraph of its Doc Comment, holds 2 sentences')
    assert len(findings(result)) == 1, result.stdout
    # Abbreviations, numbers and code spans end no sentence, and neither does a detail symbol's
    # brief, which only needs to be there.
    library.header('box.hpp', DOCUMENTED.replace(
        '/** Returns a value added to itself.\n',
        '/** Returns a value added to itself, e.g. 2 for 1, i.e. the sum, as in version 1.5,\n'
        '    with `x. y` and \\c a.b too, etc. and so on.\n').replace(
        '/** Adds two values. */', '/** Adds two values. Both are added. */'))
    expect(library.check(), 0)


def test_brief_ending_on_an_inline_command_is_one_sentence(library: Library) -> None:
    # The sentence's end is the inline command's argument's, which clang keeps in the argument:
    # `@ref detail::sum.` ends the first sentence, and `\c sum.` ends one the same way.
    for opening in ('/** Returns a value added to itself, as @ref detail::sum.',
                    '/** Returns a value added to itself, as \\c sum.',
                    '/** @brief Returns a value added to itself, as @ref detail::sum.'):
        path = library.header('box.hpp', DOCUMENTED.replace(
            '/** Returns a value added to itself.\n', f'{opening} It is twice the value.\n'))
        result = library.check()
        expect(result, 1,
               f'{line_of(path, "constexpr T twice(T value)")} webcpp::demo::twice: the brief, '
               'the first paragraph of its Doc Comment, holds 2 sentences')
        assert len(findings(result)) == 1, result.stdout
    # One that ends the brief is its one sentence, and one inside a sentence ends none.
    library.header('box.hpp', DOCUMENTED.replace(
        '/** Returns a value added to itself.\n',
        '/** Returns @ref detail::sum of a value and itself, as @ref detail::sum.\n'))
    expect(library.check(), 0)


def test_lines_across_headers(library: Library) -> None:
    # clang's dump writes a location's file and line only when they change: a finding in a second
    # header, after declarations of a first, still names its own file and line.
    library.header('box.hpp', DOCUMENTED)
    second = library.header('second.hpp', '\n\nnamespace webcpp::demo {\n\n'
                                          '/** Late. */\ntemplate <class T>\nvoid late(T);\n\n'
                                          '}  // namespace webcpp::demo\n')
    result = library.check()
    expect(result, 1, f'{line_of(second, "void late(T);")} webcpp::demo::late: the template '
                      'parameter T has no @tparam')
    assert len(findings(result)) == 1, result.stdout


def test_clang_failure_is_reported(library: Library) -> None:
    library.header('box.hpp', 'namespace webcpp::demo { int broken( }\n')
    result = library.check()
    expect(result, 2, 'clang++ could not read the headers', 'error:')


def test_library_namespace_missing(library: Library) -> None:
    library.header('box.hpp', 'namespace webcpp::other { inline int misplaced() { return 0; } }\n')
    result = library.check()
    expect(result, 2, 'no declaration of webcpp::demo')


CASES: list[Callable[[Library], None]] = [
    test_documented_library_passes,
    test_missing_tparam_names_the_template,
    test_missing_tparam_in_every_kind_of_template,
    test_tparam_naming_no_parameter,
    test_detail_symbol_without_brief,
    test_declarators_have_comments_of_their_own,
    test_brief_is_one_sentence,
    test_brief_ending_on_an_inline_command_is_one_sentence,
    test_lines_across_headers,
    test_clang_failure_is_reported,
    test_library_namespace_missing,
]


def main(argv: list[str]) -> int:
    unknown = set(argv) - {case.__name__ for case in CASES}
    if unknown:
        print(f'doc_comments_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    for case in CASES:
        if argv and case.__name__ not in argv:
            continue
        with tempfile.TemporaryDirectory(prefix='doc comments ') as scratch:
            case(Library(Path(scratch)))
        print(f'{case.__name__}: ok')
    print('doc_comments_test: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
