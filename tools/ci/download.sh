#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# Downloads a pinned file and checks its SHA-256, for the actions of tools/ci/actions.
#
# Usage: tools/ci/download.sh <url> <sha256> <file>
# Exit 0 with <file> written and its SHA-256 the one given; 1 when the download fails or the
# digest differs, which removes <file>; 2 on a usage error.
set -euo pipefail

if [ "$#" -ne 3 ]; then
    printf 'usage: tools/ci/download.sh <url> <sha256> <file>\n' >&2
    exit 2
fi
url="$1"
expected="$2"
file="$3"

curl -fsSL --retry 3 -o "${file}" "${url}"
# sha256sum is GNU's (Linux, Git for Windows); macOS has shasum.
if command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "${file}" | cut -d ' ' -f 1)"
else
    actual="$(shasum -a 256 "${file}" | cut -d ' ' -f 1)"
fi
if [ "${actual}" != "${expected}" ]; then
    rm -f "${file}"
    printf 'download.sh: %s has SHA-256 %s, and %s is pinned\n' "${url}" "${actual}" \
        "${expected}" >&2
    exit 1
fi
printf 'download.sh: %s, SHA-256 %s\n' "${url}" "${actual}"
