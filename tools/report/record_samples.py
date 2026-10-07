#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Records the samples of tools/report/samples/, each the file one lane's b2 run wrote.

Usage: record_samples.py [NAME ...]

A sample is what `b2 -a --dump-tests --out-xml=FILE` writes, run with the arguments of a lane
(the Jamroot's lane command) in a scratch superproject that holds the fixture library demo and
whatever SAMPLES plants beside it. It is then trimmed of what report.py never reads, and of what
would only describe the machine that recorded it: the <os> element (uname, which names the
host), every <properties> and <sources> element, and the actions b2 runs for itself, which have
no <name>, when they succeeded (creating a directory, for one). report_test.py records every
sample afresh, untrimmed, and checks that the report reads it as it reads the committed one.

b2 records the compilers' paths, which user-config.jam can place under the home directory: the
scratch superproject reaches .local/ through a link outside it, and a sample that still names the
home directory is not written. With names, only those samples are recorded.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# The harness lives beside the other tests of the build, in tools/test.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'test'))

import harness

SAMPLES = Path(__file__).resolve().parent / 'samples'

NATIVE = ('toolset=clang',)
WASIP2 = ('toolset=clang-wasip2', 'testing.launcher=wasmtime')

PLANTED_TESTS = """import webcpp ;

webcpp.run fails_to_run : fails_to_run.cpp ;
webcpp.run fails_to_compile : fails_to_compile.cpp ;
webcpp.run fails_to_link : fails_to_link.cpp ;
webcpp.compile-fail compiles : compiles.cpp ;
webcpp.run-fail exits_with_zero : exits_with_zero.cpp ;
"""

PLANTED_TEST_SOURCES = {
    'fails_to_run.cpp': ('#include <boost/core/lightweight_test.hpp>\n'
                         '\n'
                         'int main() {\n'
                         '    BOOST_TEST_EQ(1 + 1, 3);\n'
                         '    return boost::report_errors();\n'
                         '}\n'),
    'fails_to_compile.cpp': 'int main() { return undeclared; }\n',
    'fails_to_link.cpp': 'int missing();\n\nint main() { return missing(); }\n',
    'compiles.cpp': 'int main() { return 0; }\n',
    'exits_with_zero.cpp': 'int main() { return 0; }\n',
}

PLANTED_EXAMPLES = """import webcpp ;

webcpp.example prints_otherwise.cpp ;
webcpp.example does_not_compile.cpp ;
"""

PLANTED_EXAMPLE_SOURCES = {
    'prints_otherwise.cpp': '#include <cstdio>\n\nint main() { std::puts("printed"); }\n',
    'prints_otherwise.expected': 'expected\n',
    'does_not_compile.cpp': 'int main() { return undeclared; }\n',
    'does_not_compile.expected': 'expected\n',
}

# A failed comparison of text that CDATA cannot hold as it is: a ]]>, markup, and a byte that is
# not UTF-8, as a parser's test could print.
ODD_SOURCE = r"""#include <boost/core/lightweight_test.hpp>

#include <string>

int main() {
    BOOST_TEST_EQ(std::string("<b>]]>&amp;</b>"), std::string("\xff"));
    return boost::report_errors();
}
"""


def plant_failures(root: Path) -> None:
    """Adds the library planted, whose every test and example fails in its own way."""
    harness.add_library(root, 'planted', PLANTED_TESTS, PLANTED_TEST_SOURCES)
    examples = root / 'libs/planted/example'
    examples.mkdir()
    (examples / 'Jamfile').write_text(PLANTED_EXAMPLES)
    for name, text in PLANTED_EXAMPLE_SOURCES.items():
        (examples / name).write_text(text)


def plant_native_only(root: Path) -> None:
    """Adds the library nativeonly, which declares native only."""
    harness.add_library(root, 'nativeonly',
                        'import webcpp ;\n'
                        '\n'
                        'webcpp.targets native ;\n'
                        '\n'
                        'webcpp.run works : works.cpp ;\n',
                        {'works.cpp': 'int main() { return 0; }\n'})


def plant_broken_handler(root: Path) -> None:
    """Breaks tools/throw_exception.cpp, which every program built without exceptions links."""
    handler = root / 'tools/throw_exception.cpp'
    handler.write_text(handler.read_text() + '#error "planted: the handler does not compile"\n')


def plant_odd_output(root: Path) -> None:
    """Adds the library odd, whose test prints what CDATA cannot hold."""
    harness.add_library(root, 'odd', 'import webcpp ;\n\nwebcpp.run prints : prints.cpp ;\n',
                        {'prints.cpp': ODD_SOURCE})


@dataclass(frozen=True)
class Sample:
    """A lane to record: its toolset arguments, what it builds, and what is planted first."""

    lane: tuple[str, ...]
    targets: tuple[str, ...]
    plant: Callable[[Path], None] | None = None


SAMPLES_BY_NAME = {
    # Every test and example of demo, natively: all pass.
    'native-pass': Sample(NATIVE, ('libs/demo/test', 'libs/demo/example')),
    # The same on wasip2, where the native-only programs and the -noexcept variants are not built.
    'wasip2-pass': Sample(WASIP2, ('libs/demo/test', 'libs/demo/example')),
    # demo's pass and rejects, which pass, and each failure planted.
    'native-failures': Sample(NATIVE, ('libs/demo/test//pass', 'libs/demo/test//rejects',
                                       'libs/planted/test', 'libs/planted/example'),
                              plant_failures),
    # A library that declares native only, on wasip2: every program is skipped.
    'wasip2-empty': Sample(WASIP2, ('libs/nativeonly/test',), plant_native_only),
    # A program whose dependency outside every test, the exception handler, does not compile.
    'native-dependency': Sample(NATIVE, ('libs/demo/test//pass-noexcept',), plant_broken_handler),
    # A failure whose output b2 writes into CDATA unescaped.
    'native-odd-output': Sample(NATIVE, ('libs/odd/test//prints',), plant_odd_output),
}


def record(name: str, root: Path) -> Path:
    """Plants what the sample name needs in the scratch superproject root, runs its lane there,
    and returns the file b2 wrote, untrimmed."""
    sample = SAMPLES_BY_NAME[name]
    if sample.plant is not None:
        sample.plant(root)
    output = root / f'{name}.xml'
    result = harness.run_b2(root, '-a', '--dump-tests', f'--out-xml={output.name}', *sample.lane,
                            *sample.targets)
    # With --out-xml, b2 exits 0 even when a test fails; a failure here is b2's own.
    if result.returncode != 0 or not output.is_file():
        raise RuntimeError(f'{name}: b2 failed\n{result.stdout[-4000:]}')
    return output


# What trim removes, each a whole element on its own lines, as b2 writes them.
TRIMMED = (
    re.compile(rb'\n  <os .*?</os> ?(?=\n)', re.DOTALL),
    re.compile(rb'\n    <properties>.*?</properties> ?(?=\n)', re.DOTALL),
    re.compile(rb'\n    <sources>.*?</sources> ?(?=\n)', re.DOTALL),
    # An action without a <name> has its <jam-target> first, once the two above are gone.
    re.compile(rb'\n  <action status="0"[^>]*> ?\n    <jam-target>.*?\n  </action> ?(?=\n)',
               re.DOTALL),
)


def trim(data: bytes) -> bytes:
    """The file b2 wrote, without what TRIMMED matches."""
    for pattern in TRIMMED:
        data = pattern.sub(b'', data)
    return data


def reroute_local(root: Path) -> Path:
    """Points the scratch superproject root's user-config.jam at a link to the superproject's
    .local/ outside the home directory, and returns the directory that holds the link."""
    holder = Path(tempfile.mkdtemp(prefix='webcpp-local-'))
    link = holder / 'local'
    link.symlink_to(harness.ROOT / '.local')
    config = root / '.local/user-config.jam'
    text = config.read_text()
    for local in {str(harness.ROOT / '.local'), str((harness.ROOT / '.local').resolve())}:
        text = text.replace(local, str(link))
    config.write_text(text)
    return holder


def main(names: list[str]) -> int:
    unknown = set(names) - set(SAMPLES_BY_NAME)
    if unknown:
        print(f'record_samples: no sample named {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2
    homes = {str(Path.home()).encode(), str(Path.home().resolve()).encode()}
    for name in names or SAMPLES_BY_NAME:
        root = harness.scratch_superproject('demo')
        holder = reroute_local(root)
        try:
            data = trim(record(name, root).read_bytes())
        finally:
            shutil.rmtree(root)
            shutil.rmtree(holder)
        if any(home in data for home in homes):
            print(f'record_samples: {name} names the home directory; not written', file=sys.stderr)
            return 1
        (SAMPLES / f'{name}.xml').write_bytes(data)
        print(f'{name}: {len(data)} bytes')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
