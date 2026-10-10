#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The steps of tools/ci/actions/container: the image of the container lanes, built from
# tools/ci/container/Dockerfile once, saved in .local/container/image.tar, which the action caches
# under the Dockerfile's SHA-256, and loaded by every later lane, so that `tools/ci/matrix.py lane`
# finds it and builds none. The tag is webcpp-lane:<the first 16 hex digits of the Dockerfile's
# SHA-256>, as matrix.py's CONTAINER_IMAGE: an image of another Dockerfile is never taken for it.
#
# Usage, from the superproject's root, with the variables a runner sets (RUNNER_ARCH, ImageOS,
# GITHUB_OUTPUT):
#
#   install.sh key     writes the tag and the cache key to GITHUB_OUTPUT;
#   install.sh build   builds the image, with the network, and saves it;
#   install.sh load    loads the image the cache restored, and fails unless it holds the tag.
set -euo pipefail

dockerfile=tools/ci/container/Dockerfile
archive=.local/container/image.tar

digest() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d ' ' -f 1
    else
        shasum -a 256 "$1" | cut -d ' ' -f 1
    fi
}

hash="$(digest "${dockerfile}")"
tag="webcpp-lane:${hash:0:16}"

case "${1-}" in
    key)
        printf 'tag=%s\nkey=container-%s-%s-%s\n' "${tag}" "${hash:0:16}" "${ImageOS:-image}" \
            "${RUNNER_ARCH}" >> "${GITHUB_OUTPUT}"
        ;;
    build)
        docker build --tag "${tag}" "$(dirname "${dockerfile}")"
        mkdir -p "$(dirname "${archive}")"
        docker save --output "${archive}" "${tag}"
        ;;
    load)
        docker load --input "${archive}"
        docker image inspect "${tag}" > /dev/null 2>&1 || {
            printf 'install.sh: %s holds no image %s\n' "${archive}" "${tag}" >&2
            exit 1
        }
        ;;
    *)
        printf 'usage: install.sh key | build | load\n' >&2
        exit 2
        ;;
esac
