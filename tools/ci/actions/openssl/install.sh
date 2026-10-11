#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The step of tools/ci/actions/openssl: the runner's own OpenSSL 3, laid out in .local/openssl as
# include/openssl and lib/, where trystero's build.jam looks for it when OPENSSL_ROOT names no
# other directory, and OPENSSL_ROOT given to the job's later steps, until webcpp builds it from
# third_party/. On Linux, the system's, which pkg-config names; on macOS, Homebrew's openssl@3,
# installed with brew when the image lacks it; on Windows on X64, the one the image installs in
# %ProgramFiles%\OpenSSL, always preferred, else the installer pinned here, checked against its
# SHA-256.
#
# Usage, from the superproject's root, with the variables a runner sets (RUNNER_OS, RUNNER_ARCH,
# RUNNER_TEMP, GITHUB_ENV, GITHUB_PATH, and ProgramFiles on Windows): install.sh
#
# On Linux and macOS, .local/openssl holds links: include/openssl to the system's headers, and
# lib/ the two libraries, so that a directory of its own, never the system's /usr/include, is
# given to a compiler: GCC and Clang given -isystem /usr/include no longer find the C library's
# headers through libstdc++'s #include_next (measured with g++-14 and clang++-18 on Ubuntu 24.04),
# as a reference parses its dependencies' directories. Debian and Ubuntu keep the two headers of
# OpenSSL's build configuration, opensslconf.h and configuration.h, apart, in the architecture's
# /usr/include/<multiarch>/openssl, which a native compiler searches and a parse for another
# target, as trystero's reference is, does not: there include/openssl is a directory of links to
# each header of both, so that it holds every header of OpenSSL. On Windows it holds copies: the
# headers, and the import libraries libssl.lib and libcrypto.lib from the first of
# lib/VC/x64/MD, lib/VC/x64/MDd and lib that holds both (CMake's FindOpenSSL reads the same
# layout); their DLLs are in the installation's bin, which is put on PATH.
set -euo pipefail

# The installer of Shining Light Productions that the image installs from, as
# slproweb/opensslhashes's win32_openssl_hashes.json names it (gh api
# repos/slproweb/opensslhashes/contents/win32_openssl_hashes.json): a fallback for an image without
# OpenSSL alone. Shining Light removes a superseded installer from /download/, so once 3.6.5 is
# superseded this URL answers 404 and the fallback fails at download.sh, naming the URL: the pin
# is then moved to the release the JSON lists, with its SHA-256.
installer=Win64OpenSSL-3_6_5.exe
installer_url="https://slproweb.com/download/${installer}"
installer_sha256=8b2fcf66088fa0d13fa5729ef374a182adf72edfffde89089b3b1bf48c3f257f

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The functions every action shares: digest, mixed, configuration, compiler_identity.
# shellcheck source=SCRIPTDIR/../../helpers.sh
. "${here}/../../helpers.sh"

# Fails the step, naming why, and leaves no .local/openssl.
refuse() {
    printf 'install.sh: %s\n' "$1" >&2
    rm -rf .local/openssl
    exit 1
}

# The major version include/openssl/opensslv.h of prefix states, or nothing: OpenSSL 1.1's states
# none.
major() {
    sed -n 's/^#[[:space:]]*define[[:space:]]*OPENSSL_VERSION_MAJOR[[:space:]]*\([0-9]*\).*/\1/p' \
        "$1/openssl/opensslv.h" 2>/dev/null | head -n 1
}

# Stops unless the headers in include hold OpenSSL 3.
check_headers() {
    local include="$1"
    [ -f "${include}/openssl/ssl.h" ] || refuse "${include} holds no openssl/ssl.h"
    local found
    found="$(major "${include}")"
    [ "${found}" = 3 ] || refuse "${include}/openssl/opensslv.h is not OpenSSL 3's: \
OPENSSL_VERSION_MAJOR is '${found}'"
}

# Links include/openssl and the two libraries of libdir with extension into .local/openssl; with
# configured, the directory that holds the headers of the build's configuration apart,
# include/openssl is a directory of links to each header of both.
link() {
    local include="$1" libdir="$2" extension="$3" configured="${4-}"
    check_headers "${include}"
    local library
    for library in libssl libcrypto; do
        [ -e "${libdir}/${library}.${extension}" ] \
            || refuse "${libdir} holds no ${library}.${extension}"
    done
    rm -rf .local/openssl
    mkdir -p .local/openssl/include .local/openssl/lib
    if [ -n "${configured}" ]; then
        mkdir .local/openssl/include/openssl
        ln -s "${include}/openssl/"* "${configured}/"* .local/openssl/include/openssl/ \
            || refuse "${include}/openssl and ${configured} could not be linked together"
    else
        ln -s "${include}/openssl" .local/openssl/include/openssl
    fi
    [ -f .local/openssl/include/openssl/opensslconf.h ] \
        || refuse "${include}/openssl holds no opensslconf.h"
    for library in libssl libcrypto; do
        ln -s "${libdir}/${library}.${extension}" ".local/openssl/lib/${library}.${extension}"
    done
}

linux() {
    command -v pkg-config >/dev/null 2>&1 || refuse 'pkg-config, which names the system OpenSSL, \
is not on PATH'
    local include libdir configured=''
    include="$(pkg-config --variable=includedir openssl)" \
        || refuse 'pkg-config knows no openssl: install the development files of OpenSSL 3'
    libdir="$(pkg-config --variable=libdir openssl)"
    if [ ! -f "${include}/openssl/opensslconf.h" ]; then
        command -v dpkg-architecture >/dev/null 2>&1 || refuse "${include}/openssl holds no \
opensslconf.h, and dpkg-architecture, which names Debian's directory of the architecture's \
headers, is not on PATH"
        local multiarch
        multiarch="$(dpkg-architecture -qDEB_HOST_MULTIARCH)" \
            || refuse 'dpkg-architecture names no multiarch tuple'
        configured="${include}/${multiarch}/openssl"
        [ -f "${configured}/opensslconf.h" ] \
            || refuse "neither ${include}/openssl nor ${configured} holds opensslconf.h"
    fi
    link "${include}" "${libdir}" so "${configured}"
}

macos() {
    command -v brew >/dev/null 2>&1 || refuse 'brew, which names openssl@3, is not on PATH'
    local prefix
    prefix="$(brew --prefix openssl@3)"
    # The macOS images have openssl@3 only as a dependency of other formulae, which Homebrew moves
    # to openssl@4 one by one: when it is gone, it is installed, its bottle checked by Homebrew
    # against the SHA-256 its formula records, at the version Homebrew has then.
    if [ ! -d "${prefix}" ]; then
        printf "install.sh: Homebrew's openssl@3 is not installed in %s: " "${prefix}"
        printf 'installing it with brew\n'
        brew install openssl@3 || refuse 'brew install openssl@3 failed'
    fi
    [ -d "${prefix}" ] || refuse "Homebrew's openssl@3 is not installed in ${prefix}"
    link "${prefix}/include" "${prefix}/lib" dylib
}

# The image's OpenSSL, else the pinned installer's, installed in RUNNER_TEMP.
windows_prefix() {
    local programs
    programs="$(cygpath -u "${ProgramFiles:-C:\\Program Files}")"
    if [ -f "${programs}/OpenSSL/include/openssl/ssl.h" ]; then
        printf '%s\n' "${programs}/OpenSSL"
        return
    fi
    local temp
    temp="$(cygpath -u "${RUNNER_TEMP}")"
    "${here}/../../download.sh" "${installer_url}" "${installer_sha256}" "${temp}/${installer}" \
        >&2 || refuse "${installer_url} could not be downloaded as pinned"
    # Inno Setup's options, as the image's own install passes them.
    "${temp}/${installer}" /verysilent /sp- /suppressmsgboxes \
        "/DIR=$(cygpath -w "${temp}/openssl")" >&2 \
        || refuse "${installer} did not install"
    rm -f "${temp}/${installer}"
    printf '%s\n' "${temp}/openssl"
}

windows() {
    local prefix
    prefix="$(windows_prefix)"
    check_headers "${prefix}/include"
    local found='' directory
    for directory in lib/VC/x64/MD lib/VC/x64/MDd lib; do
        if [ -f "${prefix}/${directory}/libssl.lib" ] \
            && [ -f "${prefix}/${directory}/libcrypto.lib" ]; then
            found="${prefix}/${directory}"
            break
        fi
    done
    [ -n "${found}" ] || refuse "${prefix} holds no libssl.lib and libcrypto.lib in lib/VC/x64/MD, \
lib/VC/x64/MDd or lib"
    rm -rf .local/openssl
    mkdir -p .local/openssl/include .local/openssl/lib
    cp -R "${prefix}/include/openssl" .local/openssl/include/openssl
    cp "${found}/libssl.lib" "${found}/libcrypto.lib" .local/openssl/lib/
    cygpath -w "${prefix}/bin" >> "${GITHUB_PATH}"
}

case "${RUNNER_OS-}-${RUNNER_ARCH-}" in
    Linux-X64 | Linux-ARM64) linux ;;
    macOS-X64 | macOS-ARM64) macos ;;
    Windows-X64) windows ;;
    *)
        printf 'install.sh: no OpenSSL 3 is found or pinned for %s on %s: the action runs on ' \
            "${RUNNER_OS-}" "${RUNNER_ARCH-}" >&2
        printf 'Linux and macOS, on X64 and ARM64, and on Windows on X64\n' >&2
        exit 1
        ;;
esac
printf 'OPENSSL_ROOT=%s\n' "$(mixed "${PWD}/.local/openssl")" >> "${GITHUB_ENV}"
printf 'install.sh: OpenSSL %s in .local/openssl\n' "$(major .local/openssl/include)"
