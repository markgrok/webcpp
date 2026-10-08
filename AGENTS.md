# Working on webcpp

This is webcpp's rulebook. It is written for coding agents and human
contributors alike, and it holds every rule needed to port a library to
webcpp or to change one: an agent with no other context ports a library by
following it. Each library's own `AGENTS.md` (`libs/<name>/AGENTS.md`) holds
only what is specific to that library: the original and its version, how its
oracle drives the original, its particular cautions. Read this file first,
then the library's.

This file describes the tree as it is. What is still to come is listed in
the roadmap (chapter 13), to which every other mention of it refers. Every
command below runs from the superproject's root, in a shell where `CPATH`,
`CPLUS_INCLUDE_PATH` and `C_INCLUDE_PATH` are unset (chapter 12).

## Contents

1. What webcpp is
2. Choosing and registering a port
3. Names
4. Fidelity
5. Evidence: oracle and twins
6. C++ rules
7. Doc Comments and the API reference
8. Documentation
9. Tests, lanes, the report and CI
10. Process
11. Commits and text
12. b2 facts
13. Roadmap

## 1. What webcpp is

webcpp brings to C++ the libraries that are widely used for the web in other
languages. Each library is ported with the help of coding agents and proven
against the original. webcpp follows Boost's guidelines and model: the GitHub
organisation `webcpporg` is the equivalent of `boostorg`, and this
superproject, `webcpporg/webcpp`, is the equivalent of `boostorg/boost`. Every
library is header-only C++20, under the Boost Software License 1.0, in a
repository of its own, checked out here as a submodule under `libs/<name>`.

### The libraries

| Library | What it is | Targets | State |
| --- | --- | --- | --- |
| xactor | a deterministic actor system, webcpp's own | native, wasip2, wasip3 (`xactor_asio` native only) | a submodule at `libs/xactor`; the model for every port |
| xstate | a port of XState 5.33.2's state machines and actors; depends on xactor and Boost.JSON | native, wasip2, wasip3; its oracle lane | a submodule at `libs/xstate`; the first user of the shared oracle (chapter 5) |
| pratt | a Pratt parser engine, generic through concepts, with a calculator built on it, webcpp's own | native, wasip2, wasip3 | a submodule at `libs/pratt`; born with the allocation rule (chapter 6) |
| wasi | a helper for building C++ as WASI HTTP components | wasip2, wasip3 (`response.hpp` also natively) | to come (chapter 13) |
| trystero | a port of Trystero, serverless WebRTC rooms | native, emscripten | to come (chapter 13) |

### The layout

```
webcpp/
  Jamroot             the single build configuration: finds Boost, checks its version,
                      sets what every library shares, registers each library
  AGENTS.md           this rulebook
  README.md           what webcpp is, the prerequisites, getting started
  LICENSE_1_0.txt
  .clang-format       clang-format's style, every repository's
  .clang-tidy         clang-tidy's checks, every repository's
  pyrightconfig.json  Pyright's settings for every Python file
  libs/<name>/        a library: a repository of its own, a submodule here (xactor,
                      xstate, pratt)
  doc/                the index page (index.adoc, Jamfile)
  tools/
    webcpp.jam        the Jamfile API (chapter 9): webcpp.targets, webcpp.run, ...
    throw_exception.cpp  what Boost calls in place of a throw, built without exceptions
    boost_json.cpp    Boost.JSON's definitions, built as /webcpp//boost_json (chapter 2)
    boost_test_runner.cpp  Boost.Test's header-only framework, for webcpp.boost-test (chapter 9)
    oracle/           the shared oracle (chapter 5): oracle.jam, twins.py, compare.py and their
                      tests
    lint/             lint.sh, rules.py, compile_commands.py and their test
    doc/              the documentation toolchain: doc.jam, reference.py, doc_comments.py,
                      doc-check.py, libraries.py, counts.py, the Asciidoctor.js extensions, the
                      style
    example/          run_example.py, which runs an example and compares its output
    report/           report.py, lanes.py, pages.py: the test matrix, and the CI verdict
    test/             the tests of the Jamroot, webcpp.jam, the oracle's rules and the doc build,
                      their harness, and the fixture libraries demo and oracle_demo
    ci/               matrix.py (the lanes), assemble.py (the site), download.sh, and
                      actions/{boost,wasi-sdk,wasmtime,mrdocs,node}/ (chapter 9)
  .github/            workflows/library.yml, workflows/ci.yml, actionlint.yaml (chapter 9)
  .local/             machine-local, git-ignored (below)
  bin/                b2's build directory, git-ignored
```

A library's layout:

```
libs/<name>/
  build.jam                  project /webcpp/<name>: its headers and dependencies
  include/webcpp/<name>.hpp  the convenience header, which includes every public header but
                             one that brings an optional heavy dependency (chapter 3)
  include/webcpp/<name>/...  one header per responsibility
  test/                      Jamfile, the tests, and .clang-tidy when the tests need one
  test/oracle/               a port's oracle (chapter 5): its Jamfile, the pinned original,
                             the scripts that drive it, and the twins
  example/                   Jamfile, the programs and their .expected outputs
  doc/                       Jamfile, the page (<name>.adoc and its sections), mrdocs.yml,
                             and counts.py when the page counts what only it holds (chapter 8)
  meta/libraries.json        Boost's fields, plus "port-of"
  meta/include-boundaries.json
                             the include boundaries the lint checks, when it has any (chapter 6)
  README.md
  AGENTS.md                  only what is specific to this library
  LICENSE_1_0.txt
  LICENSE-<ORIGIN>.txt       the original's notice, for a port that derives from its code
  .gitignore                 doc/html/ at least, and node_modules/ with an oracle
  .gitattributes
  .github/workflows/ci.yml   calls the superproject's library.yml (chapter 9)
```

A library has no Jamroot. It is developed inside a checkout of the
superproject, as a Boost library is developed inside Boost: the superproject's
Jamroot is its build configuration, and `libs/<name>` is its repository.

### Prerequisites

- Boost 1.92 or newer, installed;
- b2 (B2 5.5.3 measured);
- a C++20 compiler;
- Python 3.9 or newer;
- for WebAssembly: wasi-sdk 34 and wasmtime 47 (47.0.3 measured);
- for the documentation: Node, MrDocs 2026.9.29 and clang++;
- for a library's oracle lane: Node and npm, with Boost and a C++ toolset;
- for the lint: wasi-sdk 34's clang-format and clang-tidy, and Node;
- later: Emscripten, wit-bindgen and the `wasi:http` WIT for wasi and
  trystero; OpenSSL for trystero natively.

Each toolchain is installed by hand and configured in `user-config.jam`,
until webcpp bundles the toolchains (chapter 13). b2 reads
`~/user-config.jam`, or the file `--user-config=<file>` names:

```
using clang ;      # or gcc, or msvc: the native toolset
using boost : 1.92 : <include>/opt/homebrew/opt/boost/include <library>/opt/homebrew/opt/boost/lib ;
local wasi-sdk = /path/to/wasi-sdk ;
using clang : wasip2 : $(wasi-sdk)/bin/clang++
  : <cflags>--target=wasm32-wasip2 <cxxflags>--target=wasm32-wasip2 <linkflags>--target=wasm32-wasip2
    <archiver>$(wasi-sdk)/bin/llvm-ar <ranlib>$(wasi-sdk)/bin/llvm-ranlib ;
using clang : wasip3 : $(wasi-sdk)/bin/clang++
  : <cflags>--target=wasm32-wasip3 <cxxflags>--target=wasm32-wasip3 <linkflags>--target=wasm32-wasip3
    <archiver>$(wasi-sdk)/bin/llvm-ar <ranlib>$(wasi-sdk)/bin/llvm-ranlib ;
```

When Boost cannot be used, the build stops before it compiles anything and
prints the exact `using boost` line to add. The Jamroot reads the version of
the configured Boost from its `boost/version.hpp`, with `grep`, or with
`findstr` on Windows, where b2 runs a command with `cmd.exe`, and keys its
cached check on it; a Boost whose `#define BOOST_VERSION <number>` line it
cannot read stops the build too, naming the directory.

**Machine-local setup.** `.local/` is git-ignored and holds what one machine
needs: `.local/user-config.jam`, `.local/wasi-sdk/` and `.local/mrdocs/`. The
tools look there first. `tools/lint/compile_commands.py` runs b2 with
`.local/user-config.jam`, else with the file `$WEBCPP_USER_CONFIG` names,
else with b2's own search. The tests of the build and of the tools read
`.local/user-config.jam`, else the file `$WEBCPP_USER_CONFIG` names, and stop
with an error when neither exists (`tools/test/harness.py`). The doc build
finds MrDocs at `.local/mrdocs/bin/mrdocs`. b2 itself reads it only when told:
`b2 --user-config=.local/user-config.jam ...`.

### The build commands

| Command | What it does |
| --- | --- |
| `b2 test` | every library's tests, natively |
| `b2 example` | every library's examples: each is built, run with its `.input` as its standard input when it has one, and its output compared with its `.expected` |
| `b2 doc` | the index page, `doc/html/index.html`, and every library's page, `libs/<name>/doc/html/index.html` |
| `b2 doc -sWEBCPP_INDEX=site` | the same, with the index linking each page where the site serves it, `libs/<name>/` (chapter 8) |
| `b2 libs/<name>/test` | one library's tests; `libs/<name>/example` and `libs/<name>/doc` likewise |
| `b2 libs/<name>/test//<test>` | one test, while working on it (`scheduler`) |
| `b2 libs/<name>/doc//reference` | one library's API reference alone, MrDocs strict |
| `b2 toolset=clang-wasip2 testing.launcher=wasmtime libs/<name>/test libs/<name>/example` | the same for wasm32-wasip2; `clang-wasip3` for wasm32-wasip3; one toolset per command |
| `b2 install --prefix=<dir>` | copies every library's headers to `<dir>/include/webcpp/` |
| `b2 declared-targets -d0` | prints each `<library> <target>` pair the libraries declare: the CI's lanes |
| `b2 declared-lanes -d0` | prints each `<library> <lane> <directory>` line of a library's own lanes, such as its oracle's (chapter 5) |
| `b2 libs/<name>/test/oracle//oracle` | a port's oracle lane: the original runs the cases and the twins, and the results are compared (chapter 5) |
| `b2 libs/<name>/test/oracle//update-expected` | writes the original's results again, the only writer of an expected result (chapter 5) |
| `b2 -a ...` | any of these from scratch; the only build that counts as evidence |
| `tools/lint/lint.sh --clang-format <wasi-sdk>/bin/clang-format --clang-tidy <wasi-sdk>/bin/clang-tidy` | the lint, of the superproject and every library (chapter 6) |
| `python3 tools/<dir>/<name>_test.py` | a test of the build or of a tool (chapter 10) |
| `python3 tools/ci/matrix.py plan`, `own-lanes`, `lane`, `register`, `report` | the CI's lanes, run the way the CI runs them (chapter 9) |
| `python3 tools/ci/assemble.py --docs . --report <dir> --out <site>` | the site GitHub Pages serves, every link checked (chapter 9) |

## 2. Choosing and registering a port

### Choosing

- **What.** A library widely used for the web in another language, ported at
  an exact version of the original: a tag or a published release, recorded in
  `meta/libraries.json` and in the library's `AGENTS.md`. A port follows that
  version; moving to another one is a change of its own, with its evidence.
- **The licence.** An original under a licence compatible with BSL-1.0 can be
  ported: MIT, BSD and Apache-2.0. GPL cannot. MPL is decided case by case,
  by the owner. A port that derives from the original's code keeps the
  original's notice, unchanged, in `LICENSE-<ORIGIN>.txt` (`LICENSE-XSTATE.txt`,
  `LICENSE-TRYSTERO.txt`), and its README names the parts that derive from
  it. That adds no licence to webcpp's code: every file of webcpp is BSL-1.0
  only, and no repository has a `LICENSE-MIT.txt`. A library of webcpp's own,
  like xactor and pratt, has no `LICENSE-<ORIGIN>.txt`.
- **The name.** `[a-z][a-z0-9_]*`, the name of the original where it has one
  (xstate, trystero). `index` is reserved, in any case: the index page is the
  doc build's page `index`, and the report refuses a library of that name.

### The checklist of a new library

Each item is done before the port's first green CI; the first two are the
owner's:

1. **The repository** `webcpporg/<name>`, public from its first commit, made
   by the owner. An agent never creates a remote repository, never pushes,
   and never changes a GitHub setting. Until the repository exists, the
   library is a local repository at `libs/<name>` (`git init`), which the
   lint and the build already treat as a library.
2. **The submodule**, added by the owner once the repository exists, with a
   URL relative to the superproject's, as Boost's `.gitmodules` writes its
   libraries' (`libs/xactor` is `../xactor.git`), so that a clone fetches
   the libraries over the same protocol as the superproject:

   ```
   git submodule add ../<name>.git libs/<name>
   ```

   Never `git add -A` or `git add libs` in the superproject: a library is a
   repository of its own, and the superproject records only its commit.
3. **`meta/libraries.json`**, Boost's file, with webcpp's `"port-of"`:

   ```json
   {
       "key": "xstate",
       "name": "xstate",
       "authors": ["R"],
       "description": "One sentence that says what the library is.",
       "category": ["State"],
       "maintainers": ["R <github.overboard312@passmail.net>"],
       "cxxstd": "20",
       "port-of": {
           "name": "XState",
           "language": "TypeScript",
           "version": "5.33.2",
           "url": "https://github.com/statelyai/xstate",
           "licence": "MIT"
       }
   }
   ```

   `"port-of"` is `null` for a library of webcpp's own (xactor's is). `name`,
   `description` and `port-of` are required, and every field of `port-of`,
   whose `url` is an `https` URL; `tools/doc/libraries.py` fails the doc build,
   naming the file and the field, otherwise.
4. **`build.jam`**, which the Jamroot finds by its glob `libs/*/build.jam` and
   registers as `/webcpp/<name>`. It declares one target, named after the
   library, that adds its headers and its dependencies:

   ```
   # Copyright (c) 2026 WebCpp.org
   # ... the licence notice (chapter 11)

   project /webcpp/<name> ;

   alias <name> : : : : <include>include <library>/boost//headers ;
   ```

   A dependency on another library is written as its target,
   `<library>/webcpp/xactor//xactor`. Only Boost's header-only libraries are
   available: the CI installs Boost's headers alone, and no rule links a
   compiled Boost library. A library that needs Boost.JSON adds
   `<library>/webcpp//boost_json` to its target's usage requirements, as
   xstate's `build.jam` does: the Jamroot's `boost_json`, `tools/boost_json.cpp`,
   compiles Boost.JSON's definitions (`<boost/json/src.hpp>`, as Boost.JSON
   documents for a header-only build) into a static library, once per variant,
   so a program built without exceptions gets them built without exceptions
   too. Compiled Boost libraries are on the roadmap (chapter 13). Nothing else
   registers a library: the
   test, example and doc directories join the aggregates `test`, `example` and
   `doc` by themselves, and `include/webcpp/**` joins `install`.
5. **`test/Jamfile`, `example/Jamfile` and `doc/Jamfile`**, with the rules of
   chapter 9 and chapter 8.
6. **The files of the repository:** `LICENSE_1_0.txt`, `README.md` (what the
   library is, how to build and test it inside the superproject, where its
   page is published, its licence), `AGENTS.md` (only what is specific to it,
   with a link to this file as `../../AGENTS.md`), `.gitattributes`, and a
   `.gitignore` that holds at least `doc/html/`, and `node_modules/` for a
   library with an oracle: the superproject's own `.gitignore` names only its
   top-level `doc/html/`.
7. **CI.** `.github/workflows/ci.yml`, which calls the superproject's
   reusable workflow (chapter 9), as `libs/xactor/.github/workflows/ci.yml`
   does:

   ```yaml
   jobs:
     ci:
       uses: webcpporg/webcpp/.github/workflows/library.yml@main
       with:
         library: <name>
   ```

8. **The index page.** It lists every library of `libs/` from its
   `meta/libraries.json`, so the entry exists once the file does, and `b2 doc`
   shows it in `doc/html/index.html`, linked to the library's page. A library
   without a page fails the index.
9. **`LICENSE-<ORIGIN>.txt`**, where the port derives from the original's
   code (above).

## 3. Names

| What | Rule | xactor's |
| --- | --- | --- |
| namespace | `webcpp::<name>` | `webcpp::xactor` |
| what is not public | a namespace `detail`, at any depth | `webcpp::xactor::detail` |
| convenience header | `<webcpp/<name>.hpp>`, which includes every public header, but may leave out one that brings an optional heavy dependency (below) | `<webcpp/xactor.hpp>` |
| headers | `<webcpp/<name>/...>`, one per responsibility, `snake_case` | `<webcpp/xactor/scheduler.hpp>` |
| macros | `WEBCPP_<NAME>_*` | `WEBCPP_XACTOR_*` |
| test-only macros | `WEBCPP_TEST_*` | |
| include guards | `WEBCPP_<NAME>_<HEADER>_HPP` | `WEBCPP_XACTOR_ACTOR_LOGIC_HPP` |
| b2 target | `/webcpp/<name>//<name>` | `/webcpp/xactor//xactor` |
| error category | `webcpp.<name>` | `webcpp.xactor` |
| identifiers | `snake_case`, Boost's convention; `.clang-tidy` enforces it | |

A convenience header may leave out a public header that brings an optional
heavy dependency, which a user of the rest should not pay for, and names in
its comment the header it leaves out and the dependency:
`<webcpp/pratt.hpp>` includes pratt's engine, and leaves out
`<webcpp/pratt/calculator.hpp>`, which brings Boost.Decimal.

A test's helpers that are shared between tests go in `webcpp::test`
(`libs/xactor/test/require.hpp`). Example programs alias the namespace
(`namespace xactor = webcpp::xactor;`), as Boost's do.

## 4. Fidelity

- A port behaves as the original, at the version it ports: the same results,
  the same order of events, the same errors, for the same inputs.
- Every difference is a decision, recorded in the page's appendix
  "Differences": what the original does, what the port does, and why. A
  difference forced by C++ (no garbage collector, no exceptions on wasip2,
  value types where the original shares objects) is still recorded.
- Each difference has an example `example/diff_<topic>.cpp`, with its
  `.expected`, and its twin in the original's language (chapter 5), which
  shows the original's behaviour; the page shows both outputs side by side.
  xstate is the model, with its `diff_spawn_id`: XState keys a child spawned
  without an id as `"undefined"`, the port as an empty string, and the page
  shows the two outputs, each printed by its program.
- No divergence goes unrecorded. A difference found later, in a test, a
  review or a user's report, is either fixed or recorded in the same change
  that finds it.

## 5. Evidence: oracle and twins

A port's evidence is the original itself. The port's tests do not state by
hand what the original does: the pinned original runs the same cases and the
twins of the examples, and the port must produce what it produced. The
oracle that does it is shared by every port, in `tools/oracle/`; xstate is
its first user, and the model:

| Shared, in `tools/oracle/` | Per library, in `libs/<name>/test/oracle/` |
| --- | --- |
| the twin runner, `twins.py`, with its agreeing, divergent and without-twin bookkeeping | the pinned original (`package.json` and `package-lock.json`, for JavaScript) |
| output and tree comparison, `twins.py` and `compare.py` | the oracle scripts that drive the original over the cases (xstate's `oracle.mjs` and `actors.mjs`) |
| `update-expected`, with its refusals | the cases, and their C++ runner, under the library's `test/` |
| the `.jam` module of rules, `oracle.jam`, that the library's `test/oracle/Jamfile` calls | the twins, `twins/`, with `without-twin.txt` |
| the CI action that installs the language's runtime, `tools/ci/actions/node` | |

- **Cases.** The original's tests are ported as data-driven cases, which the
  C++ runner runs against the port.
- **Expected results.** The oracle runs the pinned original over the same
  cases and writes the expected results. The port must produce them.
- **Twins.** Every documented example has a twin in the original's language,
  `<name>.mjs` beside the C++ program in the library's twin directory, which
  the page includes through `{twins}`. A twin either agrees (prints exactly
  what the C++ example prints), or diverges, with the original's output
  recorded as its own `.expected` and the difference in the appendix
  (chapter 4), or is listed as without a twin, with the reason, as a line
  `<path>: <reason>` of the twin directory's `without-twin.txt`.
- **Nothing expected is written by hand.** Only `update-expected` writes an
  expected result, and it refuses to write a twin's output for a twin that
  agrees, since that output must be the C++ example's.
- **How the original runs.** Each library declares it: for JavaScript and
  TypeScript, `node --conditions=development`.

### The rules (`tools/oracle/oracle.jam`)

A library's `test/oracle/Jamfile` declares its oracle with four rules of
`tools/webcpp.jam`. xstate's, whole after its licence notice and its first
comment:

```
import webcpp ;

webcpp.original node --conditions=development ;
webcpp.twins ../../example : twins : .mjs
  : --test-reporter=spec --test-reporter-destination=stderr ;
webcpp.cases machines : oracle.mjs : ../fixtures/cases : ../fixtures/expected ;
webcpp.cases actors : actors.mjs : ../fixtures/actors/cases : ../fixtures/actors/expected ;
webcpp.lane oracle : twins cases-machines cases-actors ;
```

| Rule | What it declares |
| --- | --- |
| `webcpp.original <word> + ;` | how a program of the original's language runs, once and first; and the target `node-modules`, which installs what `package-lock.json` beside the Jamfile pins with `npm ci`, again when the lockfile changes |
| `webcpp.twins <examples> : <twins> : <suffix> : <extra-word> * ;` | the target `twins`: `twins.py` runs the twin `<twins>/<path><suffix>` of every program `<examples>/<path>.cpp`, at any depth, with the original's words and the extra words, and compares what it prints with the program's `.expected`, or with the twin's own `.expected` for a difference, which must then differ from the program's. Declared once per library: the page shows and counts its twins (chapter 8) |
| `webcpp.cases <name> : <script> : <cases> : <expected> ;` | the target `cases-<name>`: the original runs `<script> <cases> <output>` into the build directory, and `compare.py` finds the output equal to `<expected>`, file by file and byte by byte. The Jamfile stops loading at a cases directory that does not exist, and at an expected directory whose removal would take the oracle's directory or the cases |
| `webcpp.lane <name> : <target> + ;` | an own lane of the library, the alias `<name>` over the targets, which `b2 declared-lanes` lists and the CI runs (chapter 9). Only a Jamfile under the library's `test/` or `example/` declares one |

The first `webcpp.twins` or `webcpp.cases` also declares the target
`update-expected`, which writes every expected directory again from the
original, and each divergent twin's own output (`twins.py --update`, which
refuses one that agrees). Directories are relative to the Jamfile.

Every target is explicit: only a request by name, or a lane that names it,
runs Node, and `b2 test` never does. Node and npm are looked for on `PATH`
when an oracle target runs, and the build stops, naming the one that is
missing. The targets compile nothing, but they sit in the library's test
project and inherit its requirements, with the Jamroot's check of Boost, so
an oracle lane needs Boost and a toolset beside Node and npm.

| Command | What it does |
| --- | --- |
| `b2 -a libs/<name>/test/oracle//oracle` | the oracle lane, from scratch: every case and every twin on the original, compared |
| `b2 libs/<name>/test/oracle//twins`, `//cases-<name>` | one part of it, while working on it |
| `b2 libs/<name>/test/oracle//update-expected` | the original's results written again, over the committed ones; never a check |
| `python3 tools/oracle/twins.py --list --suffix .mjs --examples libs/<name>/example --twins libs/<name>/test/oracle/twins` | each program as agreeing, divergent or without twin, and their total, running nothing |

**What a port proves.** Its cases pass natively and on every target it
declares, against expected results the original wrote; its oracle lane is
green, so the original still writes every committed expected result and
every twin agrees, or diverges as recorded; and its page shows each twin's
code and each difference's two outputs. The runner accounts for every
program by name, so a twin that is no longer compared fails the lane rather
than leave it green on the rest.

## 6. C++ rules

### The language

- C++20, header-only. The Jamroot sets `<cxxstd>20`, `<warnings>extra` and
  `<warnings-as-errors>on` for everything.
- Boost and the standard library before custom code. A third-party
  dependency other than Boost needs the owner's decision.
- **Errors as values.** An operation that can fail returns its error:
  `boost::system::result<T>`, with an error category of the library's own
  (`webcpp.<name>`) and fixed enumerator values that are never reused.
- **No global or static mutable state.** `.clang-tidy` enforces part of it
  (`cppcoreguidelines-avoid-non-const-global-variables`).
- **Determinism.** No clock, file, network, process, thread, environment or
  entropy, unless that is the library's purpose. The lint's world rule finds
  them by name in every library header; a line that names one without
  reaching the world (a simulated clock), or that reaches it because it is the
  library's purpose, says why after `lint-world:` on the same line:

  ```cpp
  #include <boost/asio/io_context.hpp>  // lint-world: posts handlers only
  ```

- **Allocation.** A library is to avoid dynamic allocation as far as its job
  allows, and to let its user customize the allocator of what it does
  allocate. A library ported or written from now on is born with this rule,
  as pratt is: its calculator's environment takes the user's `Allocator`.
  Pending: the mechanism, which a milestone of its own on allocators settles
  and first applies to xactor and xstate (chapter 13).
- **Text** is passed and held as `std::string_view` where nothing must own
  it; `std::string` only where something does.
- **A function starts with its guards:** every condition it needs is checked
  first, and what fails returns there, before any work begins.
- **A comment says what the code does not make clear:** why, a constraint, an
  example of a value. A descriptive comment is one sentence of what the code
  that follows does, then an optional reason, in a few lines.
- **JSON literals in code are laid out for their reader:** a raw string
  literal that opens a line with `R"({` or `R"([` has its members four spaces
  deeper than that line, one per line, and closes at that line's indentation.

### Exceptions and RTTI

- **wasip2:** a program compiles without exceptions. This is a portability
  policy, not a toolchain limit: some WebAssembly hosts lack exception
  handling. The Jamroot sets `<exception-handling>off` and
  `BOOST_NO_EXCEPTIONS` for `clang-wasip2`, and `webcpp.jam` links
  `tools/throw_exception.cpp`, a `boost::throw_exception` handler that prints
  and aborts, into every program built without exceptions. The wasip2 lane is
  the one place webcpp proves that a library works without exceptions, for a
  library that declares wasip2.
- **Everywhere else** (native, emscripten, wasip3), whether a program uses
  exceptions is the decision of whoever uses the library, never an
  imposition of the library or of webcpp. webcpp builds no variant without
  exceptions there. A user who builds with `exception-handling=off` gets the
  same handler linked, and MSVC's `_HAS_EXCEPTIONS=0`.
- **wasip3:** exceptions are on. The Jamroot compiles with
  `-fwasm-exceptions -mllvm -wasm-use-legacy-eh=false` and links with
  `-fwasm-exceptions -lunwind`. The second flag is needed: wasi-sdk 34 emits
  the legacy encoding by default, which wasmtime 47 refuses to run
  ("legacy_exceptions feature required").
- So a library's headers never `throw`, `try` or `catch` where wasip2
  reaches them: there they return errors, and a failure that cannot be
  returned goes through `boost::throw_exception`. Code that throws, tries or
  catches sits behind `#ifndef BOOST_NO_EXCEPTIONS`, which is the condition,
  so both wasip2 and a user's own build without exceptions compile. A
  program that throws on purpose declares only the targets where exceptions
  are on: `webcpp.example catches.cpp : : native wasip3 ;`.
- **RTTI** is never restricted by webcpp, on any target, and no variant is
  built without it; a user imposes their own.

### What the lint enforces

`tools/lint/lint.sh` lints the superproject and every library of `libs/` that
is a repository: what git tracks and what it would track (untracked, not
ignored), so a new file is linted before it is added. It prints each rule's
section and ends with `lint: clean`, or with `lint: failed: <rule>` for each
rule that failed.

| Rule | What fails |
| --- | --- |
| clang-format | a C++ file not formatted as `.clang-format` says (Google-based, 4 spaces, 100 columns); `clang-format -i` fixes it |
| clang-tidy | a finding of `.clang-tidy` (every warning is an error) in the compilation database `tools/lint/compile_commands.py` writes from b2's dry runs, one per target the libraries declare: every test and example natively, and each source that no native program compiles, analysed as the first of the WASI targets that compiles it builds it (wasip2, else wasip3), with wasi-sdk's `clang++` and its own `--target`, to which the lint adds no host target or SDK; plus each library's aggregate translation unit, which includes every public header (`bin/aggregate/<name>.cpp`), compiled as a headers-alone translation unit of the first target on which every public header compiles alone: natively, and again, with the handler `tools/throw_exception.cpp`, as b2 compiles it with `exception-handling=off`, so that what only a build without exceptions compiles (`#ifdef BOOST_NO_EXCEPTIONS`) is analysed too; or, for a library whose headers build only for WASI, on wasip2 (without exceptions) and on wasip3 (with them), each reading its version's branch. A public header without a headers-alone translation unit on any target, a declared target whose toolset is not configured, and a WebAssembly command whose compiler is not wasi-sdk's `clang++` (emscripten's `em++`, which the lint would analyse as a native command), fail it by name. Findings are reported in a library's public headers and in the headers of its tests and examples (`libs/xactor/test/require.hpp`), never in Boost's |
| io_context::run | a call of Boost.Asio's `run`, `run_one` or `run_for`, which block; a driver drains with `poll` and `poll_one` |
| fluent chains | three calls chained in one expression |
| returns `*this` | a function other than an assignment operator returning `*this` |
| em dash | U+2014 in any file |
| JSON literals | a raw JSON literal laid out otherwise than chapter 6 says |
| licence notice | a source file that does not open with the notice (chapter 11) |
| banned word | the word that the pattern `veru[s]` matches, in any case, in a file, a file name or a commit (its author, committer or message) of any repository |
| no clock, disk or network | a library header that names a clock, a file, a socket, a process, a thread, the environment or entropy without `lint-world:` |
| raw b2 rules | `run`, `run-fail`, `compile`, `compile-fail`, `exe` or `unit-test` in a library's test or example Jamfile (chapter 9) |
| Doc Comments | a command webcpp does not allow, a bare `@`, or a colon after a reference (chapter 7) |
| Pyright | an error or a warning in any Python file, with `pyrightconfig.json` (unused imports and variables are errors) |
| Python line length | a Python line over 100 columns |
| include boundaries | an `#include` that crosses a boundary the library declares in its `meta/include-boundaries.json` (below), at its line, with the boundary's reason; and a malformed file, or a glob that matches no file of the library |

A source b2 expects not to compile (`webcpp.compile-fail`), and one that
must stop with the error it states (`webcpp.compile-diagnostic`), are left
out of clang-tidy only; every other rule reads them.

**A library's include boundaries.** Every header compiles alone, so only a
boundary check sees a part of a library start to depend on another. A
library declares its boundaries in `meta/include-boundaries.json`, each a set
of headers (a `headers` glob, less an `except` glob, each matched against the
whole path under `libs/<name>/`, a `*` within one path segment) that must not
include a path starting with one of its `must-not-include` prefixes, and
`why`. xstate's keeps its machine core free of xactor and of the actor layer:

```json
{
    "boundaries": [
        {
            "headers": ["include/webcpp/xstate.hpp", "include/webcpp/xstate/*.hpp"],
            "except": ["include/webcpp/xstate/actors.hpp"],
            "must-not-include": ["webcpp/xactor", "webcpp/xstate/actors"],
            "why": "the machine core runs without xactor and the actor layer"
        }
    ]
}
```

**A directory's own `.clang-tidy`.** A library's tests or examples may need
one that inherits the root's (`InheritParentConfig: true`) and switches off
what does not apply to them, each with its reason in a comment. xactor's
`test/.clang-tidy` turns off `bugprone-unchecked-optional-access` (a test
asserts with `BOOST_TEST` before it reads, which the check does not see) and
`bugprone-exception-escape.CheckMain` (a test's `main` lets an exception end
the process, which fails the test as it should); `example/.clang-tidy` turns
off the second. The library's headers are still analysed with every check,
through the aggregate translation unit. A check that applies to a library
header is never switched off for a directory, since a header's templates are
analysed only where a test or an example instantiates them: the header states
its exemption on the line clang-tidy reports, `NOLINT(<check>)` (or
`NOLINTNEXTLINE(<check>)` on the line above, when that line has no room; a tag
comment between it and its function cancels the suppression), or, when a
page's listing must hide the exemption, with `NOLINTBEGIN(<check>)` and
`NOLINTEND(<check>)` around the exempt function or functions alone. The
reason still goes in the comment above, in every form.

**Sharding.** `--shard K/N` analyses the K-th of N interleaved slices with
clang-tidy, and runs every other rule; the N shards together analyse every
file once.

## 7. Doc Comments and the API reference

### Generation

The reference is generated by MrDocs 2026.9.29, always to AsciiDoc and as a
single page, from the library's Doc Comments. `webcpp.reference <name> ;` in
`doc/Jamfile` declares it; `tools/doc/reference.py` runs it:

- the input is a compilation database of one aggregate translation unit,
  which includes every public header (the same one the lint analyses), read
  natively with the include directories and defines of the library's target
  and of the requirements `webcpp.reference <name> : <requirements> * ;`
  gives: a library whose headers build only for WASI gives those a native
  parse needs, the explicit target `<bindings>-headers` of
  `webcpp.wit-bindings`, which generates the bindings on any toolset, and the
  macro of one version; a header the reference cannot parse fails it, naming
  the header;
- the shared settings are `tools/doc/mrdocs.yml.in`: `generator: adoc`,
  `multipage: false`, `embedded: true`, `warn-as-error: true`,
  `auto-function-metadata: false`, `auto-relates: false`, every `warn-*` on,
  the symbols of `webcpp::<name>::**`, `detail` namespaces as
  implementation-defined, the macros `WEBCPP_<NAME>_*` except the include
  guards, and `base-url: https://github.com/webcpporg/<name>/blob/main/`;
- `tools/doc/doc_comments.py` then checks with clang++ what MrDocs does not
  (below);
- the page includes the result with
  `include::{reference}[leveloffset=+1]`.

`auto-function-metadata` and `auto-relates` are off because, at their
defaults, they document a parameter with its type's brief and count a class
with related functions as documented, which hid 48 findings on the first
library measured.

**A library's `doc/mrdocs.yml` holds presentation keys only.** It may set
`sort-members`, `sort-members-by`, `sort-namespace-members-by`,
`sort-members-ctors-1st`, `sort-members-dtors-1st`,
`sort-members-assignment-1st`, `sort-members-conversion-last`,
`sort-members-relational-last`, `overloads`, `sfinae`,
`inherit-base-members`, `inherit-hidden-friends`, `legible-names` and
`show-enum-constants`. Any other key (what is documented, the input, the
output, a warning) is refused and fails the reference: every library is
documented as strictly as every other. xactor's sets `show-enum-constants:
true`.

### The format

Doc Comments are Javadoc/Doxygen style, `/** ... */`, before the symbol they
document:

```cpp
/**
 Handles one message, the payload of `cause`.

 The scheduler calls it once for each message delivered to the actor, and
 delivers the actor's next message only after it returns.

 @param turn What the actor may do while it handles the message.
 @param cause The message, in the envelope that says who sent it.
 @return Success, or an error of any category, which ends the actor with
 the status @ref status::error.
 @note An error ends this actor and only it.
 @see "Writing an actor logic", in the guide.
*/
virtual result<void> handle(xactor::turn<Message>& turn, const envelope<Message>& cause) = 0;
```

### What every public symbol needs

A public symbol is one at namespace scope of `webcpp::<name>`, or a public
member of a public class, outside every namespace `detail`. Every one is
fully documented: functions, classes, structs, enums and enumerators,
aliases, concepts, variables, data members and macros.

- **A brief,** the first paragraph, which is a single sentence: MrDocs makes
  the whole first paragraph the brief, and `doc_comments.py` fails a brief of
  more than one sentence (an abbreviation such as `e.g.` and a code span do
  not count).
- **`@param`** for every parameter, **`@tparam`** for every named template
  parameter (of a function, class, partial specialization, alias, variable or
  concept, hidden friends and member templates included), and **`@return`**
  for every function that returns a value. MrDocs reports a missing `@param`
  or `@return`; `doc_comments.py` reports a missing `@tparam`, which MrDocs
  does not.
- **A deleted function takes no `@return`.** Nobody can call it, so a
  `@return` would say nothing, and MrDocs accepts its absence:
  `actor_logic& operator=(const actor_logic&) = delete;` has a brief and no
  `@return`.
- **`@throws`, `@pre`, `@post`, `@note`, `@see` and `@code`** where they
  apply.
- **Each enumerator and each data member has its own Doc Comment.** clang
  attaches one comment to every declarator up to the next `;`, `{`, `}`, `#`
  or `@`, so in `/** A. */ a, b,` the enumerator `b` has `a`'s comment, and in
  `/** The x. */ int x, y;` so does `y`. `doc_comments.py` reports the second
  as undocumented, public or `detail`. Comment each one itself, and declare
  one data member per declaration.
- **A `detail` symbol** needs only its brief.

### The commands

- **Allowed:** `@brief`, `@param`, `@tparam`, `@return`, `@returns`,
  `@throws`, `@pre`, `@post`, `@note`, `@see`, `@code`/`@endcode`,
  `@details`, `@par`, `@copydoc`, `@ref` (and the same with `\`).
- **Forbidden,** because MrDocs drops them without a word: `@sa`,
  `@deprecated`, `@since`, `@todo`, `@retval`, and every other command. The
  lint names each.
- **A literal `@` in prose** is written `\@`; a bare `@` that starts no
  allowed command fails the lint.
- **No colon after `@ref x`.** MrDocs drops the colon: write
  `the result of @ref status_of, which`, never `@ref status_of: it`. The lint
  rejects it. A possessive is fine (`@ref scheduler's queue`); MrDocs renders
  it.
- **`@see "<title>"`** sends the reader to a section of the library's page by
  its title, exactly as the heading writes it after its `=` marks, in
  quotes, and on one line: `@see "Writing an actor logic", in the guide.` The
  doc build fails on a title that names no section of the page, or that
  wraps onto a second line, since MrDocs writes the title as plain text that
  no link checks. A section renamed changes its `@see` lines in the same
  commit.
- **A `(doc: #<anchor>)`** in a `//` comment of the library (code, test or
  example) sends its reader to an anchor of the page, such as a guarantee:
  `(doc: #xactor-invariant-13)`, or a list, `(doc: #a, #b and #c)`, or a
  range, `(doc: #a to #b)`. The doc build fails on an anchor that the page
  does not define. In a Doc Comment, use `@see` with the section's title.
- **Never link by hand to an overload's anchor:** MrDocs gives it a hash
  suffix that changes.
- **File-level comments do not reach the reference.** A header's opening
  `/** ... */` is for its reader; what the user needs is in the symbols'
  comments.

### What the doc build does after MrDocs

`postprocess.mjs` decodes the character references MrDocs writes for the
characters AsciiDoc would read as markup, and the U+2010 it writes for an
ASCII hyphen; `reference.py` drops the near-empty sections of the global
namespace and of `webcpp`, so the reference starts at `webcpp::<name>`, with
the library's macros, when it has any, in a section "Macros" of their own.

### Where the reference sits

It replaces any hand-written reference chapter. The numbered guarantees stay
in the guide part of the page, and a reference like `(doc: #anchor)` in a Doc
Comment becomes `@see "<title>"`.

## 8. Documentation

### The page

Each library has one AsciiDoc page, `doc/<name>.adoc`, with its sections in
files of their own beside it, built by `doc/Jamfile`:

```
import webcpp ;

webcpp.doc <name> : <name>.adoc ;
webcpp.reference <name> ;
```

Either rule declared in another directory stops the build, naming the rule
and the directory, and so does a page whose Jamfile declares no reference.
`b2 libs/<name>/doc` converts the page with Asciidoctor.js into
`libs/<name>/doc/html/index.html`, with the reference included. The page
sets its own title and attributes, as xactor's does:

```
= <name>: <what it is> for {cpp}
:toc: left
:toclevels: 1
:idprefix:
:sectanchors:
:example-caption!:
:attribute-missing: warn
```

The doc build provides `{examples}` (the library's `example/` directory),
`{reference}`, `{twins}` (the twin directory, for a library whose oracle
declares twins, chapter 5), the counts and the links to other pages (below),
and sets the highlighter, the shared style (`tools/doc/docinfo.html`, the
system's fonts, no web fonts), no date and no footer: a page sets none of
these. In that style a table too wide for the page scrolls in its own box,
and an identifier breaks only between its parts.

**What a page holds:**

- **the guide,** taught the way the original's documentation teaches, concept
  by concept, with C++ only in listings: each concept's purpose, its smallest
  example, its variations and its rules. Each section has an anchor that
  starts with the library's name, `[#xactor-testing]`;
- **the guarantees,** numbered, each with an anchor named after its number,
  `. [[xactor-invariant-1]]The messages of one mailbox are handled in the
  order they were enqueued.` A guarantee keeps its number and its anchor
  forever, since code, tests and comments cite them;
- **a testing chapter:** how a program tests what it builds with the library,
  how the library itself is tested, on which targets, with which commands,
  and where the test matrix is (https://webcpporg.github.io/webcpp/report/);
- **the reference,** `include::{reference}[leveloffset=+1]`, under a section
  `[#reference]`;
- **the appendix "Differences"** for a port (chapter 4).

**Every listing is a compiled example, and every shown output comes from a
`.expected` file.** A listing includes a region of an example, marked in the
program by `// tag::<name>[]` and `// end::<name>[]` lines:

```
[source]
----
include::{examples}/xactor_quick_start.cpp[tag=messages,indent=0]
----
```

and the output it prints, which `b2 example` compares on every build:

```
[source]
----
include::{examples}/xactor_quick_start.expected[]
----
```

A listing of shell commands is `[source,bash]`; the only languages a page may
use are C++ (the default), JavaScript (a twin's code), JSON and bash.

### What doc-check enforces

`tools/doc/doc-check.py` runs before the page is converted, and again on the
rendered HTML; any finding, and any warning of Asciidoctor's, fails the
build:

- every `.adoc` under `doc/` is reached from the page's `include::` graph;
- every example's code or output is shown, every block's language is allowed,
  C++ is shown only as an include of an example, and the page includes the
  reference;
- every include names a file that exists, inside `doc/`, `{examples}` or
  `{twins}`; an output's include names a program that exists;
- every `(doc: #anchor)` and `index.html#anchor` of the library's files
  names an anchor the page defines, and every `@see "<title>"` a section;
- every `(doc: <library>#<anchor>)` of the library's files, and every link
  of the rendered page into another library's page, names an anchor that
  page defines, as the build made it first (below);
- every C++ block of the library's README is opened by a comment
  `<!-- include::<file>[<attributes>] -->` and equals that region of the
  file, as an include would give it;
- no line inside a table starts with `//` (Asciidoctor drops it as a
  comment), and no `++` appears in prose (two of them swallow what lies
  between): write `{cpp}`;
- the rendered page has no cross-reference left as text, no stray `++` or
  backtick, no undecoded escape of MrDocs's, no U+2010, and no link to the
  dropped `#index` or `#webcpp` sections.

### Counts

A page never types how many examples, tests, headers or twins its library
has: `webcpp.doc` gives it attributes that `tools/doc/counts.py` computes at
every build, so that no count drifts from the tree:

- from the programs b2 records as it loads the library's test and example
  Jamfiles: `{n-examples}` and `{n-examples-<target>}`, `{n-tests}` and
  `{n-tests-<target>}` (each header compiled alone is one test),
  `{n-boost-test-suites}` and `{n-headers}`;
- for a library whose oracle declares twins, from `twins.py --list`:
  `{n-twins-agreeing}`, `{n-twins-divergent}`, `{n-examples-without-twin}`
  and `{n-examples-with-original}`;
- from the library's own `doc/counts.py`, when it has one, run with the
  library's directory as its one argument: each line `<name>=<number>` it
  prints, a count of what only that library holds (xstate's counts the cases
  of its fixtures, `{n-machine-cases}` among them).

A count that finds nothing fails the build rather than put a zero on the
page, and so does a name of a library's own that is also a generic one.

### Links between pages

A page links another library's page as
`link:{webcpp-libs}/<library>/{webcpp-page}#<anchor>[...]`, with two
attributes `webcpp.doc` sets by the layout: where b2 builds the pages, by
default, or where the site serves them, with `-sWEBCPP_INDEX=site`
(chapter 9). Such a link written any other way after `{webcpp-libs}/` is a
fault. A `//` comment of the library's files sends its reader to another
library's page with `(doc: <library>#<anchor>)`, or a list or a range of
them, as with its own page; a Doc Comment still uses `@see` (chapter 7). The
build makes every linked page first, and the check of the rendered page fails
on an anchor that page does not define, and on an overload's anchor, which
ends in `-0<digit>` and which MrDocs may renumber.

### The index page

`doc/index.adoc`, built by `doc/Jamfile` (`webcpp.index index.adoc ;`),
introduces webcpp and includes, at `{libraries}`, the table that
`tools/doc/libraries.py` writes from every library's `meta/libraries.json`:
its name, linked to its page, its description, and what it ports, linked to
the original. `b2 doc` builds it with every library's page.

The table links a page as `{library-pages}<name>/{library-page}`, two
attributes `tools/doc/doc.jam` converts the index with. By default they point
where b2 builds the page, `../../libs/<name>/doc/html/index.html` from
`doc/html/`; with `-sWEBCPP_INDEX=site` they point where the site serves it,
`libs/<name>/`, beside the index at the site's root (chapter 9). Any other
value stops the build.

**One doc build at a time.** A doc build writes `doc/html/` and
`libs/<name>/doc/html/` inside the tree, so two concurrent doc builds would
write the same files.

## 9. Tests, lanes, the report and CI

### Targets

A target is what a program is built for:

| Target | Toolset | Runs with |
| --- | --- | --- |
| `native` | any toolset not below: gcc, clang, msvc, darwin | the host |
| `emscripten` | b2's `emscripten` | no CI lane yet: one comes when emsdk is pinned (chapter 13) |
| `wasip2` | `clang-wasip2`, a clang registered against wasi-sdk with version `wasip2` | `testing.launcher=wasmtime` |
| `wasip3` | `clang-wasip3`, likewise | `testing.launcher=wasmtime` |

A Jamfile declares its default with `webcpp.targets`, a program can override
it with its own targets, and with no declaration a program is built for
`native` only. For any other target, the program gets `<build>no` and b2 skips
it without a word. This filter is conditioned on `<toolset>` and its version
only, never on a derived feature (chapter 12).

### The Jamfile API (`tools/webcpp.jam`)

A library's test and example Jamfiles declare their programs only with these
rules; the lint rejects b2's own `run`, `run-fail`, `compile`,
`compile-fail`, `exe` and `unit-test` there, by file and line.

```
import webcpp ;
webcpp.targets native wasip2 wasip3 ;
webcpp.run          <name> : <sources> + : <requirements> * : <targets> * ;
webcpp.run-fail     <name> : <sources> + : <requirements> * : <targets> * ;
webcpp.compile      <name> : <sources> + : <requirements> * : <targets> * ;
webcpp.compile-fail <name> : <sources> + : <requirements> * : <targets> * ;
webcpp.compile-diagnostic <name> : <sources> + : <requirements> * : <targets> * ;
webcpp.boost-test   <name> : <sources> + : <requirements> * ;
webcpp.example      <source> : <requirements> * : <targets> * ;
webcpp.headers-alone <library> : <include-root> : <only> * : <requirements> * : <targets> * ;
```

| Rule | Passes when | Notes |
| --- | --- | --- |
| `webcpp.targets t ...` | | the Jamfile's default targets; before its first program, once; each is `native`, `emscripten`, `wasip2` or `wasip3`, or the build stops naming it |
| `webcpp.run` | the program exits with 0 | built once per target it declares; without exceptions on wasip2, where it links `tools/throw_exception.cpp` |
| `webcpp.run-fail` | the program exits with another status | |
| `webcpp.compile` | the sources compile | no program is linked |
| `webcpp.compile-fail` | the sources do not compile | left out of clang-tidy; any error passes it, the wrong one included |
| `webcpp.compile-diagnostic` | the sources stop with every error they state in clang's `-verify` comments, `// expected-error@<file>:* {{<message>}}` for a header they include or `// expected-error@+1 {{<message>}}` for the next line | compiled with `-Xclang -verify -Xclang -verify-ignore-unexpected=error,note`, so an error not stated and a note are ignored; built on b2's `clang` toolset only (native clang, `clang-wasip2`, `clang-wasip3`) and skipped elsewhere, since `-verify` is clang's: a refusal would turn every gcc and msvc lane red for a declaration that holds; left out of clang-tidy |
| `webcpp.boost-test` | every case of the Boost.Test suite passes | native only, whatever the Jamfile declares; the header-only framework, `tools/boost_test_runner.cpp`, is one object of the suite's, always compiled with exceptions |
| `webcpp.example` | the program exits with 0, and its standard output, carriage returns removed, equals `<stem>.expected` beside it | its standard input is `<stem>.input` beside it, else empty, never the terminal, on every target (wasmtime passes it through); run through `testing.launcher` for wasm, by `tools/example/run_example.py`, which names a failing exit status (or the signal) before the diff; always run again, and `<stem>.input` is a source of the run |
| `webcpp.headers-alone` | each public header compiles alone | one test per header, `alone-<path>` with `/` as `-` (`alone-xactor-scheduler`), against `/webcpp/<library>//<library>` and the requirements given, for the targets given or the Jamfile's; `only` restricts a call to the public headers its globs match, relative to `<include-root>/webcpp/` (`wasi/http/response.hpp`), a glob that matches none stopping the build; a library may call it several times, and a header two calls take stops the build, naming it |

The rules of the doc Jamfiles are in chapter 8: `webcpp.doc <library> :
<page>.adoc ;`, `webcpp.reference <library> : <requirements> * ;` and, for the superproject's
index, `webcpp.index <page>.adoc ;`. Those of an oracle's Jamfile,
`libs/<name>/test/oracle/Jamfile`, are in chapter 5: `webcpp.original`,
`webcpp.twins`, `webcpp.cases` and `webcpp.lane`.

A library's Jamfiles, as xactor's, each whole after its licence notice.
`libs/xactor/test/Jamfile`:

```
project : requirements <library>/webcpp/xactor//xactor ;

import webcpp ;

webcpp.targets native wasip2 wasip3 ;

webcpp.headers-alone xactor : ../include ;

# xactor's guarantees, one program per file. scheduler checks the Asio
# driver where drivers.hpp declares it, outside WASI.
webcpp.run scheduler : scheduler_test.cpp ;
webcpp.run lifecycle : lifecycle_test.cpp ;
webcpp.run fuel : fuel_test.cpp ;
webcpp.run create_actor : create_actor_test.cpp ;
```

`libs/xactor/example/Jamfile`:

```
project : requirements <library>/webcpp/xactor//xactor ;

import webcpp ;

webcpp.targets native wasip2 wasip3 ;

webcpp.example xactor_quick_start.cpp ;
webcpp.example xactor_lifecycle.cpp ;
webcpp.example xactor_fuel.cpp ;
webcpp.example xactor_timers.cpp ;
webcpp.example xactor_drivers.cpp ;
# A test of actors, with lightweight_test: it prints nothing on its standard
# output, and returns boost::report_errors().
webcpp.example xactor_testing.cpp ;
# A static actor, whose behaviour is a Boost.MSM state machine.
webcpp.example xactor_msm.cpp ;
# Native only: Boost.Asio 1.92 does not compile for wasm32-wasip2 or
# wasm32-wasip3 with wasi-sdk 34 (no ESHUTDOWN, no ::pause, and a signal.h
# that stops with #error), so drivers.hpp declares asio_driver only outside
# WASI.
webcpp.example xactor_asio.cpp : : native ;
```

### Tests

- Unit tests use Boost.Core's lightweight_test,
  `<boost/core/lightweight_test.hpp>`, declared with `webcpp.run`. `main`
  runs the cases and returns `boost::report_errors()`.
- A case that cannot go on after a failed check returns:
  `if (!BOOST_TEST(x.has_value())) { return; }`. A helper, which cannot
  return from its case, calls `require(BOOST_TEST(...))`, which ends the
  program with the errors counted so far
  (`libs/xactor/test/require.hpp`): a test may be built without exceptions.
- Boost.Test is for a test that needs it (fixtures, data-driven suites),
  declared with `webcpp.boost-test`, natively only. The CI installs no
  compiled `unit_test_framework`: the suite compiles Boost.Test's header-only
  framework, `tools/boost_test_runner.cpp`, as an object of its own.
- Every test runs on every target its Jamfile declares. What a target cannot
  build is excluded by declaration (`: native`), and inside a program by the
  same condition the library uses (`#ifndef __wasi__`), never by skipping
  silently.
- A test moved from the original's or another suite records the conversion,
  case by case, and each converted case is seen failing on a planted defect
  where the old one had a pinning test (`libs/xactor/test/CONVERSION.md`).

### Lanes

A lane builds and runs one library's tests and examples for one toolset, from
scratch, and records what it built and ran:

```
b2 -a --dump-tests --out-xml=<lane>.xml toolset=<toolset> libs/<library>/test libs/<library>/example
```

A wasip2 or wasip3 lane adds `testing.launcher=wasmtime`, which applies to
every toolset of one b2 request, so a lane is always one toolset. The lane
runs from the superproject's root. `--dump-tests` is required: it lists every
test, those the lane skips included, and the report refuses a file without
it. With `--out-xml`, b2 exits 0 even when a test fails, so b2's status is
never the verdict.

**Lane names.** A lane is named after its target (`native`, `emscripten`,
`wasip2`, `wasip3`) or after the directory b2 builds its toolset in
(`gcc-14`, `gcc-15`, `clang-linux-18`, `clang-darwin-21`, `msvc-14.3`). The
CI names a native lane after its directory, and a wasm or emscripten lane
after its target. The report checks every name against the toolset directory
the file records: a lane named after a target must be built for it, and any
other name must be that directory, or the report exits 2, naming the lane,
the directory and the two names it may take. A lane that built nothing
records no directory; its name is not checked, and it fails as empty.

**Lanes in parallel.** Independent lanes run at the same time, each with its
own build directory, and are read once all have finished:

```
b2 -a --dump-tests --build-dir=bin/lane-wasip2 --out-xml=wasip2.xml toolset=clang-wasip2 testing.launcher=wasmtime libs/<library>/test libs/<library>/example
```

Two concurrent b2 runs never share a build directory, and at most one of
them builds the documentation (chapter 8).

**Own lanes.** A library may also declare lanes of its own with
`webcpp.lane` (chapter 5), such as xstate's oracle lane, which needs Node
where a toolset lane does not. `b2 declared-lanes -d0` lists them, one line
`<library> <lane> <directory>` each, and one runs as
`b2 -a <directory>//<lane>`, whose exit status is its verdict. An own lane
writes no XML, and is no column of the report.

### The report (`tools/report/`)

```
python3 tools/report/report.py --lane <lane>=<lane>.xml [--lane ...] --out <dir>
```

writes the test matrix into `<dir>`: `index.html`, the libraries by lanes;
`<library>.html`, a library's tests and examples by lanes; and
`output/<lane>/...`, the log of each failure, linked from its cell. A cell is
green when every build of it passed, red with the kind of its most
significant failure (compile, compiled, link, linked, build, run, ran, not
run), and grey (n/a) when the lane did not build it. The directory is served
as the site's `report/` (below): each page's `webcpp` links the site's index,
`../`, a library's page links its documentation, `../libs/<library>/`, and the
footer links `github.com/webcpporg`.

**Its exit status is the verdict:** 0 when every lane built something (a test
or an example: an example counts as something that ran) of every library it
lists, and everything passed; 1 when a test or an example failed, an action
outside every test failed, a lane built nothing, or a lane that built
something built none of the tests and examples of a library it lists, each
named (`wasip2: nativeonly: the lane built none of its tests and examples`).
The CI puts in a lane only the libraries that declare its target, so such a
library is a fault that a grey column would hide, as when a lane run by hand
names a library that does not declare its target. It exits 2, with nothing
written, when a file cannot be read, a lane spans more than one toolset, a
lane named after a target was built for another, a lane named after no target
is not named after its toolset directory, a test lies outside `libs/<name>/`,
or a library is named `index`.

### CI

The CI runs exactly the commands above. It is GitHub Actions, in two
workflows of the superproject, and every third-party action is pinned by its
full commit SHA, with its tag in a comment. It runs on every push to `main`
and on every pull request, of the superproject and of each library.

**A library's CI,** `libs/<name>/.github/workflows/ci.yml`, calls the
superproject's reusable workflow, `.github/workflows/library.yml@main`
(`on: workflow_call`, input `library`). **The superproject's CI,**
`.github/workflows/ci.yml`, calls the same workflow without a library, for
every library at the commit its submodule points to. Every job checks out
`webcpporg/webcpp` with its submodules, the caller's commit for the
superproject and `main` for a library, whose own commit then replaces
`libs/<library>`; no checkout keeps its credentials. A run on `main` is never
cancelled by the next; a pull request's newer push cancels its older run. The
jobs:

- **plan:** `python3 tools/ci/matrix.py plan [--library <name>]` runs
  `b2 declared-targets -d0` and prints the JSON matrix of lanes: one lane per
  compiler for each target a library declares, building the libraries that
  declare it. The CI never lists a library's targets by hand. A target with
  no lane fails the plan by name: the CI gets an emscripten lane when emsdk
  is pinned (chapter 13). Then `matrix.py own-lanes [--library <name>]`
  runs `b2 declared-lanes -d0` and prints the JSON matrix of the own lanes
  of that library, or of every library.
- **lanes,** one job each, which run `matrix.py lane <entry>`: it registers
  the lane's toolset in `.local/user-config.jam` with its version, prints the
  lane command and runs it, and the job uploads `<lane>.xml`:

  | Lane | Runner | Toolset |
  | --- | --- | --- |
  | `gcc-14` | ubuntu-24.04 | `gcc-14` |
  | `gcc-15` | ubuntu-26.04 | `gcc-15` |
  | `clang-linux-18` | ubuntu-24.04 | `clang-18`, on libstdc++ |
  | `clang-linux-22` | ubuntu-26.04 | `clang-22`, on libstdc++ |
  | `clang-darwin-<version>` | macos-15 | Apple Clang, its version read from `clang++ -dumpversion` |
  | `msvc-14.3` | windows-2022 | Visual Studio 2022 |
  | `msvc-14.5` | windows-2025 | Visual Studio 2026 |
  | `wasip2`, `wasip3` | ubuntu-24.04 | `clang-wasip2`, `clang-wasip3`: wasi-sdk 34 and wasmtime 47.0.3 |

  The Clang lanes on libstdc++ stay: a regression of xactor's guarantee 28 is
  caught only there. The MSVC lanes add `address-model=64
  embed-manifest-via=linker --abbreviate-paths`; b2 abbreviates each word of
  a toolset directory, and `msvc-14.3` and `msvc-14.5` are their own
  abbreviations, which `tools/ci/matrix_test.py` checks with b2's own rule.
- **own lanes,** one job each, `Own lane (<library>, <lane>, <directory>)`,
  on Linux x86-64 (ubuntu-24.04): the Boost action, `matrix.py register
  clang-18` (an oracle lane checks Boost, chapter 5), the Node action, and
  `b2 -a <directory>//<lane>`, whose exit status is the lane's verdict. A
  library that declares no own lane, as xactor, has no such job.
- **docs:** with MrDocs on Linux x86-64 (it has no build for Linux arm64 or
  Intel macOS) and `clang++-18`, `b2 -a libs/<library>/doc`, or for the
  superproject `b2 -a doc -sWEBCPP_INDEX=site`, whose pages are the site's.
- **lint:** `tools/lint/lint.sh` in four shards (`--shard 1/4` to `4/4`),
  with wasi-sdk's clang-format and clang-tidy, Node, Clang 18 as b2's default
  toolset, and the full history (`fetch-depth: 0`) of the superproject and of
  the library, since the banned-word rule reads every commit.
- **tools,** for the superproject only: every `tools/**/*_test.py`, with
  Clang 18, wasi-sdk, wasmtime, Node and MrDocs, each failure named.
- **actionlint:** actionlint 1.7.12, downloaded and checked against its
  SHA-256, on every workflow of the superproject and of `libs/*`, with
  `.github/actionlint.yaml`. It also runs clean locally before a workflow
  change is committed.
- **report:** `matrix.py report` merges every lane's XML with
  `tools/report/report.py` into the test matrix, uploaded as an artifact. Its
  exit status is the verdict; a planned lane that wrote no XML fails it by
  name, and so does a lane's job that failed, or an own lane's.

`matrix.py lane` takes, after `--`, more arguments for b2, so that a lane is
run locally exactly as the CI runs it, beside others:
`python3 tools/ci/matrix.py lane '<entry>' -- --build-dir=bin/lane-gcc-15`.

**The actions,** `tools/ci/actions/`, each a script beside its `action.yml`:

- `boost` downloads `boost_1_92_0.tar.gz` from
  `https://archives.boost.io/release/1.92.0/source/`, checked against the
  SHA-256 it records: the gzip archive, since Windows Server 2022's `tar.exe`
  has no bzip2. It builds b2 with `bootstrap`, installs Boost's headers
  (`--with-headers`, since no library links a compiled Boost library) and
  that b2 into a prefix cached per image, writes the `using boost` line of
  `.local/user-config.jam`, and puts b2 on `PATH`, on Linux, macOS and
  Windows. The headers are installed with `--layout=system`, in
  `<prefix>/include/boost`, and b2 with `b2-install-layout=standard`, in
  `<prefix>/bin`: on Windows, Boost's default is the versioned layout,
  `<prefix>/include/boost-1_92`, and b2's the portable one, which ignores
  `--bindir` and puts b2 in the prefix itself. A prefix that lacks either
  after the install fails the action before it is cached. It refuses an empty
  or relative prefix: b2 given an empty `--prefix` installs into `/usr/local`.
- `wasi-sdk` installs wasi-sdk 34 into `.local/wasi-sdk`, `wasmtime`
  installs wasmtime 47.0.3 on `PATH`, `mrdocs` installs MrDocs 2026.9.29 into
  `.local/mrdocs`, and `node` sets up Node 26.7.0, with npm's cache keyed on
  the lock files of `tools/doc`, `tools/lint` and every library's
  `test/oracle`.
- `tools/ci/download.sh <url> <sha256> <file>` downloads each pinned file,
  and leaves no file and exits 1 when the download fails or the digest
  differs.

`tools/ci/actions_test.py` pins `download.sh`, the Boost action's prefix
checks and the layouts it installs the headers and b2 in.

**The site.** On every run of the superproject's CI, `tools/ci/assemble.py`
lays out the site from the pages and the report, and on `main` it is
deployed to GitHub Pages, `https://webcpporg.github.io/webcpp/`, a red matrix
included:

```
index.html          the index page, built with -sWEBCPP_INDEX=site
libs/<name>/        each library's page
report/             the test matrix
```

It fails, naming each fault, when a library has no page, when the index does
not link a library's page, or when a link of any page names no file of the
site or no anchor of its page: an index built without `-sWEBCPP_INDEX=site`
links out of the site, and fails.

Submodules are bumped by pull request, merged only when green; `main` is the
only branch.

## 10. Process

- **The specification before the code, a failing test before the
  implementation.** A behaviour is written down (in the page, or in the
  library's `AGENTS.md` for what is internal) before it is built, and a test
  is seen failing before the code that makes it pass.
- **A defect is first reproduced the way a user meets it:** the command a
  user runs, the page a reader opens, the lane CI runs. Then it is fixed, and
  the reproduction becomes a test.
- **Only a build from scratch counts as evidence:** `b2 -a`. b2 compares
  timestamps, and an incremental build can leave a stale result in place. An
  incremental build is for iterating.
- **Green, before any merge,** means all of these, run and read, not assumed:
  - every declared lane from scratch: `b2 -a libs/<name>/test
    libs/<name>/example` natively, and with `toolset=clang-wasip2
    testing.launcher=wasmtime` and `toolset=clang-wasip3
    testing.launcher=wasmtime` where declared, and every own lane the
    library declares, `b2 -a libs/<name>/test/oracle//oracle` for an oracle;
  - `b2 -a doc`;
  - the lint: `lint: clean`;
  - the tests of the build and of the tools, when they or what they test
    changed: `tools/test/jamroot_test.py`, `tools/test/webcpp_jam_test.py`,
    `tools/test/oracle_jam_test.py`, `tools/test/doc_test.py`,
    `tools/test/harness_test.py`,
    `tools/lint/lint_test.py`, `tools/report/report_test.py`,
    `tools/doc/doc_check_test.py`, `tools/doc/doc_comments_test.py`,
    `tools/doc/extensions_test.py`, `tools/doc/counts_test.py`,
    `tools/oracle/twins_test.py`, `tools/oracle/compare_test.py`,
    `tools/example/run_example_test.py`, `tools/ci/matrix_test.py`,
    `tools/ci/assemble_test.py` and `tools/ci/actions_test.py`, each run as
    `python3 <path>`. They build in scratch copies under `$TMPDIR`, whose
    path holds a space, so they run beside a build of the tree;
  - CI green, the library's and the superproject's.
- **Fix the lint, the failures and the flakiness you meet,** even when they
  are not yours; report what you cannot fix.
- **A change of the build or of a tool** has a test that fails without it:
  the tests of `tools/` pin every behaviour this file states. A change to
  b2's `--out-xml` format shows as a red `report_test.py`, whose samples are
  recorded, never edited by hand (`python3 tools/report/record_samples.py`).

### Porting a library, step by step

1. Choose it, check its licence, and pin its version (chapter 2).
2. Make `libs/<name>` with its checklist files (chapter 2), and see `b2
   libs/<name>/test` build the headers-alone tests of an empty convenience
   header.
3. Port the original's tests as cases, and the oracle that writes their
   expected results from the pinned original (chapter 5); see them fail.
4. Port the code, header by header, with its Doc Comments (chapter 7), until
   the cases pass natively, then on every declared target.
5. Write the page: the guide with its examples and twins, the guarantees,
   the testing chapter, the reference and the differences (chapters 4, 8).
6. Run the definition of green above, from scratch.

## 11. Commits and text

- **Identity.** Commits are made as `R <github.overboard312@passmail.net>`, with no
  trailer of any kind (no `Co-authored-by`, no `Signed-off-by`, no agent
  name):

  ```
  git -c user.name=R -c user.email=github.overboard312@passmail.net commit -- <paths>
  ```

  Stage and commit with explicit paths, never `git add -A`. A subject is
  plain: what the change does, prefixed by the part it touches
  (`tools/doc: ...`, `xactor: ...`).
- **No accidental trailer.** git reads a last body paragraph that starts with
  `word:` as a trailer (`std::` does). Start such a paragraph otherwise.
- **English** in everything written to a file: code, comments, documents,
  commit messages.
- **No em dash** (U+2014) anywhere; use a plain dash.
- **The banned word.** No file, file name or commit mentions the word that
  `veru[s]` matches, in any case: `git grep -I -i -e 'veru[s]'` prints
  nothing in any repository, and the lint checks every commit's author,
  committer and message too.
- **The licence notice.** Every source file (`.hpp`, `.cpp`, `.py`, `.mjs`,
  `.sh`, `.jam`, `Jamroot`, `Jamfile`, `build.jam`, `.yml`) opens with it,
  with `#` for Jam, Python, shell and YAML; a `#!` line stays first:

  ```
  // Copyright (c) 2026 WebCpp.org
  //
  // Distributed under the Boost Software License, Version 1.0. (See
  // accompanying file LICENSE_1_0.txt or copy at
  // https://www.boost.org/LICENSE_1_0.txt)
  ```

  An AsciiDoc file opens with it too, as `//` comments.
- **History.** Every repository starts from one import commit; the history of
  the code it was moved from is not carried over.
- **Outward actions** belong to the owner: no push, no merge, no remote
  repository created, no GitHub setting changed, no SSH key or credential
  touched by an agent.

## 12. b2 facts

Each of these was measured; each has cost time.

- **Every b2 run unsets `CPATH`, `CPLUS_INCLUDE_PATH` and `C_INCLUDE_PATH`.**
  A shell that sets them (Homebrew's often does) makes the compiler read
  another Boost before the configured one, without a word; the Jamroot
  refuses to run while one is set:

  ```
  env -u CPATH -u CPLUS_INCLUDE_PATH -u C_INCLUDE_PATH b2 ...
  ```

- **A verdict is built from scratch,** `b2 -a`: b2 compares timestamps, and
  an edit in the same second as the last build is missed.
- **`$(` inside an action is b2's, not the shell's.** b2 expands `$(name)` in
  an action's text, so a shell `$(command)` silently becomes empty; write
  command substitution with backquotes.
- **An action of more than one command opens with `set -e`,** or a failing
  command in its middle goes unnoticed.
- **`<build>no` is conditioned on the toolset,** never on a derived feature
  such as `<target-os>`: b2's evaluation of conditional requirements then
  never settles, since `<build>no` replaces every other conditional result,
  `<target-os>wasi` among them.
- **A syntax error in a Jamfile only prints,** and every target declared
  after it silently stops existing. When a target is "not found", read the
  first lines of b2's output.
- **A subproject's target is named with its project:** `b2
  libs/xactor/test//scheduler`, `b2 libs/xactor/doc//reference`.
- **`testing.launcher` applies to every toolset of one request,** so a wasm
  lane and a native one are two b2 runs.
- **With `--out-xml`, b2 exits 0 even when a test fails;** the report's exit
  status is the verdict, and the report needs `--dump-tests`.
- **b2 5.5.3's `--command-database` writes nothing,** so the compilation
  database comes from `tools/lint/compile_commands.py`, which reads b2's dry
  run (`b2 -n -a`).
- **A free feature plays no part in a target's build directory:** an
  example's output from one launcher would read as up to date under another,
  which is why `webcpp.example` always runs again.
- **wasm32-wasip2 and wasm32-wasip3 are no system b2 knows.** The Jamroot
  adds the `<target-os>wasi` value after the toolsets are loaded, so that gcc's
  Unix link options (`--start-group`, `-Bstatic`, rpath), which
  wasm-component-ld rejects, are never chosen for it.
- **Boost's location.** `boost.use-project` takes the `using boost` of
  `user-config.jam`, else `BOOST_ROOT`, else the compiler's default paths.
  Apple's clang searches `/usr/local/include` before every `-isystem`
  directory, so clang keeps Boost's directory as `-I` and marks the headers
  `<boost/...>` names as system ones (`--system-header-prefix=boost/`).
- **A checkout path that holds a space** builds: every path b2 hands to an
  action is quoted, and the tests of the build run in such a path.

## 13. Roadmap

What webcpp does not have yet, and the chapters that mention it:

- **More libraries:** wasi, a helper for building C++ as WASI HTTP
  components; trystero, a port of Trystero, serverless WebRTC rooms
  (chapter 1). Each joins `libs/` as a submodule, with its page and its
  lanes.
- **Allocators.** The mechanism by which a library lets its user customize
  the allocator of what it allocates, settled in a milestone of its own,
  which first applies it to xactor and xstate (chapter 6).
- **The emscripten lane.** b2's `emscripten` is a target already, and the CI
  gets a lane for it when emsdk is pinned, as wasi-sdk and wasmtime are;
  until then, a library that declares it fails the CI's plan (chapter 9).
  trystero is its first user.
- **Compiled Boost libraries.** The CI installs Boost's headers alone, so a
  library uses only header-only Boost, and a Boost.Test suite compiles the
  framework's header-only form (chapters 2 and 9).
- **Bundled toolchains.** Each toolchain is installed by hand and configured
  in `user-config.jam` (chapter 1), until webcpp bundles them.
