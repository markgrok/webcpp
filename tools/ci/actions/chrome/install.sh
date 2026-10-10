#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The step of tools/ci/actions/chrome: Chrome for Testing's chrome-headless-shell at a pinned
# version, in .local/chrome-headless-shell, and CHROME given to the job's later steps, the Chrome
# that a driven test runs when its driver meets a browser (trystero's interop lane), on Linux, X64
# and ARM64.
#
# Usage, from the superproject's root, with the variables a runner sets (RUNNER_OS, RUNNER_ARCH,
# RUNNER_TEMP, GITHUB_ENV): install.sh
#
# The version is the Stable channel of Chrome for Testing's
# last-known-good-versions-with-downloads.json when it was pinned, and each build's URL is the one
# that JSON lists. Google publishes no SHA-256 of its archives: each digest below is the one of the
# archive downloaded twice, which also matched the MD5 Google's storage states for it
# (x-goog-hash). The headless shell, unlike a full Chrome, sends nothing to Google on its own
# (measured), and it is the same program on every run of a commit, never the image's Chrome,
# which moves with the image.
#
# CHROME is a wrapper that runs the shell with --no-sandbox, a decision kept until it is measured on
# a runner. The shell's sandbox needs unprivileged user namespaces, which Ubuntu 24.04 grants
# through AppArmor only to programs that have a profile (the image's own Chrome has one, a program
# under .local has none), and its archive holds no setuid chrome-sandbox to fall back on. Measured
# in an Ubuntu 24.04 container under Docker, as an unprivileged user, the shell stops ("No usable
# sandbox!") without the flag and runs with it; Docker refuses those namespaces for a reason of its
# own, so this shows the symptom, not the runner's AppArmor, which no run has yet shown.
#
# The threat model: the sandbox confines a renderer against a hostile page. The shell here loads
# only the interop driver's own pages, served on 127.0.0.1, and resolves no other host (the
# driver's --host-resolver-rules map every name but 127.0.0.1 to nothing), so no page it can reach
# is anyone else's. The two options that keep the sandbox, to measure after the first CI run, are
# an AppArmor profile that grants userns to this shell alone (installed with sudo apparmor_parser),
# and CHROME_DEVEL_SANDBOX naming the image's setuid helper, /opt/google/chrome/chrome-sandbox.
set -euo pipefail

version=155.0.8059.39
base="https://storage.googleapis.com/chrome-for-testing-public/${version}"
case "${RUNNER_OS-}-${RUNNER_ARCH-}" in
    Linux-X64)
        build=linux64
        sha256=39dcb8c46550632a3d911850ab3b8af840b4e3f6d8622faa2018eb8756278786
        ;;
    Linux-ARM64)
        build=linux-arm64
        sha256=9fb86f7c0b2734c5febc0bbb4e85f37da43553f3f8a7970949828c5713e87e94
        ;;
    *)
        printf 'install.sh: no chrome-headless-shell %s is pinned for %s on %s: the action ' \
            "${version}" "${RUNNER_OS-}" "${RUNNER_ARCH-}" >&2
        printf 'runs on Linux, on X64 and ARM64\n' >&2
        exit 1
        ;;
esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
asset="chrome-headless-shell-${build}.zip"
"${here}/../../download.sh" "${base}/${build}/${asset}" "${sha256}" "${RUNNER_TEMP}/${asset}"
rm -rf .local/chrome-headless-shell
mkdir -p .local/chrome-headless-shell
unzip -q "${RUNNER_TEMP}/${asset}" -d .local/chrome-headless-shell
rm "${RUNNER_TEMP}/${asset}"
directory="$(cd ".local/chrome-headless-shell/chrome-headless-shell-${build}" && pwd -P)"
shell="${directory}/chrome-headless-shell"
[ -x "${shell}" ] || {
    printf 'install.sh: %s holds no chrome-headless-shell-%s/chrome-headless-shell\n' "${asset}" \
        "${build}" >&2
    rm -rf .local/chrome-headless-shell
    exit 1
}
wrapper="$(cd .local/chrome-headless-shell && pwd -P)/chrome"
{
    printf '#!/bin/sh\n'
    printf '# Written by tools/ci/actions/chrome: chrome-headless-shell %s, without its sandbox ' \
        "${version}"
    printf '(install.sh says why).\n'
    printf 'exec "%s" --no-sandbox "$@"\n' "${shell}"
} > "${wrapper}"
chmod 755 "${wrapper}"
printf 'CHROME=%s\n' "${wrapper}" >> "${GITHUB_ENV}"
printf 'install.sh: chrome-headless-shell %s in %s, CHROME=%s\n' "${version}" "${directory}" \
    "${wrapper}"
