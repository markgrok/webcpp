#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks the Jamroot: it finds the installed Boost and searches it first, refuses a missing or
older one by naming the fix, checks again when Boost changes, keeps Boost's warnings out of
-Werror, refuses CPATH, and installs the headers. Each case builds a scratch superproject with
the fixture library demo. Run with the names of some cases to run only those."""

from __future__ import annotations

import filecmp
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import harness

# 2020-09-13, in seconds since the epoch.
INSTALLED_LONG_AGO = 1_600_000_000


def using_boost(prefix):
    """The user-config line that configures the Boost installed in prefix."""
    return f'using boost : 1.92 : <include>"{prefix}/include" <library>"{prefix}/lib" ;\n'


def fake_boost(prefix, version):
    """Writes in prefix a Boost that is only a version.hpp defining version, such as 108000.

    The header is dated 2020, as an installed package's headers keep their own dates: older
    than anything a build wrote. Returns the user-config line that configures it.
    """
    (prefix / 'include/boost').mkdir(parents=True)
    (prefix / 'lib').mkdir()
    header = prefix / 'include/boost/version.hpp'
    header.write_text(
        '#ifndef BOOST_VERSION_HPP\n'
        '#define BOOST_VERSION_HPP\n'
        f'#define BOOST_VERSION {version}\n'
        f'#define BOOST_LIB_VERSION "{version // 100000}_{version // 100 % 1000}"\n'
        '#endif\n')
    os.utime(header, (INSTALLED_LONG_AGO, INSTALLED_LONG_AGO))
    return using_boost(prefix)


def old_boost(root):
    """Writes a fake Boost 1.80, and returns the user-config line that configures it."""
    return fake_boost(root / 'old boost', 108000)


def search_list(output):
    """The directories that a compiler's -v output searches for #include <...>, in order."""
    lines = [line.strip() for line in output.splitlines()]
    start = lines.index('#include <...> search starts here:') + 1
    end = lines.index('End of search list.', start)
    return [Path(line.removesuffix(' (framework directory)')).resolve()
            for line in lines[start:end]]


def test_boost_found_and_fixture_builds(root):
    result = harness.run_b2(root, 'libs/demo/test')
    harness.expect(result, True, '**passed**')
    assert re.search(r'^\*\*passed\*\* .*/pass\.test$', result.stdout, re.MULTILINE), (
        result.stdout[-4000:])


def test_no_boost_configured_names_the_fix(root):
    # No `using boost`, then one that names no location: either leaves Boost to the
    # compiler's default include path, where it is not.
    for config in (harness.without_boost(), harness.without_boost() + 'using boost : 1.92 ;\n'):
        harness.configure(root, config)
        result = harness.run_b2(root, 'libs/demo/test', env_extra={'BOOST_ROOT': None})
        harness.expect(result, False, 'Boost 1.92 or newer was not found',
                       'no `using boost` names its location', 'using boost : 1.92 : <include>')
        # The build stops at the configuration check, before a wall of missing-header errors.
        assert 'lightweight_test.hpp' not in result.stdout, result.stdout[-4000:]


def test_old_boost_is_refused(root):
    harness.configure(root, harness.without_boost() + old_boost(root))
    result = harness.run_b2(root, 'libs/demo/test')
    harness.expect(result, False, 'Boost 1.92 or newer is required', 'Boost 1.80.0 was found in',
                   'using boost : 1.92 : <include>')
    assert 'lightweight_test.hpp' not in result.stdout, result.stdout[-4000:]


def test_a_changed_boost_is_checked_again(root):
    # The configuration check caches its answer under bin/, and its object file too; another
    # Boost, even one older than that object, must reuse neither.
    harness.expect(harness.run_b2(root, 'libs/demo/test'), True, '**passed**')
    harness.configure(root, harness.without_boost() + old_boost(root))
    harness.expect(harness.run_b2(root, 'libs/demo/test'), False, 'Boost 1.80.0 was found in')


def test_a_boost_changed_in_place_is_checked_again(root):
    # Homebrew points opt/boost at another keg: the same directory holds another version.
    keg = root / 'opt boost'
    fake_boost(root / 'boost 1.92', 109200)
    fake_boost(root / 'boost 1.80', 108000)
    keg.symlink_to(root / 'boost 1.92')
    harness.configure(root, harness.without_boost() + using_boost(keg))
    harness.expect(harness.run_b2(root, 'libs/demo'), True)
    keg.unlink()
    keg.symlink_to(root / 'boost 1.80')
    harness.expect(harness.run_b2(root, 'libs/demo'), False, 'Boost 1.80.0 was found in')


def test_boost_warnings_are_not_ours(root):
    # A Boost header that warns under -Wextra, in a directory whose path holds a space: the
    # build treats Boost's headers as system ones, so -Werror does not fail on them. Only
    # Boost's: a header whose include path merely starts with "boost" still warns.
    boost = root / 'boost that warns'
    harness.configure(root, harness.without_boost() + fake_boost(boost, 109200))
    warns = 'inline int warns(int unused) { return 0; }\n'
    (boost / 'include/boost/warns.hpp').write_text(warns)
    harness.add_library(root, 'warns',
                        'import testing ;\n'
                        'compile uses_boost.cpp ;\n'
                        'compile uses_boostlike.cpp : <include>../include ;\n',
                        {'uses_boost.cpp': '#include <boost/warns.hpp>\n',
                         'uses_boostlike.cpp': '#include <boostlike/warns.hpp>\n'})
    (root / 'libs/warns/include/boostlike').mkdir(parents=True)
    (root / 'libs/warns/include/boostlike/warns.hpp').write_text(warns)
    harness.expect(harness.run_b2(root, 'libs/warns/test//uses_boost'), True, '**passed**')
    harness.expect(harness.run_b2(root, 'libs/warns/test//uses_boostlike'), False,
                   "unused parameter 'unused'")


def test_configured_boost_is_searched_first(root):
    # A Boost in a directory the compiler searches on its own must not win over the configured
    # one; Apple clang, for one, searches /usr/local/include before any -isystem directory.
    # So the configured directory comes first among those searched for #include <...>.
    boost = root / 'configured boost'
    harness.configure(root, harness.without_boost() + fake_boost(boost, 109200))
    harness.add_library(root, 'order',
                        'import testing ;\ncompile uses_boost.cpp : <cxxflags>-v ;\n',
                        {'uses_boost.cpp': '#include <boost/version.hpp>\n'})
    result = harness.run_b2(root, 'libs/order/test')
    harness.expect(result, True, '**passed**')
    searched = search_list(result.stdout)
    assert searched[0] == (boost / 'include').resolve(), searched


def test_cpath_set_is_refused(root):
    result = harness.run_b2(root, 'libs/demo/test', env_extra={'CPATH': '/tmp'})
    harness.expect(result, False, 'CPATH is set')


def test_a_relative_user_config_is_found(root):
    # WEBCPP_USER_CONFIG relative to the directory the tests run from, while b2 runs in root.
    shutil.rmtree(root / '.local', ignore_errors=True)
    saved = os.environ.get('WEBCPP_USER_CONFIG')
    os.environ['WEBCPP_USER_CONFIG'] = os.path.relpath(harness.user_config(harness.ROOT))
    try:
        harness.expect(harness.run_b2(root, 'libs/demo/test'), True, '**passed**')
    finally:
        if saved is None:
            del os.environ['WEBCPP_USER_CONFIG']
        else:
            os.environ['WEBCPP_USER_CONFIG'] = saved


def test_install_copies_headers_to_prefix(root):
    # Every file of include/webcpp/**, a header or not, but no hidden file such as Finder's.
    source = root / 'libs/demo/include'
    (source / 'webcpp/.DS_Store').write_bytes(b'Finder')
    prefix = Path(tempfile.mkdtemp(prefix='webcpp prefix '))
    try:
        harness.expect(harness.run_b2(root, 'install', f'--prefix={prefix}'), True)
        files = sorted(path.relative_to(source) for path in source.rglob('*')
                       if path.is_file() and not path.name.startswith('.'))
        installed = sorted(path.relative_to(prefix / 'include')
                           for path in (prefix / 'include').rglob('*') if path.is_file())
        assert installed == files, (installed, files)
        assert Path('webcpp/demo.hpp') in installed, installed
        assert Path('webcpp/demo/answer.hpp') in installed, installed
        assert Path('webcpp/demo/data/answer.txt') in installed, installed
        for file in files:
            assert filecmp.cmp(source / file, prefix / 'include' / file, shallow=False), file
    finally:
        shutil.rmtree(prefix)


CASES = [
    test_boost_found_and_fixture_builds,
    test_no_boost_configured_names_the_fix,
    test_old_boost_is_refused,
    test_a_changed_boost_is_checked_again,
    test_a_boost_changed_in_place_is_checked_again,
    test_boost_warnings_are_not_ours,
    test_configured_boost_is_searched_first,
    test_cpath_set_is_refused,
    test_a_relative_user_config_is_found,
    test_install_copies_headers_to_prefix,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('jamroot_test', CASES, sys.argv[1:]))
