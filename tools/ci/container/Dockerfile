# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The image of the container lanes (tools/ci/matrix.py), GCC 14 and Clang 18 on libstdc++: Ubuntu
# 24.04, the release of their runner, pinned by the digest of its image index (docker-library's
# repo-info, repos/ubuntu/remote/24.04.md), with the two compilers, the development files of the
# OpenSSL 3 that trystero's native backend is built against, as on the runner, and Python, which
# runs the examples. b2, Boost's headers, the superproject and the libraries the CI's actions build
# are the runner's, mounted at their own paths; the lane runs in it with no network but the
# loopback, which the packages are installed before.
FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        g++-14 clang-18 libssl-dev python3 \
    && rm -rf /var/lib/apt/lists/*
