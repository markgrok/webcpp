#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The steps of tools/ci/actions/libdatachannel: libdatachannel 0.24.6, shared, in
# .local/libdatachannel, where trystero's build.jam looks for it when LIBDATACHANNEL_ROOT names no
# other directory, until webcpp builds it from third_party/. On Linux and macOS, on X64 and ARM64,
# and on Windows on X64, built with the lane's compilers against the OpenSSL that OPENSSL_ROOT
# names, which the openssl action gives first.
#
# Usage, from the superproject's root, with the variables a runner sets (RUNNER_OS, RUNNER_ARCH,
# ImageOS, ImageVersion, GITHUB_OUTPUT, GITHUB_ENV, GITHUB_PATH), OPENSSL_ROOT, and the action's
# inputs, CC and CXX, the C and C++ compilers of the lane (empty for CMake's own choice, Visual
# Studio's on Windows):
#
#   install.sh key        writes the cache key to GITHUB_OUTPUT: the version, the runner, the
#                         compilers, OpenSSL's version and this action's files;
#   install.sh install    clones the tag v0.24.6, checks that HEAD is the tag's commit, then
#                         fetches its submodules, and builds and installs it with CMake;
#   install.sh configure  checks the installed header and library, and gives the job's later
#                         steps LIBDATACHANNEL_ROOT, and, on Windows, PATH its DLL's directory.
#
# A program links libdatachannel's C++ API, whose types it shares, so it is built with the
# program's compiler and standard library: a program built with GCC and libstdc++ does not link
# against one built with libc++, and the cache is keyed on the compilers. Its own WebSocket, its
# examples and its tests are left out (NO_WEBSOCKET, NO_EXAMPLES, NO_TESTS), and its media
# transport is kept (NO_MEDIA off). Windows builds the Debug configuration: b2's debug variant,
# the lanes', builds a program with /MDd, whose standard types differ from /MD's, and a DLL that
# shares them must match.
set -euo pipefail

version=0.24.6
repository=https://github.com/paullouisageneau/libdatachannel.git
# The commit of the tag v0.24.6 (gh api repos/paullouisageneau/libdatachannel/git/ref/tags/v0.24.6,
# then the tag object): the pin. The submodules are the commits it records.
commit=6b1e2e620f1e37f0eafeee702eaea0043cb305fd

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The functions every action shares: digest, mixed, configuration, compiler_identity.
# shellcheck source=SCRIPTDIR/../../helpers.sh
. "${here}/../../helpers.sh"

# Stops, before anything is fetched, on a runner this action builds nothing for, or without the
# OpenSSL it builds against.
check_runner() {
    case "${RUNNER_OS-}-${RUNNER_ARCH-}" in
        Linux-X64 | Linux-ARM64 | macOS-X64 | macOS-ARM64 | Windows-X64) ;;
        *)
            printf 'install.sh: libdatachannel %s is built for Linux and macOS on X64 and ' \
                "${version}" >&2
            printf 'ARM64, and Windows on X64, not for %s on %s\n' "${RUNNER_OS-}" \
                "${RUNNER_ARCH-}" >&2
            exit 1
            ;;
    esac
    if [ -z "${OPENSSL_ROOT-}" ] || [ ! -f "${OPENSSL_ROOT}/include/openssl/opensslv.h" ]; then
        printf 'install.sh: OPENSSL_ROOT names no OpenSSL (%s): the openssl action runs first\n' \
            "${OPENSSL_ROOT-}" >&2
        exit 1
    fi
}

key() {
    check_runner
    local files compiler openssl
    files="$(digest "${here}/action.yml" "${here}/install.sh" "${here}/../../helpers.sh")"
    compiler="$(compiler_identity | digest)"
    openssl="$(grep -h 'OPENSSL_VERSION_TEXT\|OPENSSL_VERSION_STR' \
        "${OPENSSL_ROOT}/include/openssl/opensslv.h" | digest)"
    printf 'key=libdatachannel-%s-%s-%s-%s-%s-%s-%s\n' "${version}" "${RUNNER_OS}" \
        "${RUNNER_ARCH}" "${ImageOS:-image}" "${compiler:0:16}" "${openssl:0:16}" \
        "${files:0:16}" >> "${GITHUB_OUTPUT}"
}

# Fails the install, naming why, and leaves nothing to be cached.
refuse() {
    printf 'install.sh: %s\n' "$1" >&2
    rm -rf .local/.build/libdatachannel .local/libdatachannel
    exit 1
}

install() {
    check_runner
    rm -rf .local/.build/libdatachannel .local/libdatachannel
    mkdir -p .local/.build
    local source=.local/.build/libdatachannel/source
    git clone --quiet --depth 1 --branch "v${version}" "${repository}" "${source}"
    local head
    head="$(git -C "${source}" rev-parse HEAD)"
    [ "${head}" = "${commit}" ] \
        || refuse "${repository} at v${version} checked out ${head}, and ${commit} is pinned"
    # Only now the submodules, at the commits the pinned commit's gitlinks name: a tag that moved
    # never has git fetch from the URLs its own .gitmodules would name.
    git -C "${source}" submodule update --quiet --init --recursive --depth 1
    local compilers=()
    if [ -n "${CC-}" ]; then
        compilers+=(-DCMAKE_C_COMPILER="${CC}")
    fi
    if [ -n "${CXX-}" ]; then
        compilers+=(-DCMAKE_CXX_COMPILER="${CXX}")
    fi
    local config work=.local/.build/libdatachannel/build
    local prefix
    config="$(configuration)"
    prefix="$(mixed "${PWD}/.local/libdatachannel")"
    # Bash 3.2, macOS's, reads an empty array as unset under set -u.
    cmake -S "${source}" -B "${work}" ${compilers[@]+"${compilers[@]}"} \
        -DCMAKE_BUILD_TYPE="${config}" -DCMAKE_INSTALL_LIBDIR=lib -DBUILD_SHARED_LIBS=ON \
        -DNO_WEBSOCKET=ON -DNO_EXAMPLES=ON -DNO_TESTS=ON -DNO_MEDIA=OFF \
        -DOPENSSL_ROOT_DIR="$(mixed "${OPENSSL_ROOT}")" -DCMAKE_INSTALL_PREFIX="${prefix}"
    cmake --build "${work}" --config "${config}" --parallel
    cmake --install "${work}" --config "${config}" --prefix "${prefix}"
    rm -rf .local/.build/libdatachannel
}

configure() {
    check_runner
    local library=lib/libdatachannel.so
    case "${RUNNER_OS}" in
        macOS) library=lib/libdatachannel.dylib ;;
        Windows) library=lib/datachannel.lib ;;
    esac
    if [ ! -f .local/libdatachannel/include/rtc/rtc.hpp ] \
        || [ ! -e ".local/libdatachannel/${library}" ]; then
        printf 'install.sh: .local/libdatachannel holds no include/rtc/rtc.hpp or %s\n' \
            "${library}" >&2
        exit 1
    fi
    printf 'LIBDATACHANNEL_ROOT=%s\n' "$(mixed "${PWD}/.local/libdatachannel")" >> "${GITHUB_ENV}"
    if [ "${RUNNER_OS}" = Windows ]; then
        [ -f .local/libdatachannel/bin/datachannel.dll ] || {
            printf 'install.sh: .local/libdatachannel holds no bin/datachannel.dll\n' >&2
            exit 1
        }
        # A program finds the DLL on PATH, as a test b2 runs does.
        cygpath -w "${PWD}/.local/libdatachannel/bin" >> "${GITHUB_PATH}"
    fi
    printf 'install.sh: libdatachannel %s in .local/libdatachannel\n' "${version}"
}

case "${1-}" in
    key) key ;;
    install) install ;;
    configure) configure ;;
    *)
        printf 'usage: install.sh key | install | configure\n' >&2
        exit 2
        ;;
esac
