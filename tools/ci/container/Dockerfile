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
#
# Every package comes from Ubuntu's snapshot of the archive at SNAPSHOT, so that one Dockerfile is
# one set of packages: apt reads the archive as it was then (Snapshot: yes on the sources, and
# apt-get --snapshot). The snapshot service is HTTPS only, and the base image has no
# ca-certificates, so apt reaches it the first time without verifying the server's certificate,
# to install ca-certificates from the snapshot too, and verifies it from then on. That is no loss
# of integrity: apt checks the snapshot's signed InRelease, and every index and package against
# it, whatever the transport. Installing ca-certificates from the live archive instead pulls in
# openssl and libssl3t64 as they are now, and the snapshot's libssl-dev, which depends on its own
# libssl3t64, then cannot install once Ubuntu updates OpenSSL (measured at SNAPSHOT=20260915:
# "libssl-dev : Depends: libssl3t64 (= 3.0.13-0ubuntu3.15) but 3.0.13-0ubuntu3.16 is to be
# installed"). Ubuntu keeps no snapshot of ports.ubuntu.com: the image builds for x86-64 alone,
# the container lanes' runners (measured: apt 2.8.3 says "Snapshots not supported for
# http://ports.ubuntu.com/ubuntu-ports/" on arm64).
FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55

ARG SNAPSHOT=20261009T000000Z

RUN sed -i 's/^Signed-By: .*/&\nSnapshot: yes/' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::https::Verify-Peer=false update --snapshot "${SNAPSHOT}" \
    && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::https::Verify-Peer=false install \
        --yes --no-install-recommends --snapshot "${SNAPSHOT}" ca-certificates \
    && apt-get update --snapshot "${SNAPSHOT}" \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        --snapshot "${SNAPSHOT}" g++-14 clang-18 libssl-dev python3 \
    && rm -rf /var/lib/apt/lists/*
