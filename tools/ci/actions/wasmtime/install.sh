#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The step of tools/ci/actions/wasmtime: wasmtime 47.0.3 in RUNNER_TEMP/wasmtime, put on PATH
# (GITHUB_PATH), for the runner's system and processor (RUNNER_OS, RUNNER_ARCH). It runs the
# programs of the wasip2 and wasip3 lanes, as testing.launcher=wasmtime, and serves the HTTP
# components of the own lanes on those targets and of the tests of the tools, as
# tools/component/serve.py's `wasmtime serve`.
#
# Usage: install.sh
set -euo pipefail

base=https://github.com/bytecodealliance/wasmtime/releases/download/v47.0.3
case "${RUNNER_OS}-${RUNNER_ARCH}" in
    Linux-X64)
        asset=wasmtime-v47.0.3-x86_64-linux.tar.xz
        sha256=ca1fc56d1afc40c8782e96c297fd182a0da162f9a8f52a1e7b094e1dd648e178
        ;;
    Linux-ARM64)
        asset=wasmtime-v47.0.3-aarch64-linux.tar.xz
        sha256=497b518db00ae585f04390758eaa99ad555bee50612dce7d102602778fb46ff0
        ;;
    macOS-ARM64)
        asset=wasmtime-v47.0.3-aarch64-macos.tar.xz
        sha256=c2684249e5d9ef9351942cf2d315982cf201fe0300f05d63bc1527446f0cd37f
        ;;
    macOS-X64)
        asset=wasmtime-v47.0.3-x86_64-macos.tar.xz
        sha256=424a50f76a9dcf4d02dab326b2374be1ad404030576ee915866e4af106058b35
        ;;
    *)
        printf 'install.sh: no wasmtime 47.0.3 is pinned for %s on %s\n' "${RUNNER_OS}" \
            "${RUNNER_ARCH}" >&2
        exit 1
        ;;
esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${here}/../../download.sh" "${base}/${asset}" "${sha256}" "${RUNNER_TEMP}/${asset}"
directory="${RUNNER_TEMP}/wasmtime"
rm -rf "${directory}"
mkdir -p "${directory}"
tar -xJf "${RUNNER_TEMP}/${asset}" -C "${directory}" --strip-components=1
rm "${RUNNER_TEMP}/${asset}"
printf '%s\n' "${directory}" >> "${GITHUB_PATH}"
"${directory}/wasmtime" --version
