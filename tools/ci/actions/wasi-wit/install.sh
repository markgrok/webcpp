#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The step of tools/ci/actions/wasi-wit: the WIT of WASI 0.2.12 and 0.3.0, which a component's
# world resolves its wasi:http packages against, in .local/wasi-wit/p2 and .local/wasi-wit/p3,
# where tools/component/component.jam looks for them when no -sWASI_WIT_P2 or -sWASI_WIT_P3 is
# given. Each is the wit/deps directory of the Rust crate that publishes that version's WIT,
# wasip2 1.0.4 and wasip3 0.9.0, from crates.io's static host; the crates are the same on every
# runner.
#
# Usage, from the superproject's root: install.sh
set -euo pipefail

base=https://static.crates.io/crates
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# install <version> <crate> <crate-version> <sha256>: the crate's wit/deps in
# .local/wasi-wit/<version>, in place of what was there.
install() {
    local version="$1" crate="$2" crate_version="$3" sha256="$4"
    local top="${crate}-${crate_version}"
    local url="${base}/${crate}/${top}.crate"
    local archive="${RUNNER_TEMP}/${top}.crate"
    local work="${RUNNER_TEMP}/wasi-wit-${version}"
    "${here}/../../download.sh" "${url}" "${sha256}" "${archive}"
    rm -rf "${work}"
    mkdir -p "${work}"
    tar -xzf "${archive}" -C "${work}"
    rm "${archive}"
    if [ ! -f "${work}/${top}/wit/deps/http.wit" ]; then
        rm -rf "${work}"
        printf 'install.sh: %s holds no wit/deps/http.wit\n' "${url}" >&2
        exit 1
    fi
    rm -rf ".local/wasi-wit/${version}"
    mkdir -p .local/wasi-wit
    mv "${work}/${top}/wit/deps" ".local/wasi-wit/${version}"
    rm -rf "${work}"
    printf 'install.sh: .local/wasi-wit/%s:' "${version}"
    (cd ".local/wasi-wit/${version}" && printf ' %s' *)
    printf '\n'
}

install p2 wasip2 1.0.4+wasi-0.2.12 \
    b67efb37e106e55ce722a510d6b5f9c17f083e5fc79afc2badeb12cc313d9487
install p3 wasip3 0.9.0+wasi-0.3.0 \
    f1d5749fdf69bb9400562eba50f8f25f5cd800ef4b74300038b6f99ae7409674
