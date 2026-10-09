#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The steps of tools/ci/actions/emsdk: Emscripten 6.0.11 from emsdk in .local/emsdk, where
# tools/ci/matrix.py registers b2's emscripten toolset against it, for the runner's system and
# processor (RUNNER_OS, RUNNER_ARCH): Linux and macOS, on X64 and ARM64.
#
# Usage, from the superproject's root, with the variables a runner sets (RUNNER_OS, RUNNER_ARCH,
# RUNNER_TEMP, GITHUB_WORKSPACE, GITHUB_OUTPUT, GITHUB_ENV):
#
#   install.sh key        writes the cache key, the version, the runner and this action's files,
#                         to GITHUB_OUTPUT;
#   install.sh install    downloads the emsdk repository at the commit of its tag 6.0.11, and
#                         every archive `emsdk install 6.0.11` installs from, each checked against
#                         the SHA-256 pinned here, then runs `emsdk install` and `emsdk activate`
#                         on those files alone, in .local/emsdk;
#   install.sh configure  checks that .local/emsdk's emcc is Emscripten 6.0.11, installs the node
#                         wrapper, gives the job's later steps EM_CACHE, and warms that cache.
#
# emsdk downloads its archives without checking them, so each is downloaded here first, with
# tools/ci/download.sh, into .local/emsdk/downloads under the name emsdk gives it there, and
# emsdk runs with EMSDK_KEEP_DOWNLOADS=1, under which it installs from a file it finds there
# rather than download it again. An archive emsdk downloads besides those fails the install,
# naming it. The archives are removed once installed: the action caches what they installed.
#
# EM_CACHE is .local/emscripten-cache, outside the emsdk, which Emscripten would otherwise write
# its cache into, by its resolved path: Emscripten 6.0.11 builds a system library from a relative
# path it computes from EM_CACHE as given, which misses its sources through a link, as macOS's
# /var is one.
#
# Emscripten checks its configuration the first time it meets a cache, and says "Running sanity
# checks" on standard error, which would land in the output of the first b2 that configures the
# toolset, as tools/ci/matrix.py plan reads it. configure runs that check here, once, where its
# log is the action's, and the cache it leaves is saved with the emsdk: no b2 of a job meets a
# cache that is not checked, and the check still runs, as Emscripten means it to, when the
# version or the emsdk's directory changes.
set -euo pipefail

version=6.0.11
# What `emcc --version` names: the version and the commit of emscripten it was built from.
emscripten="${version} (a0014542110d6078c3a1a7941fa1ddb3a2281f16)"
# The commit of emsdk's tag 6.0.11 (gh api repos/emscripten-core/emsdk/git/ref/tags/6.0.11).
commit=dd8e25632640cfc1fb570c7fa4cc374e8a5e5a72
archive="emsdk-${commit}.tar.gz"
url="https://github.com/emscripten-core/emsdk/archive/${commit}.tar.gz"
sha256=f57126eb845e04325a3d3d7711dbddc159ff0e8516c331d28cf01476bf72dc0b
# The build of emscripten-releases that emsdk's emscripten-releases-tags.json names for 6.0.11.
release=f6264d4a4dd9ba24a9f0a5702835a44d1463de13
builds=https://storage.googleapis.com/webassembly/emscripten-releases-builds

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The archives emsdk installs 6.0.11 from on the runner, one line each: its URL, the name emsdk
# saves it under, and its SHA-256. The release's binaries, then Node 24.19.0, whose archives are
# nodejs.org's (SHASUMS256.txt), and on macOS Python 3.13.3, which emsdk's sdk installs there.
pinned() {
    case "${RUNNER_OS-}-${RUNNER_ARCH-}" in
        Linux-X64)
            printf '%s %s %s\n' \
                "${builds}/linux/${release}/wasm-binaries.tar.xz" \
                "${release}-wasm-binaries.tar.xz" \
                cab251b54999e8fb4260080f0e719796336570396e118865013a20b8d93dbb83 \
                "${builds}/deps/node-v24.19.0-linux-x64.tar.xz" \
                node-v24.19.0-linux-x64.tar.xz \
                14b342e71204f811bde6153be8e04b62aef63c236fef92b55f9c83154b409647
            ;;
        Linux-ARM64)
            printf '%s %s %s\n' \
                "${builds}/linux/${release}/wasm-binaries-arm64.tar.xz" \
                "${release}-wasm-binaries-arm64.tar.xz" \
                9146dd517c705d30505942d0eb6786ed11ea59cc8acd19fea50d21c3d732532b \
                "${builds}/deps/node-v24.19.0-linux-arm64.tar.xz" \
                node-v24.19.0-linux-arm64.tar.xz \
                01443c1e1a29e531ccad5a46fefa6df490d2189c49f7955904aecdbb0fe86fdc
            ;;
        macOS-X64)
            printf '%s %s %s\n' \
                "${builds}/mac/${release}/wasm-binaries.tar.xz" \
                "${release}-wasm-binaries.tar.xz" \
                5959c07b2206d82414878ad118f9988ccdf489fe8a9e54b7a4dcdec57d8298a6 \
                "${builds}/deps/node-v24.19.0-darwin-x64.tar.gz" \
                node-v24.19.0-darwin-x64.tar.gz \
                d1b5e999db158c62fe8f7267a4476b035d8bd93b1a605bac24a3f0dd166e3316 \
                "${builds}/deps/python-3.13.3-0-macos-x86_64.tar.gz" \
                python-3.13.3-0-macos-x86_64.tar.gz \
                d3f30e1b78354d6f74fae951175dc2bd22b386aafeab13edd6ac7c9613b0d33c
            ;;
        macOS-ARM64)
            printf '%s %s %s\n' \
                "${builds}/mac/${release}/wasm-binaries-arm64.tar.xz" \
                "${release}-wasm-binaries-arm64.tar.xz" \
                8151a0cd16b9fee579e73b8b31905e7073cdf20e76a91858ff807858a635fa5d \
                "${builds}/deps/node-v24.19.0-darwin-arm64.tar.gz" \
                node-v24.19.0-darwin-arm64.tar.gz \
                8294b7aa9b03997481c06babf1e8b270c859358f27da57a11509afe537ac381d \
                "${builds}/deps/python-3.13.3-0-macos-arm64.tar.gz" \
                python-3.13.3-0-macos-arm64.tar.gz \
                2b0899d7ade9463b0c909ef23aeea27546a4f412637998d817a49718bc2bac19
            ;;
        *)
            printf 'install.sh: no emsdk %s is pinned for %s on %s: the action runs on Linux and ' \
                "${version}" "${RUNNER_OS-}" "${RUNNER_ARCH-}" >&2
            printf 'macOS, on X64 and ARM64\n' >&2
            exit 1
            ;;
    esac
}

digest() {
    if command -v sha256sum >/dev/null 2>&1; then
        cat "$@" | sha256sum | cut -d ' ' -f 1
    else
        cat "$@" | shasum -a 256 | cut -d ' ' -f 1
    fi
}

key() {
    pinned > /dev/null
    # A change to how the emsdk is installed or configured installs it again.
    local files
    files="$(digest "${here}/action.yml" "${here}/install.sh" "${here}/node.sh" \
        "${here}/../../download.sh")"
    printf 'key=emsdk-%s-%s-%s-%s-%s\n' "${version}" "${RUNNER_OS}" "${RUNNER_ARCH}" \
        "${ImageOS:-image}" "${files:0:16}" >> "${GITHUB_OUTPUT}"
}

install() {
    local downloads
    downloads="$(pinned)"
    "${here}/../../download.sh" "${url}" "${sha256}" "${RUNNER_TEMP}/${archive}"
    rm -rf .local/emsdk
    mkdir -p .local/emsdk/downloads
    tar -xzf "${RUNNER_TEMP}/${archive}" -C .local/emsdk --strip-components=1
    rm "${RUNNER_TEMP}/${archive}"
    local names=()
    local download name hash
    while read -r download name hash; do
        "${here}/../../download.sh" "${download}" "${hash}" ".local/emsdk/downloads/${name}"
        names+=("${name}")
    done <<< "${downloads}"
    (cd .local/emsdk && EMSDK_KEEP_DOWNLOADS=1 ./emsdk install "${version}" \
        && ./emsdk activate "${version}")
    local found
    for found in .local/emsdk/downloads/*; do
        name="$(basename "${found}")"
        if [[ " ${names[*]} " != *" ${name} "* ]]; then
            printf 'install.sh: emsdk downloaded %s, which this action does not pin\n' "${name}" >&2
            rm -rf .local/emsdk
            exit 1
        fi
    done
    rm -rf .local/emsdk/downloads
}

configure() {
    pinned > /dev/null
    local cache
    cache="$(cd "${GITHUB_WORKSPACE}" && pwd -P)/.local/emscripten-cache"
    mkdir -p "${cache}"
    export EM_CACHE="${cache}"
    local emcc=.local/emsdk/upstream/emscripten/emcc
    local output printed
    output="$("${emcc}" --version)" || {
        printf 'install.sh: %s --version failed\n' "${emcc}" >&2
        exit 1
    }
    printed="${output%%$'\n'*}"
    if [[ "${printed}" != *" ${emscripten}" ]]; then
        printf 'install.sh: %s is not Emscripten %s: emcc --version printed %s\n' "${emcc}" \
            "${emscripten}" "${printed}" >&2
        exit 1
    fi
    printf '%s\n' "${printed}"
    # The cache is checked now: em++, as b2 runs it to configure the toolset, says nothing more.
    local said
    said="$(.local/emsdk/upstream/emscripten/em++ --version 2>&1 >/dev/null)"
    if [ -n "${said}" ]; then
        printf 'install.sh: em++ --version still says, with the cache %s warmed:\n%s\n' \
            "${cache}" "${said}" >&2
        exit 1
    fi
    mkdir -p .local/emscripten
    cp "${here}/node.sh" .local/emscripten/node
    chmod 755 .local/emscripten/node
    printf 'EM_CACHE=%s\n' "${cache}" >> "${GITHUB_ENV}"
    printf 'install.sh: EM_CACHE=%s, warmed; node wrapper .local/emscripten/node\n' "${cache}"
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
