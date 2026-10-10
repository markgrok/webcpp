#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The steps of tools/ci/actions/secp256k1: libsecp256k1 0.8.0, static, with its schnorrsig and
# extrakeys modules, in .local/secp256k1-native and, for emscripten, .local/secp256k1-emscripten,
# where trystero's build.jam looks for it when SECP256K1_ROOT and SECP256K1_EMSCRIPTEN_ROOT name
# no other directory, until webcpp builds it from third_party/. On Linux and macOS, on X64 and
# ARM64, and on Windows on X64; the emscripten build on Linux and macOS, where the emsdk action
# installs Emscripten.
#
# Usage, from the superproject's root, with the variables a runner sets (RUNNER_OS, RUNNER_ARCH,
# ImageOS, ImageVersion, GITHUB_OUTPUT, GITHUB_ENV) and the action's inputs, CC, the C compiler
# of the lane (empty for CMake's own choice, Visual Studio's on Windows), and EMSCRIPTEN, 'true'
# for the emscripten build too:
#
#   install.sh key        writes the cache key to GITHUB_OUTPUT: the version, the runner, the
#                         compiler, the emscripten build and this action's files;
#   install.sh install    downloads the source archive of the pinned commit, checked against its
#                         SHA-256, and builds and installs it with CMake, natively and, with
#                         EMSCRIPTEN=true, with Emscripten's emcmake;
#   install.sh configure  checks the installed headers and libraries, and gives the job's later
#                         steps SECP256K1_ROOT and, with EMSCRIPTEN=true, SECP256K1_EMSCRIPTEN_ROOT.
#
# The options are those trystero's page builds it with (its section "The three libraries"): its
# small tables keep the browser's download small. Windows builds the Debug configuration, whose
# runtime library (/MDd) is the one b2's debug variant, the lanes', links a program with; elsewhere
# the configuration does not change what a program links, and Release is built. On Windows,
# CMake's library is libsecp256k1.lib, and a program defines SECP256K1_STATIC, which trystero's
# build.jam does.
set -euo pipefail

version=0.8.0
# The commit of the tag v0.8.0 (gh api repos/bitcoin-core/secp256k1/git/ref/tags/v0.8.0, then
# the tag object), and the SHA-256 of GitHub's archive of it.
commit=6e2c8bc4ecdc6e71dbe7a368f360d8d453ce435d
url="https://github.com/bitcoin-core/secp256k1/archive/${commit}.tar.gz"
sha256=3fe9fd705f4fdf2fe90d6e04b6c1fedd7e8f244a119315886f6468f52c2dfc33

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The Emscripten version the emsdk action installs, its line version=, which the key of the
# emscripten build names: a bump of emsdk builds libsecp256k1 again.
emscripten_version() {
    local emsdk
    emsdk="$(cd "${here}/../emsdk" 2>/dev/null && pwd -P)/install.sh"
    local found
    found="$(sed -n 's/^version=\([0-9][0-9.]*\)$/\1/p' "${emsdk}" 2>/dev/null | head -n 1)"
    if [ -z "${found}" ]; then
        printf 'install.sh: %s names no version=\n' "${emsdk}" >&2
        exit 1
    fi
    printf '%s\n' "${found}"
}

options=(
    -DBUILD_SHARED_LIBS=OFF -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DCMAKE_INSTALL_LIBDIR=lib
    -DSECP256K1_ENABLE_MODULE_SCHNORRSIG=ON -DSECP256K1_ENABLE_MODULE_EXTRAKEYS=ON
    -DSECP256K1_ECMULT_WINDOW_SIZE=4 -DSECP256K1_ECMULT_GEN_KB=2
    -DSECP256K1_BUILD_TESTS=OFF -DSECP256K1_BUILD_EXHAUSTIVE_TESTS=OFF
    -DSECP256K1_BUILD_BENCHMARK=OFF -DSECP256K1_BUILD_CTIME_TESTS=OFF
)

# The action's input emscripten, false unless it says true, and nothing else.
emscripten_wanted() {
    local wanted="${EMSCRIPTEN:-false}"
    if [ "${wanted}" != true ] && [ "${wanted}" != false ]; then
        printf "install.sh: the input emscripten is 'true' or 'false', not '%s'\n" "${wanted}" >&2
        exit 2
    fi
    printf '%s\n' "${wanted}"
}

# Stops, before anything is downloaded, on a runner this action builds nothing for.
check_runner() {
    case "${RUNNER_OS-}-${RUNNER_ARCH-}" in
        Linux-X64 | Linux-ARM64 | macOS-X64 | macOS-ARM64 | Windows-X64) ;;
        *)
            printf 'install.sh: libsecp256k1 %s is built for Linux and macOS on X64 and ARM64, ' \
                "${version}" >&2
            printf 'and Windows on X64, not for %s on %s\n' "${RUNNER_OS-}" "${RUNNER_ARCH-}" >&2
            exit 1
            ;;
    esac
    if [ "$(emscripten_wanted)" = true ] && [ "${RUNNER_OS}" = Windows ]; then
        printf 'install.sh: the emscripten build of libsecp256k1 is made on Linux and macOS, ' >&2
        printf 'where the emsdk action installs Emscripten, not on Windows\n' >&2
        exit 1
    fi
}

digest() {
    if command -v sha256sum >/dev/null 2>&1; then
        cat "$@" | sha256sum | cut -d ' ' -f 1
    else
        cat "$@" | shasum -a 256 | cut -d ' ' -f 1
    fi
}

# A path as Windows programs read it there, with slashes: D:/a/webcpp/webcpp/.local.
mixed() {
    if [ "${RUNNER_OS}" = Windows ]; then
        cygpath -m "$1"
    else
        printf '%s\n' "$1"
    fi
}

# The configuration built: Debug on Windows, for the lanes' /MDd, Release elsewhere.
configuration() {
    if [ "${RUNNER_OS}" = Windows ]; then
        printf 'Debug\n'
    else
        printf 'Release\n'
    fi
}

# What the compiler says it is: the first line of its --version, or, when the input names none,
# the image, whose default compiler CMake takes.
compiler_identity() {
    if [ -n "${CC-}" ]; then
        "${CC}" --version 2>&1 | head -n 1
    else
        printf 'default %s %s\n' "${ImageOS:-image}" "${ImageVersion:-version}"
    fi
}

key() {
    check_runner
    local wanted files compiler
    wanted="$(emscripten_wanted)"
    files="$(digest "${here}/action.yml" "${here}/install.sh" "${here}/../../download.sh")"
    compiler="$(compiler_identity | digest)"
    local build=native
    if [ "${wanted}" = true ]; then
        build="native-emscripten-$(emscripten_version)"
    fi
    printf 'key=secp256k1-%s-%s-%s-%s-%s-%s-%s\n' "${version}" "${RUNNER_OS}" "${RUNNER_ARCH}" \
        "${ImageOS:-image}" "${compiler:0:16}" "${build}" "${files:0:16}" >> "${GITHUB_OUTPUT}"
}

# Fails the install, naming why, and leaves nothing to be cached.
refuse() {
    printf 'install.sh: %s\n' "$1" >&2
    rm -rf .local/.build/secp256k1 .local/secp256k1-native .local/secp256k1-emscripten
    exit 1
}

# Configures, builds and installs the sources in source into prefix, with the words before the
# options, cmake or emcmake cmake.
build() {
    local source="$1" work="$2" prefix="$3"
    shift 3
    local config
    config="$(configuration)"
    "$@" -S "${source}" -B "${work}" -DCMAKE_BUILD_TYPE="${config}" "${options[@]}" \
        -DCMAKE_INSTALL_PREFIX="$(mixed "${PWD}/${prefix}")"
    cmake --build "${work}" --config "${config}" --parallel
    cmake --install "${work}" --config "${config}" --prefix "$(mixed "${PWD}/${prefix}")"
}

install() {
    check_runner
    local wanted
    wanted="$(emscripten_wanted)"
    local emcmake=.local/emsdk/upstream/emscripten/emcmake
    if [ "${wanted}" = true ] && [ ! -x "${emcmake}" ]; then
        refuse "the emscripten build needs ${emcmake}, which the emsdk action installs first"
    fi
    rm -rf .local/.build/secp256k1 .local/secp256k1-native .local/secp256k1-emscripten
    mkdir -p .local/.build/secp256k1
    local archive=.local/.build/secp256k1/source.tar.gz
    "${here}/../../download.sh" "${url}" "${sha256}" "${archive}" \
        || refuse "${url} could not be downloaded as pinned"
    tar -xzf "${archive}" -C .local/.build/secp256k1
    local source=".local/.build/secp256k1/secp256k1-${commit}"
    [ -f "${source}/CMakeLists.txt" ] || refuse "${url} holds no secp256k1-${commit}/CMakeLists.txt"
    local compilers=()
    if [ -n "${CC-}" ]; then
        compilers=(-DCMAKE_C_COMPILER="${CC}")
    fi
    # Bash 3.2, macOS's, reads an empty array as unset under set -u.
    build "${source}" .local/.build/secp256k1/native .local/secp256k1-native \
        cmake ${compilers[@]+"${compilers[@]}"}
    if [ "${wanted}" = true ]; then
        build "${source}" .local/.build/secp256k1/emscripten .local/secp256k1-emscripten \
            "${emcmake}" cmake
    fi
    rm -rf .local/.build/secp256k1
}

# Whether prefix holds the header and the static library of its build, or fails naming it.
check_prefix() {
    local prefix="$1" library="$2"
    if [ ! -f "${prefix}/include/secp256k1.h" ] \
        || [ ! -f "${prefix}/include/secp256k1_schnorrsig.h" ] \
        || [ ! -f "${prefix}/lib/${library}" ]; then
        printf 'install.sh: %s holds no include/secp256k1.h, include/secp256k1_schnorrsig.h or ' \
            "${prefix}" >&2
        printf 'lib/%s\n' "${library}" >&2
        exit 1
    fi
}

configure() {
    check_runner
    local wanted
    wanted="$(emscripten_wanted)"
    local library=libsecp256k1.a
    if [ "${RUNNER_OS}" = Windows ]; then
        library=libsecp256k1.lib
    fi
    check_prefix .local/secp256k1-native "${library}"
    printf 'SECP256K1_ROOT=%s\n' "$(mixed "${PWD}/.local/secp256k1-native")" >> "${GITHUB_ENV}"
    if [ "${wanted}" = true ]; then
        check_prefix .local/secp256k1-emscripten libsecp256k1.a
        printf 'SECP256K1_EMSCRIPTEN_ROOT=%s\n' "${PWD}/.local/secp256k1-emscripten" \
            >> "${GITHUB_ENV}"
    fi
    printf 'install.sh: libsecp256k1 %s in .local/secp256k1-native%s\n' "${version}" \
        "$([ "${wanted}" = true ] && printf ' and .local/secp256k1-emscripten')"
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
