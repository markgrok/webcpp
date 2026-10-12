#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# The steps of tools/ci/actions/boost: Boost 1.92.0's headers and its b2, built from the source
# archive and installed in a prefix that the action caches, on Linux, macOS and Windows.
#
# Usage, from the superproject's root, with the variables a runner sets (RUNNER_OS, RUNNER_ARCH,
# RUNNER_TEMP, GITHUB_OUTPUT, GITHUB_PATH):
#
#   install.sh key                writes the prefix and the cache key to GITHUB_OUTPUT;
#   install.sh install <prefix>   downloads the archive, checks its SHA-256, builds b2 with
#                                 bootstrap, and installs the headers (--with-headers) and b2 in
#                                 <prefix>, and fails when <prefix> then lacks either, before the
#                                 action caches it;
#   install.sh configure <prefix> writes .local/user-config.jam with the `using boost` line of
#                                 <prefix>, and puts <prefix>/bin, where b2 is, on PATH;
#   install.sh source <directory> fills <directory> with what install keeps in <prefix>/source,
#                                 for a machine whose Boost has no sources.
#
# The headers are installed, and beside them, in <prefix>/source, the sources of Boost's compiled
# libraries, from which webcpp builds those it needs (the Jamroot's /webcpp//boost_url,
# boost_charconv and boost_locale).
set -euo pipefail

version=1.92.0
# The gzip archive, which every runner's tar reads by itself: Windows Server 2022's tar.exe has no
# bzip2, and hangs on the bzip2 archive.
archive=boost_1_92_0.tar.gz
url="https://archives.boost.io/release/${version}/source/${archive}"
sha256=c4a3b310ddd2472416e091067166b0713be97c63f38c212c484ada022fd296ce

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The functions every action shares: digest, mixed, configuration, compiler_identity.
# shellcheck source=SCRIPTDIR/../../helpers.sh
. "${here}/../../helpers.sh"

# The file that install.sh writes last into a tree of Boost's sources it made, with the version
# and the archive's SHA-256: the one sign that a directory is such a tree, which it may replace.
marker=.webcpp-boost-source

# What install.sh made and removes when it ends, however it ends: the extracted archive, a tree
# it was filling, the tree it replaced.
made=()
trap 'rm -rf ${made[@]+"${made[@]}"}' EXIT

# Stops, before anything is downloaded, when destination exists and holds no marker: a directory
# that install.sh did not write, such as one of the user's, an installed Boost's include directory
# or a whole Boost tree, is never replaced.
refuse_foreign() {
    if [ -e "$1" ] && [ ! -f "$1/${marker}" ]; then
        printf 'install.sh: %s exists and holds no %s, so install.sh did not write it, and it %s' \
            "$1" "${marker}" 'is left as it is; if it is a tree of Boost'"'"'s sources that you' >&2
        printf ' no longer need, remove it yourself and run install.sh source again\n' >&2
        exit 1
    fi
}

# Copies into destination what webcpp builds Boost's compiled libraries from: boost/version.hpp,
# which the Jamroot compares with the configured Boost's, every libs/<library>/src of the source
# tree, and last the marker. It fills a sibling of its own first and swaps it into place, so that
# a build reading the old tree never sees half of the new one.
keep_sources() {
    local tree="$1" destination="${2%/}"
    refuse_foreign "${destination}"
    mkdir -p "$(dirname "${destination}")"
    local filling
    filling="$(mktemp -d "${destination}.filling.XXXXXX")"
    made+=("${filling}")
    chmod 755 "${filling}"
    mkdir "${filling}/boost" "${filling}/libs"
    cp "${tree}/boost/version.hpp" "${filling}/boost/version.hpp"
    local src library
    for src in "${tree}"/libs/*/src; do
        [ -d "${src}" ] || continue
        library="$(basename "$(dirname "${src}")")"
        mkdir "${filling}/libs/${library}"
        cp -R "${src}" "${filling}/libs/${library}/src"
    done
    printf '# Written by tools/ci/actions/boost/install.sh, which may replace this tree.\n' \
        > "${filling}/${marker}"
    printf 'version=%s\nsha256=%s\n' "${version}" "${sha256}" >> "${filling}/${marker}"
    if [ -e "${destination}" ]; then
        local old
        old="$(mktemp -d "${destination}.old.XXXXXX")"
        made+=("${old}")
        mv "${destination}" "${old}/tree"
    fi
    mv "${filling}" "${destination}"
}

# Fills directory with the sources install keeps, from the same archive, checked the same way: a
# machine's .local/boost-source, where the Jamroot looks when no BOOST_SOURCE is given.
source_tree() {
    local directory="${1%/}"
    refuse_foreign "${directory}"
    local work
    # Named in full: macOS's mktemp -d alone ignores TMPDIR.
    work="$(mktemp -d "${TMPDIR:-/tmp}/webcpp-boost-source.XXXXXX")"
    made+=("${work}")
    "${here}/../../download.sh" "${url}" "${sha256}" "${work}/${archive}"
    tar -xzf "${work}/${archive}" -C "${work}"
    keep_sources "${work}/boost_${version//./_}" "${directory}"
}

key() {
    # The image is part of the key: b2 is a native program, and one built on a newer image need
    # not run on an older one. So are this action's files: a change to how Boost is installed
    # installs it again.
    local image
    # The os-release of the runner, which shellcheck cannot read.
    # shellcheck source=/dev/null
    case "${RUNNER_OS}" in
        Linux) image="$(. /etc/os-release && printf '%s-%s' "${ID}" "${VERSION_ID}")" ;;
        macOS) image="macos-$(sw_vers -productVersion | cut -d . -f 1)" ;;
        *) image="${ImageOS:-windows}" ;;
    esac
    local files
    files="$(digest "${here}/action.yml" "${here}/install.sh" "${here}/../../download.sh" \
        "${here}/../../helpers.sh")"
    printf 'prefix=%s\n' "$(mixed "${RUNNER_TEMP}")/boost-${version}" >> "${GITHUB_OUTPUT}"
    printf 'key=boost-%s-%s-%s-%s\n' "${version}" "${image}" "${RUNNER_ARCH}" \
        "${files:0:16}" >> "${GITHUB_OUTPUT}"
}

install() {
    local prefix="$1"
    # RUNNER_TEMP is a Windows path there, D:\a\_temp, which Git's bash reads as /d/a/_temp.
    local temp="${RUNNER_TEMP}"
    if [ "${RUNNER_OS}" = Windows ]; then
        temp="$(cygpath -u "${RUNNER_TEMP}")"
    fi
    local work="${temp}/boost-source"
    rm -rf "${work}"
    mkdir -p "${work}"
    "${here}/../../download.sh" "${url}" "${sha256}" "${work}/${archive}"
    cd "${work}"
    if [ "${RUNNER_OS}" = Windows ]; then
        # Windows's own tar, libarchive: Git's GNU tar reads a drive letter as a host name.
        "$(cygpath -u "${SYSTEMROOT}")/System32/tar.exe" -xzf "${archive}"
    else
        tar -xzf "${archive}"
    fi
    rm "${archive}"
    cd "boost_${version//./_}"
    keep_sources "$(pwd)" "${prefix}/source"
    local b2=./b2
    if [ "${RUNNER_OS}" = Windows ]; then
        cmd //c bootstrap.bat || { cat bootstrap.log; exit 1; }
        b2=./b2.exe
    else
        ./bootstrap.sh || { cat bootstrap.log; exit 1; }
    fi
    "${b2}" --version
    # Each file installed is a line of b2's output, so only a failure's last lines are shown. The
    # system layout, <prefix>/include/boost, on every runner: Boost's default on Windows is the
    # versioned layout, which puts the headers in <prefix>/include/boost-1_92/boost.
    "${b2}" --prefix="${prefix}" --layout=system --with-headers install \
        > "${work}/headers.log" 2>&1 || { tail -n 50 "${work}/headers.log"; exit 1; }
    # The standard layout, <prefix>/bin/b2 and its build system in <prefix>/share/b2, on every
    # runner: b2's default on Windows is the portable layout, which ignores --bindir and puts b2
    # in <prefix> itself.
    (cd tools/build && "../../${b2}" --prefix="${prefix}" --bindir="${prefix}/bin" \
        b2-install-layout=standard install) \
        > "${work}/b2.log" 2>&1 || { tail -n 50 "${work}/b2.log"; exit 1; }
    cd "${temp}"
    rm -rf "${work}"
    check "${prefix}"
    "${prefix}/bin/${b2#./}" --version
}

# Whether prefix holds what configure uses: Boost's headers in <prefix>/include/boost, b2 in
# <prefix>/bin, and in <prefix>/source the tree keep_sources writes for this archive (its marker
# names the archive's SHA-256) with the sources of each compiled library the Jamroot builds
# (tools/boost/Jamfile). So a prefix cached before it kept them, or before it kept one of them, is
# refused here, and not at the first build that needs them.
check() {
    local prefix="$1"
    local b2="${prefix}/bin/b2"
    [ "${RUNNER_OS-}" != Windows ] || b2="${b2}.exe"
    local missing=
    if [ ! -f "${prefix}/include/boost/version.hpp" ] || [ ! -x "${b2}" ] \
        || [ ! -f "${prefix}/source/boost/version.hpp" ]; then
        missing=1
    elif ! grep -q "^sha256=${sha256}\$" "${prefix}/source/${marker}" 2>/dev/null; then
        missing=1
    else
        local library
        for library in url charconv locale cobalt; do
            [ -d "${prefix}/source/libs/${library}/src" ] || missing=1
        done
    fi
    if [ -n "${missing}" ]; then
        printf 'install.sh: %s holds no Boost headers, no b2 or no sources\n' "${prefix}" >&2
        exit 1
    fi
}

configure() {
    local prefix="$1"
    check "${prefix}"
    mkdir -p .local
    {
        printf '# Written by tools/ci/actions/boost: Boost %s, installed in %s.\n' \
            "${version}" "${prefix}"
        printf 'using boost : 1.92 : <include>"%s/include" <library>"%s/lib" ;\n' \
            "${prefix}" "${prefix}"
        printf 'modules.poke : BOOST_SOURCE : "%s/source" ;\n' "${prefix}"
    } > .local/user-config.jam
    cat .local/user-config.jam
    if [ "${RUNNER_OS}" = Windows ]; then
        cygpath -w "${prefix}/bin" >> "${GITHUB_PATH}"
    else
        printf '%s/bin\n' "${prefix}" >> "${GITHUB_PATH}"
    fi
}

usage() {
    printf 'usage: install.sh key | install <prefix> | configure <prefix> | source <directory>\n' \
        >&2
    exit 2
}

# A prefix is required, and absolute: b2 given an empty --prefix installs in /usr/local.
require_prefix() {
    case "${1-}" in
        /* | [A-Za-z]:/*) ;;
        *) usage ;;
    esac
}

case "${1-}" in
    key) key ;;
    install)
        require_prefix "${2-}"
        install "$2"
        ;;
    configure)
        require_prefix "${2-}"
        configure "$2"
        ;;
    source)
        [ -n "${2-}" ] || usage
        source_tree "$2"
        ;;
    *) usage ;;
esac
