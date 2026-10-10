#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The functions the actions of tools/ci/actions share, which each install.sh sources, as
# `. "${here}/../../helpers.sh"`, beside tools/ci/download.sh:
#
#   digest FILE...       the SHA-256 of the files, one after the other, in hex;
#   mixed PATH           PATH as Windows programs and b2 read it there, with slashes
#                        (D:/a/webcpp), on Windows (RUNNER_OS), else PATH as it is;
#   configuration        the CMake configuration an external library is built in: Debug on
#                        Windows, whose /MDd is the runtime b2's debug variant, the lanes', links a
#                        program with, and Release elsewhere, where it does not change what a
#                        program links;
#   compiler_identity    what the lane's compilers are, for a cache key: the first line of the
#                        --version of each of CC and CXX that is set, else, when neither is, the
#                        image (ImageOS, ImageVersion), whose default compilers CMake takes.

digest() {
    if command -v sha256sum >/dev/null 2>&1; then
        cat "$@" | sha256sum | cut -d ' ' -f 1
    else
        cat "$@" | shasum -a 256 | cut -d ' ' -f 1
    fi
}

mixed() {
    if [ "${RUNNER_OS-}" = Windows ]; then
        cygpath -m "$1"
    else
        printf '%s\n' "$1"
    fi
}

configuration() {
    if [ "${RUNNER_OS-}" = Windows ]; then
        printf 'Debug\n'
    else
        printf 'Release\n'
    fi
}

compiler_identity() {
    if [ -z "${CC-}" ] && [ -z "${CXX-}" ]; then
        printf 'default %s %s\n' "${ImageOS:-image}" "${ImageVersion:-version}"
        return
    fi
    local compiler
    for compiler in "${CC-}" "${CXX-}"; do
        if [ -n "${compiler}" ]; then
            "${compiler}" --version 2>&1 | head -n 1
        fi
    done
}
