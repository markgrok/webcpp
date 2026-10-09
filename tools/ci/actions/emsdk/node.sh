#!/bin/sh
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The node b2's emscripten toolset runs a program with, installed by tools/ci/actions/emsdk as
# .local/emscripten/node and named by tools/ci/emsdk.jam: the node on PATH, which refuses
# --experimental-wasm-threads without a word.
#
# b2 1.92's emscripten toolset (tools/emscripten.jam) probes `node --version
# --experimental-wasm-threads` when it is configured, and passes the flag to node when the probe
# succeeds. Node 24 and newer no longer know the flag and print "node: bad option:
# --experimental-wasm-threads" on standard error, into the output of every b2 that configures the
# toolset, which the tests of the build compare whole. Exiting non-zero here, silently, makes the
# probe fail as it should, so b2 never passes the flag.
for argument in "$@"; do
    [ "${argument}" = --experimental-wasm-threads ] && exit 9
done
exec node "$@"
