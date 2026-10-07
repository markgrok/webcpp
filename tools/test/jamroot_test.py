#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks the Jamroot: it finds the installed Boost, refuses a missing or older one by naming the
fix, refuses CPATH, and installs the headers. Each case builds a scratch superproject with the
fixture library demo. Run with the names of some cases to run only those."""

import filecmp
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import harness

USING_BOOST = re.compile(r'^\s*using\s+boost\b.*$', re.MULTILINE)

# 2020-09-13, in seconds since the epoch.
INSTALLED_LONG_AGO = 1_600_000_000


def expect(result, succeeded, *texts):
    """Asserts that b2 succeeded or failed as expected and printed each text."""
    output = result.stdout
    assert (result.returncode == 0) == succeeded, (succeeded, result.returncode, output[-4000:])
    for text in texts:
        assert text in output, (text, output[-4000:])


def without_boost():
    """The user-config of the superproject without its `using boost` line."""
    return USING_BOOST.sub('', harness.user_config(harness.ROOT).read_text())


def configure(root, text):
    """Makes text the user-config.jam of the scratch superproject root."""
    (root / '.local').mkdir(exist_ok=True)
    (root / '.local/user-config.jam').write_text(text)


def old_boost(root):
    """Writes a Boost 1.80 that is only a version.hpp; returns the user-config line naming it.

    The header is dated 2020, as an installed package's headers keep their own dates: older
    than anything a build wrote.
    """
    prefix = root / 'old boost'
    (prefix / 'include/boost').mkdir(parents=True)
    (prefix / 'lib').mkdir()
    header = prefix / 'include/boost/version.hpp'
    header.write_text(
        '#ifndef BOOST_VERSION_HPP\n'
        '#define BOOST_VERSION_HPP\n'
        '#define BOOST_VERSION 108000\n'
        '#define BOOST_LIB_VERSION "1_80"\n'
        '#endif\n')
    os.utime(header, (INSTALLED_LONG_AGO, INSTALLED_LONG_AGO))
    return f'using boost : 1.80 : <include>"{prefix}/include" <library>"{prefix}/lib" ;\n'


def test_boost_found_and_fixture_builds(root):
    result = harness.run_b2(root, 'libs/demo/test')
    expect(result, True, '**passed**')
    assert re.search(r'^\*\*passed\*\* .*demo_pass\.test$', result.stdout, re.MULTILINE), (
        result.stdout[-4000:])


def test_no_boost_configured_names_the_fix(root):
    configure(root, without_boost())
    result = harness.run_b2(root, 'libs/demo/test', env_extra={'BOOST_ROOT': None})
    expect(result, False, 'Boost 1.92 or newer was not found', 'using boost : 1.92 : <include>')
    # The build stops at the configuration check, before a wall of missing-header errors.
    assert 'lightweight_test.hpp' not in result.stdout, result.stdout[-4000:]


def test_old_boost_is_refused(root):
    configure(root, without_boost() + old_boost(root))
    result = harness.run_b2(root, 'libs/demo/test')
    expect(result, False, 'Boost 1.92 or newer is required', 'Boost 1.80.0 was found in',
           'using boost : 1.92 : <include>')
    assert 'lightweight_test.hpp' not in result.stdout, result.stdout[-4000:]


def test_a_changed_boost_is_checked_again(root):
    # The configuration check caches its answer under bin/, and its object file too; another
    # Boost, even one older than that object, must reuse neither.
    expect(harness.run_b2(root, 'libs/demo/test'), True, '**passed**')
    configure(root, without_boost() + old_boost(root))
    expect(harness.run_b2(root, 'libs/demo/test'), False, 'Boost 1.80.0 was found in')


def test_boost_warnings_are_not_ours(root):
    # A Boost header that warns under -Wextra, in a directory whose path holds a space: the
    # build treats Boost's directory as a system one, so -Werror does not fail on it.
    boost = root / 'boost that warns'
    (boost / 'include/boost').mkdir(parents=True)
    (boost / 'include/boost/version.hpp').write_text('#define BOOST_VERSION 109200\n')
    (boost / 'include/boost/warns.hpp').write_text('inline int warns(int unused) { return 0; }\n')
    configure(root, without_boost()
              + f'using boost : 1.92 : <include>"{boost}/include" <library>"{boost}/lib" ;\n')
    (root / 'libs/warns/test').mkdir(parents=True)
    (root / 'libs/warns/build.jam').write_text('project /webcpp/warns ;\n')
    (root / 'libs/warns/test/Jamfile').write_text('import testing ;\ncompile uses_boost.cpp ;\n')
    (root / 'libs/warns/test/uses_boost.cpp').write_text('#include <boost/warns.hpp>\n')
    expect(harness.run_b2(root, 'libs/warns/test'), True, '**passed**')


def test_cpath_set_is_refused(root):
    result = harness.run_b2(root, 'libs/demo/test', env_extra={'CPATH': '/tmp'})
    expect(result, False, 'CPATH is set')


def test_install_copies_headers_to_prefix(root):
    prefix = Path(tempfile.mkdtemp(prefix='webcpp prefix '))
    try:
        expect(harness.run_b2(root, 'install', f'--prefix={prefix}'), True)
        source = root / 'libs/demo/include'
        headers = sorted(path.relative_to(source) for path in source.rglob('*') if path.is_file())
        installed = sorted(path.relative_to(prefix / 'include')
                           for path in (prefix / 'include').rglob('*') if path.is_file())
        assert installed == headers, (installed, headers)
        assert Path('webcpp/demo.hpp') in installed, installed
        assert any(path.parent == Path('webcpp/demo') for path in installed), installed
        for header in headers:
            assert filecmp.cmp(source / header, prefix / 'include' / header, shallow=False), header
    finally:
        shutil.rmtree(prefix)


CASES = [
    test_boost_found_and_fixture_builds,
    test_no_boost_configured_names_the_fix,
    test_old_boost_is_refused,
    test_a_changed_boost_is_checked_again,
    test_boost_warnings_are_not_ours,
    test_cpath_set_is_refused,
    test_install_copies_headers_to_prefix,
]


def main(names):
    unknown = set(names) - {case.__name__ for case in CASES}
    if unknown:
        print(f'jamroot_test: no case named {", ".join(sorted(unknown))}', file=sys.stderr)
        sys.exit(2)
    for case in CASES:
        if names and case.__name__ not in names:
            continue
        root = harness.scratch_superproject('demo')
        try:
            case(root)
        finally:
            shutil.rmtree(root)
        print(f'{case.__name__}: ok')
    print('jamroot_test: ok')


if __name__ == '__main__':
    main(sys.argv[1:])
