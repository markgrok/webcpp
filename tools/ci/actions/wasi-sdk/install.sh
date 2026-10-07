#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The step of tools/ci/actions/wasi-sdk: wasi-sdk 34.0 in .local/wasi-sdk, where the README
# installs it, for the runner's system and processor (RUNNER_OS, RUNNER_ARCH). Its clang++
# builds the wasip2 and wasip3 lanes, which tools/ci/matrix.py registers, and its clang-format
# and clang-tidy are the lint's.
#
# Usage, from the superproject's root: install.sh
set -euo pipefail

base=https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-34
case "${RUNNER_OS}-${RUNNER_ARCH}" in
    Linux-X64)
        asset=wasi-sdk-34.0-x86_64-linux.tar.gz
        sha256=b761e3a0721dbae9c09a0059e5fdb2bf917d1b4a8a7b430fb3b5aafb0984b2c4
        ;;
    Linux-ARM64)
        asset=wasi-sdk-34.0-arm64-linux.tar.gz
        sha256=f7e243dff54d60bcc576e94d6166b69f410f2500ae4a9ceef34315be10e77971
        ;;
    macOS-ARM64)
        asset=wasi-sdk-34.0-arm64-macos.tar.gz
        sha256=9c59398106b417f8f14913380fdf0097a8cc0ff4af9eb3ce0065a859e88d49e9
        ;;
    macOS-X64)
        asset=wasi-sdk-34.0-x86_64-macos.tar.gz
        sha256=87d27fa8adc68dee59bfbf2e22a6d34ef717c34d6bf1d8af2a56fc929d9ce0eb
        ;;
    *)
        printf 'install.sh: no wasi-sdk 34.0 is pinned for %s on %s\n' "${RUNNER_OS}" \
            "${RUNNER_ARCH}" >&2
        exit 1
        ;;
esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${here}/../../download.sh" "${base}/${asset}" "${sha256}" "${RUNNER_TEMP}/${asset}"
rm -rf .local/wasi-sdk
mkdir -p .local/wasi-sdk
tar -xzf "${RUNNER_TEMP}/${asset}" -C .local/wasi-sdk --strip-components=1
rm "${RUNNER_TEMP}/${asset}"
.local/wasi-sdk/bin/clang++ --version
