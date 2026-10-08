# webcpp

webcpp brings to C++ the libraries that other languages use for the web.
Each is a header-only C++20 library, ported with the help of coding agents
from a widely used original at an exact version, and proven against that
original; or a library of webcpp's own. webcpp follows Boost's guidelines and
model: this repository is the superproject, the equivalent of
`boostorg/boost`, each library has a repository of its own under
[webcpporg](https://github.com/webcpporg), checked out as a submodule under
`libs/<name>`, and everything is built, tested and documented with b2.

## The libraries

| Library | What it is | Targets |
| --- | --- | --- |
| [xactor](https://github.com/webcpporg/xactor) | A header-only, deterministic actor system: actors that handle one message at a time, with fuel per execution, timers and a lifecycle. | native, wasip2, wasip3 |
| [xstate](https://github.com/webcpporg/xstate) | A header-only port of XState's state machines and actors: machines read from XState's JSON config, stepped by XState's pure functions or run as actors on xactor. Ports XState 5.33.2, and is proven against it. | native, wasip2, wasip3 |
| [pratt](https://github.com/webcpporg/pratt) | A header-only Pratt parser engine, generic through concepts, with a calculator built on it, exact in decimal by default; a library of webcpp's own. | native, wasip2, wasip3 |
| [wasi](https://github.com/webcpporg/wasi) | Header-only helpers for C++ built as WebAssembly components: the HTTP handler a component exports on wasip2 and wasip3, and the macros a program writes its main between; a library of webcpp's own. | wasip2, wasip3 (its response also natively) |

trystero (a port of Trystero's serverless WebRTC rooms) is being moved here.
Each library's page, with its API reference, and the test matrix of every
library on every target are published at <https://webcpporg.github.io/webcpp/>.

## Prerequisites

- Boost 1.92 or newer, installed;
- b2;
- a C++20 compiler;
- Python 3.9 or newer, which compares the examples with their expected output
  and runs the tests of the build itself;
- for WebAssembly, wasi-sdk 34, whose clang builds for wasm32-wasip2 and
  wasm32-wasip3, and wasmtime 47, which runs what it builds;
- for WebAssembly components, such as wasi's, wit-bindgen 0.62.0, which
  generates the C bindings of a component's world, and the `wasi:http` WIT
  of WASI 0.2.12 and 0.3.0, against which a world resolves its packages; and
  wasmtime, which serves the components;
- for the documentation, Node, which runs Asciidoctor.js, MrDocs 2026.9.29,
  which writes each library's API reference, and clang++; and wit-bindgen
  and the WIT, since wasi's reference reads its bindings;
- for a library's oracle lane, which runs the original it ports against the
  same cases and examples, Node and npm;
- for the lint, wasi-sdk 34, whose clang-format and clang-tidy it runs, the
  wasip2 and wasip3 toolsets below, wit-bindgen and the WIT, since it reads
  what those toolsets compile, and Node, with which it installs Pyright.

b2 refuses to run while `CPATH`, `CPLUS_INCLUDE_PATH` or `C_INCLUDE_PATH` is
set, since the compiler would read another Boost from them before the
configured one. Unset them in the shell you build from:

    unset CPATH CPLUS_INCLUDE_PATH C_INCLUDE_PATH

## Getting started

Clone the superproject with its libraries, and test them:

    git clone --recursive https://github.com/webcpporg/webcpp
    cd webcpp
    b2 test

When Boost is not on the compiler's default include path, as with Homebrew's
on macOS, the build stops at once and says what to configure:

    error: Boost 1.92 or newer was not found: no `using boost` names its location, and none is on the compiler's default include path
    error: Boost 1.92.0 is installed in /opt/homebrew/opt/boost: configure it in user-config.jam with this line, in place of any other `using boost`:
    error:     using boost : 1.92 : <include>/opt/homebrew/opt/boost/include <library>/opt/homebrew/opt/boost/lib ;

b2 reads `user-config.jam` from your home directory. Write that line there,
after the toolset of your compiler (`using clang ;`, `using gcc ;` or
`using msvc ;`), so that `~/user-config.jam` reads, for Homebrew's Boost and
clang:

    using clang ;
    using boost : 1.92 : <include>/opt/homebrew/opt/boost/include <library>/opt/homebrew/opt/boost/lib ;

and run `b2 test` again. It checks the Boost it found, which it reports on a
line of its configuration checks,

    - Boost 1.92 or newer in /opt/homebrew/opt/boost/include (1.92.0) : yes [1]

then builds and runs every library's tests.

The other aggregates work the same way:

| Command | What it does |
| --- | --- |
| `b2 test` | builds and runs every library's tests |
| `b2 example` | builds and runs every library's examples, and compares each one's output with the `.expected` file beside it |
| `b2 doc` | builds the index page, `doc/html/index.html`, and each library's page, `libs/<name>/doc/html/index.html` |
| `b2 install --prefix=<dir>` | copies every library's headers to `<dir>/include/webcpp/`, for CMake or a plain compiler |
| `b2 libs/<name>/test` | one library's tests; `libs/<name>/example` and `libs/<name>/doc` likewise |
| `b2 libs/<name>/test/oracle//oracle` | a port's oracle lane: the original it ports runs the same cases and a twin of each example, and the results must be the port's |
| `b2 -a ...` | the same, from scratch: b2 compares timestamps, so only a build from scratch is a result |

A b2 project uses a library through `/webcpp/<name>//<name>`, which adds its
headers and Boost's.

### WebAssembly

Each library declares the targets it is built for. To build them for
wasm32-wasip2 and wasm32-wasip3, register two clang toolsets against
wasi-sdk 34 in `~/user-config.jam`:

    local wasi-sdk = /path/to/wasi-sdk ;
    using clang : wasip2 : $(wasi-sdk)/bin/clang++
      : <cflags>--target=wasm32-wasip2 <cxxflags>--target=wasm32-wasip2
        <linkflags>--target=wasm32-wasip2
        <archiver>$(wasi-sdk)/bin/llvm-ar <ranlib>$(wasi-sdk)/bin/llvm-ranlib ;
    using clang : wasip3 : $(wasi-sdk)/bin/clang++
      : <cflags>--target=wasm32-wasip3 <cxxflags>--target=wasm32-wasip3
        <linkflags>--target=wasm32-wasip3
        <archiver>$(wasi-sdk)/bin/llvm-ar <ranlib>$(wasi-sdk)/bin/llvm-ranlib ;

and run the tests and the examples with wasmtime, one toolset per command:

    b2 toolset=clang-wasip2 testing.launcher=wasmtime test example
    b2 toolset=clang-wasip3 testing.launcher=wasmtime test example

On wasip2 a library builds without exceptions, a portability policy, since
some WebAssembly hosts lack exception handling. Everywhere else, whether a
program uses exceptions is the choice of whoever builds it: webcpp builds no
variant without them, and none without RTTI. A program that a library does
not declare for a target is skipped there.
`b2 declared-targets -d0` lists the targets each library declares.

A library may also run some of its programs in lanes of its own, which
`test` and `example` leave out: the HTTP components wasmtime serves, for
one. `b2 declared-lanes -d0` lists them, each with the target it runs on,
and one runs as

    b2 toolset=clang-wasip2 testing.launcher=wasmtime libs/<name>/test//<lane>

A component's bindings are generated by wit-bindgen when a WASI toolset
builds it, so a native build never needs wit-bindgen or the WIT. b2 finds
wit-bindgen where `-sWIT_BINDGEN=<path>` says, else at
`.local/wit-bindgen/wit-bindgen`, else on `PATH`; the WIT of each version
where `-sWASI_WIT_P2=<dir>` and `-sWASI_WIT_P3=<dir>` say, each the
`wit/deps` directory of the Rust crate `wasip2` 1.0.4 or `wasip3` 0.9.0,
else in `.local/wasi-wit/p2` and `.local/wasi-wit/p3`; and the wasmtime that
serves a component where `-sWASMTIME=<path>` says, else on `PATH`. When one
is needed and not there, the build stops, naming it and every place it
looked.

## Documentation

    b2 doc

builds the index page and each library's page, with its API reference from
MrDocs. MrDocs is found at `.local/mrdocs/bin/mrdocs`, on `PATH`, or where
`-sMRDOCS=<path>` says, and the build stops, naming where it looked, when it
is in none of them; clang++ is found on `PATH`, or where `-sCLANG=<path>`
says. The Node packages are installed by `npm ci` on first use, once per
`package-lock.json`, under `tools/doc/.node-modules/`, and linked at
`tools/doc/node_modules`, so that doc builds at once share them.

The build is strict: a public symbol without a Doc Comment, a template
parameter without `@tparam`, a `detail` symbol without a brief, and a Doc
Comment's `@see "<title>"` that names no section of its library's page each
fail it, naming the symbol and the file.

## Linting

    tools/lint/lint.sh --clang-format <wasi-sdk>/bin/clang-format --clang-tidy <wasi-sdk>/bin/clang-tidy

lints the superproject and every library under `libs/`, and names each rule
that fails. `--shard K/N` analyses one of N slices of the files with
clang-tidy, which takes most of the time, and runs every other rule.

## The tests of the tools

The build and its tools have tests of their own, each a Python script run
from the root, such as `python3 tools/test/jamroot_test.py`:
`tools/test/*_test.py` for the Jamroot, `tools/webcpp.jam`, the oracle's
rules, the rules of a WebAssembly component and the documentation build, and
`tools/<tool>/*_test.py` for the oracle, the lint, the report, the
documentation, the example runner, the server of a component, the installer
of the Node packages and the CI's scripts.

## Contributing

Every library is developed inside a checkout of the superproject, as a Boost
library is developed inside Boost. [AGENTS.md](AGENTS.md) holds every rule a
contributor, human or agent, needs to port a library or change one: the
layout, the names, the build, the tests, the documentation, the evidence a
port gives and how a change is made.

## License

Distributed under the [Boost Software License, Version 1.0](LICENSE_1_0.txt).
