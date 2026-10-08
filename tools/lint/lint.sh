#!/usr/bin/env bash
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

# Lint the superproject and every library of libs/.
#
# The files it reads are those of the superproject's repository and of each library's own
# (a submodule, or a clone not yet registered as one): what git tracks, and what it would track
# (untracked and not ignored), so that a new file is linted before it is added.
#
# clang-format and clang-tidy come from a pinned wasi-sdk, so that every machine and the CI
# runners lint with one version. Several rules have no clang-tidy check that expresses them and
# are enforced here by pattern, each printing what it looked for when it fires: the ban on
# io_context::run, run_one and run_for, the ban on fluent chains, the ban on a function other
# than an assignment operator returning *this, and that no library header names a real clock,
# a file, a socket, a process, a thread, the environment or the system's entropy. Others are
# webcpp's own: the licence notice every source file opens with, the word that must never
# appear, the em dash, the layout of JSON literals, that a library's test and example Jamfiles
# declare their programs only with tools/webcpp.jam's rules, that a Doc Comment uses only the
# commands MrDocs renders and puts no colon after a reference, which MrDocs drops, that every
# Python file passes Pyright, keeps to 100 columns and has two blank lines before a top-level def
# or class, and that a comment of a Jam file keeps to 80 columns.
#
# clang-tidy reads the compilation database of tools/lint/compile_commands.py: what b2 compiles
# for the libraries' tests and examples, natively and with the host's default toolset, and, for
# a source that no native program compiles, as the first WASI target that compiles it does
# (wasip2, else wasip3), with wasi-sdk's clang++, the one compiler of a WebAssembly command the
# database accepts; plus each library's aggregate translation unit, through which every public
# header is analysed: natively, and again as b2 compiles it with exception-handling=off, with
# the handler tools/throw_exception.cpp, so that what only a build without exceptions compiles
# is analysed too; or, for a library whose headers build only for WASI, on wasip2 and on
# wasip3. That database leaves out a source b2 expects not to compile (webcpp.compile-fail), and
# one that must stop with the error it states (webcpp.compile-diagnostic): an analysis would stop
# at the error the test exists to show. Each is left out of clang-tidy only,
# the one rule that compiles: clang-format and the rules that read text read it like any other
# C++ file. A run-fail test's sources compile, and are analysed. A source that only some targets
# build (a native_only.cpp that stops with #error for WASI) is analysed as the first of them
# builds it.
#
# clang-tidy is most of the lint's time, so it can be split: --shard K/N analyses the K-th of N
# interleaved slices of the files and runs every other rule as before. The N shards together
# analyse every file once; the CI runs them as N jobs.
#
# Pyright is pinned in tools/lint/package.json and package-lock.json, and installed by npm ci
# the first time the lint runs, or when the pin changes, through tools/node/install.py: under
# tools/lint/.node-modules/, linked at tools/lint/node_modules, so that two lints at once never
# install over each other. Node is a prerequisite.
#
# Usage: tools/lint/lint.sh --clang-format <path> --clang-tidy <path> [--shard K/N]
# Exit 0 when every rule passes, 1 when one fails (each named on a line `lint: failed: <rule>`),
# 2 on a usage error.
set -euo pipefail

# A shell with CPATH set (Homebrew does) makes the compiler and clang-tidy search it first,
# finding a Boost that is not the configured one without a word. The Jamroot refuses a b2 run
# with it set, but clang-tidy is run here directly.
unset CPATH CPLUS_INCLUDE_PATH C_INCLUDE_PATH

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

usage() {
    printf 'lint: %s\n' "$1" >&2
    printf 'usage: tools/lint/lint.sh --clang-format <path> --clang-tidy <path> [--shard K/N]\n' >&2
    exit 2
}

clang_format=''
clang_tidy=''
shard='1/1'
while [ "$#" -gt 0 ]; do
    case "$1" in
        --clang-format | --clang-tidy | --shard) [ "$#" -ge 2 ] || usage "$1 takes a value" ;;
        *) usage "unknown argument $1" ;;
    esac
    case "$1" in
        --clang-format) clang_format="$2" ;;
        --clang-tidy) clang_tidy="$2" ;;
        --shard) shard="$2" ;;
    esac
    shift 2
done

[ -n "${clang_format}" ] || usage 'no --clang-format given'
[ -n "${clang_tidy}" ] || usage 'no --clang-tidy given'
[ -x "${clang_format}" ] || usage "--clang-format ${clang_format} is not an executable"
[ -x "${clang_tidy}" ] || usage "--clang-tidy ${clang_tidy} is not an executable"
[[ "${shard}" =~ ^([1-9][0-9]*)/([1-9][0-9]*)$ ]] \
    || usage "--shard takes K/N, two positive integers, not ${shard}"
shard_index="${BASH_REMATCH[1]}"
shard_count="${BASH_REMATCH[2]}"
[ "${shard_index}" -le "${shard_count}" ] || usage "--shard ${shard}: K is greater than N"

cd "${repository_root}"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || usage "${repository_root} is not a git repository; the lint reads the files git lists"

failed_rules=()
current_rule=''

rule() {
    current_rule="$1"
    printf '\n== %s ==\n' "$1"
}

fail() {
    printf 'lint: %s\n' "$1"
    failed_rules+=("${current_rule}")
}

work_directory="$(mktemp -d)"
trap 'rm -rf "${work_directory}"' EXIT

# The repositories: the superproject, and each library of libs/ that is a repository of its own.
repositories=(.)
for library in libs/*/; do
    library="${library%/}"
    if [ -e "${library}/.git" ]; then
        repositories+=("${library}")
    fi
done

# Every file of the repositories that is there, relative to the root, sorted, NUL-separated.
# The index can name a path a move has not been staged for yet, and a submodule is listed as a
# directory; neither is a file. A symbolic link is not read either: its text is a path.
for repository in "${repositories[@]}"; do
    git -C "${repository}" ls-files -z --cached --others --exclude-standard \
        | while IFS= read -r -d '' file; do
              path="${file}"
              if [ "${repository}" != . ]; then
                  path="${repository}/${file}"
              fi
              if [ -f "${path}" ] && [ ! -L "${path}" ]; then
                  printf '%s\0' "${path}"
              fi
          done
done | sort -z -u > "${work_directory}/files"

# The files whose path matches the extended regular expression given, NUL-separated.
files_matching() {
    while IFS= read -r -d '' file; do
        if [[ "${file}" =~ $1 ]]; then
            printf '%s\0' "${file}"
        fi
    done < "${work_directory}/files"
}

files_matching '\.(cpp|hpp)$' > "${work_directory}/sources"
files_matching '\.py$' > "${work_directory}/python"
# The headers of the libraries, and of the fixture libraries that the tests of the build place
# in libs/.
files_matching '^(libs|tools/test/fixtures)/[^/]+/include/.*\.hpp$' > "${work_directory}/headers"

# Runs a command with the files of a list as its last arguments, and nothing when the list is
# empty: grep, clang-format and others read their standard input when given no file.
on_files() {
    local list="$1"
    shift
    [ -s "${list}" ] || return 0
    xargs -0 "$@" < "${list}"
}

# 1. Formatting.
rule 'clang-format'
if on_files "${work_directory}/sources" "${clang_format}" --dry-run -Werror; then
    printf 'every C++ file is formatted\n'
else
    fail 'some C++ files are not formatted; run clang-format -i on them'
fi

# 2. Static analysis, over what b2 would compile.
rule 'clang-tidy'
if python3 tools/lint/compile_commands.py "${repository_root}" \
        "${work_directory}/database/compile_commands.json"; then
    # The files to analyse, each with whether its commands name wasi-sdk's clang++ (wasi) or
    # another compiler (host), and a compiler of the host's, when one is named. compile_commands.py
    # refuses a WebAssembly command of any compiler but wasi-sdk's clang++, so a host command is
    # a native one; both read wasi-sdk's clang++ with its function wasi_sdk.
    # A file of both kinds fails the rule, by name, and the rules after it still run.
    if python3 - tools/lint "${work_directory}/database/compile_commands.json" \
            "${work_directory}/analysed" > "${work_directory}/compiler" <<'PYTHON'; then
import json
import sys

sys.path.insert(0, sys.argv[1])

from compile_commands import wasi_sdk

with open(sys.argv[2]) as opened:
    entries = json.load(opened)
kinds = {}
for entry in entries:
    kind = 'wasi' if wasi_sdk(entry['arguments'][0]) else 'host'
    if kinds.setdefault(entry['file'], kind) != kind:
        sys.exit(f'lint: {entry["file"]} is compiled both by wasi-sdk\'s clang++ and by '
                 'another compiler; clang-tidy reads one --target for it')
with open(sys.argv[3], 'w') as analysed:
    for file in sorted(kinds):
        print(f'{kinds[file]} {file}', file=analysed)
hosts = [entry['arguments'][0] for entry in entries if kinds[entry['file']] == 'host']
print(hosts[0] if hosts else '')
PYTHON

        # The native commands name the host's compiler, which knows where its own system headers
        # are; the wasi-sdk clang-tidy that reads them does not. It is told the target of that
        # compiler and, on macOS, the SDK: facts about the machine the analysis runs on, not build
        # flags. A command of wasi-sdk's clang++ (a program or an aggregate built only for WASI)
        # names its own --target, and its sysroot is the one clang-tidy's wasi-sdk knows: it is
        # told neither.
        host_target=''
        host_sysroot=''
        if [ -n "$(cat "${work_directory}/compiler")" ]; then
            host_target="$("$(cat "${work_directory}/compiler")" -dumpmachine)"
            if [ "$(uname -s)" = Darwin ] && command -v xcrun >/dev/null 2>&1; then
                host_sysroot="$(xcrun --show-sdk-path)"
            fi
        fi

        # clang-tidy reads one file per run and takes seconds on one that includes Boost, so the
        # files are analysed in parallel. Each run's findings are kept in a file of their own and
        # printed in the order of the sorted files, so that the report reads the same on every run.
        # The bash -c of xargs, below, runs it.
        # shellcheck disable=SC2329
        tidy_one() {
            local index="$1" kind="$2" file="$3"
            local arguments=(-p "${work_directory}/database")
            if [ "${kind}" = host ]; then
                arguments+=("--extra-arg=--target=${host_target}")
                if [ -n "${host_sysroot}" ]; then
                    arguments+=(--extra-arg=-isysroot "--extra-arg=${host_sysroot}")
                fi
            fi
            local status=0
            "${clang_tidy}" --quiet "${arguments[@]}" "${file}" \
                > "${work_directory}/${index}.out" 2>&1 || status=$?
            printf '%s\n' "${status}" > "${work_directory}/${index}.status"
        }
        export -f tidy_one
        export clang_tidy host_target host_sysroot work_directory

        # This shard's slice: the files whose position in the sorted list is K modulo N.
        # Interleaving keeps the slices alike, since neighbours are alike (the examples of one
        # directory, the tests of another).
        listed=0
        analysed=0
        while IFS=' ' read -r kind file; do
            listed=$((listed + 1))
            [ $(((listed - 1) % shard_count + 1)) -eq "${shard_index}" ] || continue
            analysed=$((analysed + 1))
            printf '%s\n' "${file}" >> "${work_directory}/slice"
            printf '%s\0%s\0%s\0' "${analysed}" "${kind}" "${file}"
        done < "${work_directory}/analysed" > "${work_directory}/plan"

        if [ "${analysed}" -gt 0 ]; then
            xargs -0 -n 3 -P "$(getconf _NPROCESSORS_ONLN)" bash -c 'tidy_one "$@"' tidy \
                < "${work_directory}/plan"
        fi
        # clang-tidy exits 1 on a finding. Any other failing status is a run that did not finish
        # (a crash, or the kernel ending it for memory) and that analysed nothing; it is named, so
        # that it does not read as a finding. A file with more than one command (a source two
        # programs compile with different options) is analysed once per command, and clang-tidy then
        # says which run it is on; those lines are left out.
        tidy_failed=0
        index=0
        while [ "${index}" -lt "${analysed}" ]; do
            index=$((index + 1))
            grep -vE '^\[[0-9]+/[0-9]+\] \([0-9]+/[0-9]+\) Processing file ' \
                "${work_directory}/${index}.out" || true
            status="$(cat "${work_directory}/${index}.status")"
            if [ "${status}" -gt 1 ]; then
                printf 'clang-tidy ended with status %s on %s\n' "${status}" \
                    "$(sed -n "${index}p" "${work_directory}/slice")"
            fi
            [ "${status}" -eq 0 ] || tidy_failed=1
        done
        # A translation unit that does not compile is not analysed: clang-tidy reports the error,
        # then runs its checks on what error recovery made of the rest, where a type it could not
        # find reads as int, and what they report there is an artefact. A missing header is a
        # broken setup, not a finding.
        units="translation units"
        [ "${analysed}" -ne 1 ] || units="translation unit"
        if [ "${analysed}" -gt 0 ] \
            && grep -qF '[clang-diagnostic-error]' "${work_directory}"/*.out; then
            fail 'a translation unit does not compile (its [clang-diagnostic-error] above); the
          other findings in it are artefacts of that'
        elif [ "${tidy_failed}" -ne 0 ]; then
            fail 'clang-tidy reported a finding'
        elif [ "${shard_count}" -eq 1 ]; then
            printf 'clang-tidy is clean (%d %s)\n' "${analysed}" "${units}"
        else
            printf 'clang-tidy is clean (%d of %d translation units, shard %s)\n' \
                "${analysed}" "${listed}" "${shard}"
        fi
    else
        fail "a file of the compilation database is compiled both by wasi-sdk's clang++ and by
      another compiler (above), so nothing was analysed"
    fi
else
    fail 'compile_commands.py wrote no compilation database (above), so nothing was analysed'
fi

# 3. The rules clang-tidy cannot express.

# 3a. io_context::run, run_one and run_for block under the work guard, so the drivers may never
#     call them. The ban is on the Asio object, not on the spelling: a scheduler of a library's
#     own may have a run_one, and calling it is the whole point. Each file that declares an
#     io_context is searched for calls on that object by the name it was given.
rule 'io_context::run'
blocking_calls="$(while IFS= read -r -d '' file; do
    { grep -oE 'boost::asio::io_context[[:space:]]+[A-Za-z_][A-Za-z0-9_]*' "${file}" || true; } \
        | awk '{ print $NF }' | sort -u | while IFS= read -r object; do
        [ -n "${object}" ] || continue
        { grep -nE "(^|[^A-Za-z0-9_])${object}\.(run|run_one|run_for)\(" "${file}" || true; } \
            | sed "s|^|${file}:|"
    done
    { grep -nE 'io_context::(run|run_one|run_for)\b' "${file}" || true; } | sed "s|^|${file}:|"
done < "${work_directory}/sources")"
if [ -n "${blocking_calls}" ]; then
    printf '%s\n' "${blocking_calls}"
    fail 'io_context::run, run_one and run_for are banned; poll and poll_one are the drivers'
else
    printf 'no io_context::run, run_one or run_for\n'
fi

# 3b. A fluent chain is three or more calls in one expression. One accessor followed by one
#     call is allowed, which is why the pattern needs three.
rule 'fluent chains'
fluent_chains="$(on_files "${work_directory}/sources" grep -nHE \
    '\.[a-z_]+\([^()]*\)\.[a-z_]+\([^()]*\)\.[a-z_]+\(' || true)"
if [ -n "${fluent_chains}" ]; then
    printf '%s\n' "${fluent_chains}"
    fail 'fluent chains are banned; bind long-lived collaborators to named references'
else
    printf 'no fluent chains\n'
fi

# 3c. A function that returns *this is a fluent interface unless it is an assignment operator.
#     The nearest preceding signature decides.
rule 'returns *this'
# The program is awk's, and its $ are awk's fields.
# shellcheck disable=SC2016
self_returns="$(on_files "${work_directory}/sources" awk '
    /\(/ { signature = $0 }
    /return \*this;/ {
        if (signature !~ /operator[ ]*=/) { printf "%s:%d: %s\n", FILENAME, FNR, $0 }
    }' || true)"
if [ -n "${self_returns}" ]; then
    printf '%s\n' "${self_returns}"
    fail 'a function other than an assignment operator returns *this'
else
    printf 'nothing returns *this outside an assignment operator\n'
fi

# 4. The em dash is banned in every file, not only in C++.
rule 'em dash'
# The pattern is written as the UTF-8 bytes of U+2014 so that this script does not contain the
# character it bans.
em_dash=$'\xe2\x80\x94'
em_dashes="$(on_files "${work_directory}/files" grep -nHI "${em_dash}" || true)"
if [ -n "${em_dashes}" ]; then
    printf '%s\n' "${em_dashes}"
    fail 'the em dash character is banned; use a plain dash'
else
    printf 'no em dash character\n'
fi

# 5. JSON written in a raw string literal is laid out for its reader: a literal that opens a
#    line with `R"({` or `R"([` has its members four spaces deeper than that line, and closes
#    at its indentation.
rule 'JSON literals'
# The program is awk's, and its $ are awk's fields.
# shellcheck disable=SC2016
misaligned="$(on_files "${work_directory}/sources" awk '
    function indent(line) { match(line, /^ */); return RLENGTH }
    FNR == 1 { state = 0 }
    state == 1 {
        if (indent($0) != base + 4) {
            print FILENAME ":" opened ": the members are not four spaces deeper than the line" \
                " that opens the literal"
        }
        state = 2
    }
    state == 2 && /^ *[]}]\)"/ {
        if (indent($0) != base) {
            print FILENAME ":" opened ": the literal does not close at the indentation of the" \
                " line that opens it"
        }
        state = 0
    }
    /R"\([[{]$/ { opened = FNR; base = indent($0); state = 1 }
' || true)"
if [ -n "${misaligned}" ]; then
    printf '%s\n' "${misaligned}"
    fail 'lay JSON literals out with their members four spaces deeper than their opening line'
else
    printf 'every JSON literal is laid out\n'
fi

# 6. The licence notice: every source file (C++, JavaScript, Python, shell, Jam, YAML) opens with
#    it, after a #! line when it has one (tools/lint/rules.py).
rule 'licence notice'
if python3 tools/lint/rules.py licence < "${work_directory}/files"; then
    printf 'every source file opens with the licence notice\n'
else
    fail 'every source file opens with the WebCpp.org licence notice'
fi

# 7. The word that must never appear: not in a file, not in a file name, and not in a commit
#    (its author, its committer or its message) of any of the repositories. The brackets keep
#    this script from matching its own pattern.
rule 'banned word'
banned='veru[s]'
in_content="$(on_files "${work_directory}/files" grep -nHIiE "${banned}" || true)"
in_names="$(tr '\0' '\n' < "${work_directory}/files" | grep -iE "${banned}" || true)"
in_history="$(for repository in "${repositories[@]}"; do
    git -C "${repository}" rev-parse --verify -q HEAD >/dev/null || continue
    git -C "${repository}" log -i -E --grep="${banned}" --format="${repository}: commit %h: %s"
    git -C "${repository}" log -i -E --author="${banned}" \
        --format="${repository}: commit %h: author %an <%ae>"
    git -C "${repository}" log -i -E --committer="${banned}" \
        --format="${repository}: commit %h: committer %cn <%ce>"
done)"
if [ -n "${in_content}" ]; then
    printf '%s\n' "${in_content}"
    fail 'a file contains the banned word'
fi
if [ -n "${in_names}" ]; then
    printf '%s\n' "${in_names}"
    fail 'a file name contains the banned word'
fi
if [ -n "${in_history}" ]; then
    printf '%s\n' "${in_history}"
    fail 'a commit (its author, committer or message) contains the banned word'
fi
if [ -z "${in_content}" ] && [ -z "${in_names}" ] && [ -z "${in_history}" ]; then
    printf 'the banned word appears nowhere\n'
fi

# 8. A library reads no clock, disk or network, and starts no process: no header of a library
#    names a real clock, a file, a socket or a process API, nor a thread, the process's
#    environment or the system's entropy, unless that is the library's purpose. A name is
#    matched wherever it appears, not only in an include, since a header can reach one through
#    another's include. A line that names one without reaching the world, as a simulated clock
#    would, or that reaches it because that is the library's purpose, says why after
#    `lint-world:`.
rule 'no clock, disk or network'
world_apis=(
    # Clocks: std::chrono's, and C's time and clock.
    '(system|steady|high_resolution|utc|tai|gps|file)_clock'
    '(^|[^_[:alnum:].>])(time|clock|gettimeofday|clock_gettime|timespec_get)\('
    '<(ctime|time\.h|sys/time\.h)>'
    'boost/(chrono|date_time|timer)[/.]'
    '(steady|system|high_resolution|deadline)_timer'
    # Threads, which wait on the real clock or run beside the scheduler.
    '<thread>'
    '(^|[^_[:alnum:]])std::j?thread([^_[:alnum:]]|$)'
    'this_thread::'
    # Files.
    '<(fstream|filesystem|fcntl\.h|sys/stat\.h|dirent\.h|sys/mman\.h)>'
    'boost/(filesystem|iostreams|interprocess|nowide)[/.]'
    '(^|[^_[:alnum:]])(fopen|freopen|tmpfile|opendir|mmap)\('
    '(^|[^_[:alnum:]])(basic_)?[io]?fstream([^_[:alnum:]]|$)'
    '(^|[^_[:alnum:]])(basic_)?filebuf([^_[:alnum:]]|$)'
    '(^|[^_[:alnum:]>])::(open|openat|creat)\('
    # The filesystem library by name, which a header can reach through another's include: a
    # call through it, and an alias or a using of it.
    '(^|[^_[:alnum:]])filesystem::'
    '(std|boost|experimental)::filesystem([^_[:alnum:]]|$)'
    # Sockets, and Boost.Asio whole, whose io_context waits on them.
    '<(sys/socket\.h|netinet/[a-z_]+\.h|arpa/inet\.h|netdb\.h|winsock2?\.h)>'
    'boost/asio[/.]'
    'boost/beast[/.]'
    '(^|[^_[:alnum:].>])(socket|getaddrinfo)\('
    # Processes, and the environment a process is started with.
    '<(unistd\.h|spawn\.h|sys/wait\.h)>'
    'boost/process[/.]'
    '(^|[^_[:alnum:].>])(fork|vfork|execl|execlp|execle|execv|execvp|execvpe|posix_spawn|popen)\('
    'std::system\('
    '(^|[^_[:alnum:].>])(secure_)?getenv\('
    # Entropy, which a run cannot repeat.
    'random_device'
)
world_pattern="$(IFS='|'; printf '%s' "${world_apis[*]}")"
world_reached="$(on_files "${work_directory}/headers" grep -nHE -e "${world_pattern}" \
    | grep -v 'lint-world:' || true)"
if [ -n "${world_reached}" ]; then
    printf '%s\n' "${world_reached}"
    fail "a header names a real clock, a file, a socket, a process, a thread, the environment or
      the entropy; say why after lint-world: if it reaches none, or if that is the library's
      purpose"
else
    printf 'no header names a clock, a file, a socket, a process, a thread, the environment or'
    printf ' the entropy\n'
fi

# 9. A library's test and example Jamfiles declare their programs with tools/webcpp.jam's rules,
#    which build each only for the targets it declares and add what every program needs; b2's
#    own run, run-fail, compile, compile-fail, exe and unit-test do neither (tools/lint/rules.py).
rule 'raw b2 rules'
if python3 tools/lint/rules.py raw-rules < "${work_directory}/files"; then
    printf 'every test and example Jamfile declares its programs with webcpp.*\n'
else
    fail 'a test or example Jamfile declares a program with a raw b2 rule'
fi

# 10. A Doc Comment uses only the commands webcpp allows, each of which MrDocs renders; MrDocs
#     drops the others without a word. A literal @ is written \@. No colon follows a reference,
#     @ref or \ref, since MrDocs drops it too (tools/lint/rules.py).
rule 'Doc Comments'
if python3 tools/lint/rules.py doc-comments < "${work_directory}/sources"; then
    printf 'every Doc Comment uses only the allowed commands, and no colon after a reference\n'
else
    fail 'a Doc Comment uses a command webcpp does not allow, a bare @, or @ref with a colon'
fi

# 11. Pyright, over every Python file, with the root's pyrightconfig.json: a warning fails as an
#     error does. It is installed on first use, and again when the pin changes.
rule 'Pyright'
# The version of the package.json given, or of the dependency named after it.
version_of() {
    python3 -c 'import json, sys; package = json.load(open(sys.argv[1]))
print(package["dependencies"][sys.argv[2]] if sys.argv[2:] else package["version"])' "$@"
}
pinned="$(version_of tools/lint/package.json pyright)"
installed="$(version_of tools/lint/node_modules/pyright/package.json 2>/dev/null || true)"
pyright_ready=1
if [ "${installed}" != "${pinned}" ]; then
    printf 'installing Pyright %s with npm ci for tools/lint\n' "${pinned}"
    if ! command -v npm >/dev/null 2>&1; then
        pyright_ready=0
        fail 'npm is not on PATH; Node is a prerequisite of the lint'
    elif ! python3 tools/node/install.py tools/lint; then
        pyright_ready=0
        fail 'npm ci could not install Pyright in tools/lint'
    fi
fi
if [ "${pyright_ready}" -eq 1 ]; then
    if [ ! -s "${work_directory}/python" ]; then
        printf 'no Python file\n'
    elif on_files "${work_directory}/python" env FORCE_COLOR=0 \
            tools/lint/node_modules/.bin/pyright --warnings --project pyrightconfig.json; then
        printf 'Pyright is clean\n'
    else
        fail 'Pyright reported an error or a warning'
    fi
fi

# 12. A Python file keeps to 100 columns, the limit .clang-format sets for C++
#     (tools/lint/rules.py).
rule 'Python line length'
if python3 tools/lint/rules.py line-length < "${work_directory}/python"; then
    printf 'every Python line is 100 columns or fewer\n'
else
    fail 'a Python line is longer than 100 columns'
fi

# 13. A top-level def or class of a Python file has two blank lines before it, its decorators
#     and the comments just above it, as PEP 8 lays a module out (tools/lint/rules.py).
rule 'Python blank lines'
if python3 tools/lint/rules.py blank-lines < "${work_directory}/python"; then
    printf 'every top-level def and class has two blank lines before it\n'
else
    fail 'a top-level def or class has other than two blank lines before it'
fi

# 14. A comment of a Jam file keeps to 80 columns, the width Jam comments are wrapped at; its
#     code may run longer (tools/lint/rules.py).
rule 'Jam comment width'
if python3 tools/lint/rules.py jam-comments < "${work_directory}/files"; then
    printf 'every Jam comment is 80 columns or fewer\n'
else
    fail 'a Jam comment is longer than 80 columns; wrap it as its neighbours are'
fi

# 15. A library's include boundaries: libs/<name>/meta/include-boundaries.json, when a library
#     has one, names boundaries, each a set of headers (a headers glob, less an except glob,
#     each anchored to the whole path relative to libs/<name>/ and matched segment by segment
#     with Python's fnmatch, so * stays within one path segment and never reaches a deeper one)
#     that must not #include <...> or #include "..." a path starting with one of its
#     must-not-include prefixes. A violation fails at its line, with the boundary's why; a
#     malformed file (an unknown or a missing key, a non-string element, an empty why), or a
#     glob that matches no file of the library fails, naming the file (tools/lint/rules.py).
#     This generalises xstate-cpp's rule 3d, which kept the machine core free of xactor and of
#     the actor layer; its "replaced documents" rule guarded a history that does not exist here,
#     and is not carried.
rule 'include boundaries'
if python3 tools/lint/rules.py include-boundaries < "${work_directory}/files"; then
    printf 'every library keeps to its declared include boundaries\n'
else
    fail 'a library crosses an include boundary its meta/include-boundaries.json declares'
fi

printf '\n'
if [ "${#failed_rules[@]}" -eq 0 ]; then
    printf 'lint: clean\n'
    exit 0
fi
printf 'lint: failed: %s\n' "${failed_rules[@]}" | uniq
exit 1
