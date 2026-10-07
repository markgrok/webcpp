#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The step of tools/ci/actions/mrdocs: MrDocs 2026.9.29 in .local/mrdocs, where tools/doc/doc.jam
# looks for it. MrDocs publishes a build for Linux x86-64 and none for Linux arm64, so the docs
# run on Linux x86-64. Its archive's top directory is named after MrDocs's own version,
# MrDocs-0.8.0-Linux, not after the release.
#
# Usage, from the superproject's root: install.sh
set -euo pipefail

asset=MrDocs-2026.9.29-Linux.tar.xz
url="https://github.com/cppalliance/mrdocs/releases/download/2026.9.29/${asset}"
sha256=9d96e42f303046fb0b221aa9071eabccc40b9683e0b7af2b02a929d15476ca6a

if [ "${RUNNER_OS}-${RUNNER_ARCH}" != Linux-X64 ]; then
    printf 'install.sh: MrDocs 2026.9.29 is pinned for Linux on X64 only, not %s on %s\n' \
        "${RUNNER_OS}" "${RUNNER_ARCH}" >&2
    exit 1
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${here}/../../download.sh" "${url}" "${sha256}" "${RUNNER_TEMP}/${asset}"
rm -rf .local/mrdocs
mkdir -p .local/mrdocs
tar -xJf "${RUNNER_TEMP}/${asset}" -C .local/mrdocs --strip-components=1 MrDocs-0.8.0-Linux
rm "${RUNNER_TEMP}/${asset}"
.local/mrdocs/bin/mrdocs --version
