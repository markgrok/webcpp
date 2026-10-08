#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The step of tools/ci/actions/wit-bindgen: wit-bindgen 0.62.0 in .local/wit-bindgen, where
# tools/component/component.jam looks for it when no -sWIT_BINDGEN is given, for the runner's
# system and processor (RUNNER_OS, RUNNER_ARCH). It generates the C bindings of a component's
# world (webcpp.wit-bindings): for the wasip2 and wasip3 lanes, the API reference of a library
# whose headers include them, and the lint, which reads every command those lanes compile. Only
# the program is installed: the archive's licences and README stay out.
#
# Usage, from the superproject's root: install.sh
set -euo pipefail

version=0.62.0
base="https://github.com/bytecodealliance/wit-bindgen/releases/download/v${version}"
case "${RUNNER_OS-}-${RUNNER_ARCH-}" in
    Linux-X64)
        build=x86_64-linux
        sha256=3e81cc6523729f7532b4aa7968648a04abf0c711b7d1677150e9121f4e6458fe
        ;;
    Linux-ARM64)
        build=aarch64-linux
        sha256=16829d8e4b81ef381c7007ad94d2b14c365360d0024cdfb5a34e5fbd4d8f1d89
        ;;
    macOS-ARM64)
        build=aarch64-macos
        sha256=68a8898f8d139d24bd129c5206007dfb7636898edf7659348760d8159ecea9d6
        ;;
    macOS-X64)
        build=x86_64-macos
        sha256=0fe161319d31be62e2a39c8786772230a36e120be457d67c34b67706de91911b
        ;;
    *)
        printf 'install.sh: no wit-bindgen %s is pinned for %s on %s\n' "${version}" \
            "${RUNNER_OS-}" "${RUNNER_ARCH-}" >&2
        exit 1
        ;;
esac

top="wit-bindgen-${version}-${build}"
asset="${top}.tar.gz"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${here}/../../download.sh" "${base}/${asset}" "${sha256}" "${RUNNER_TEMP}/${asset}"
rm -rf .local/wit-bindgen
mkdir -p .local/wit-bindgen
tar -xzf "${RUNNER_TEMP}/${asset}" -C .local/wit-bindgen --strip-components=1 \
    "${top}/wit-bindgen"
rm "${RUNNER_TEMP}/${asset}"
.local/wit-bindgen/wit-bindgen --version
