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
| [pratt](https://github.com/webcpporg/pratt) | A header-only Pratt parser engine, generic through concepts, with a calculator built on it, exact in decimal by default; a library of webcpp's own. | native, emscripten, wasip2, wasip3 |
| [wasi](https://github.com/webcpporg/wasi) | Header-only helpers for C++ built as WebAssembly components: the HTTP handler a component exports on wasip2 and wasip3, and the macros a program writes its main between; a library of webcpp's own. | wasip2, wasip3 (its response also natively) |
| [trystero](https://github.com/webcpporg/trystero) | Serverless WebRTC rooms, wire compatible with Trystero: peers meet over public Nostr relays, natively over libdatachannel and in the browser over its own WebRTC. Ports Trystero 0.26.0, and is proven against it. | native, emscripten |

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
- for emscripten, Emscripten 6.0.11 from emsdk, and Node, which runs what it
  builds;
- for trystero, libsecp256k1 0.8.0, natively and built with Emscripten, and,
  for its native backend, libdatachannel 0.24.6 and OpenSSL 3 (below);
- for WebAssembly components, such as wasi's, wit-bindgen 0.62.0, which
  generates the C bindings of a component's world, and the `wasi:http` WIT
  of WASI 0.2.12 and 0.3.0, against which a world resolves its packages; and
  wasmtime, which serves the components;
- for the documentation, Node, which runs Asciidoctor.js, MrDocs 2026.9.29,
  which writes each library's API reference, and clang++; wit-bindgen and
  the WIT, since wasi's reference reads its bindings; and emsdk's headers and
  trystero's libraries, since trystero's reference reads its browser and
  native backends;
- for a library's oracle lane, which runs the original it ports against the
  same cases and examples, Node and npm;
- for the lint, wasi-sdk 34, whose clang-format and clang-tidy it runs, the
  wasip2, wasip3 and emscripten toolsets below, wit-bindgen, the WIT and
  trystero's libraries, since it reads what those toolsets compile, and Node,
  with which it installs Pyright.

b2 refuses to run while `CPATH`, `CPLUS_INCLUDE_PATH` or `C_INCLUDE_PATH` is
set, since the compiler would read another Boost from them before the
configured one. Unset them in the shell you build from:

    unset CPATH CPLUS_INCLUDE_PATH C_INCLUDE_PATH

## Getting started

Clone the superproject with its libraries, and test them:

    git clone --recursive https://github.com/webcpporg/webcpp
    cd webcpp
    b2 test

On a machine without the three libraries trystero needs ("trystero's
libraries", below), `b2 test` builds and runs every other library's tests and
leaves trystero's out, saying so once for each library it did not find, with
where it looked and how to give it:

    webcpp: trystero is left out: libsecp256k1 was not found: -sSECP256K1_ROOT=<dir> was not given, and /path/to/webcpp/.local/secp256k1-native/include holds no secp256k1.h, nor does /usr/include or /usr/local/include. ...

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

then builds and runs every library's tests, trystero's once its three
libraries are found ("trystero's libraries", below).

The other aggregates work the same way:

| Command | What it does |
| --- | --- |
| `b2 test` | builds and runs every library's tests |
| `b2 example` | builds and runs every library's examples, and compares each one's output with the `.expected` file beside it |
| `b2 doc` | builds the index page, `doc/html/index.html`, and each library's page, `libs/<name>/doc/html/index.html`; a library left out, as trystero without its libraries, is named on the index without a link, and has no page |
| `b2 install --prefix=<dir>` | copies every library's headers to `<dir>/include/webcpp/`, for CMake or a plain compiler, and its licence files beside them, in `<dir>/include/webcpp/<name>/` |
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
    modules.poke : WASI_SDK : $(wasi-sdk) ;
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

Every target builds with exceptions: whether a program uses them is the
choice of whoever builds it, every library supports a build without them,
and webcpp builds none without RTTI. Each library has its own `WEBCPP_<NAME>_NO_EXCEPTIONS`, in
`<webcpp/<name>/config.hpp>`, as Boost.Asio has `BOOST_ASIO_NO_EXCEPTIONS`:
defined in a build without exceptions, and definable by a program to turn a
library's exceptions off in a build that has them. A library raises an
exception through `boost::throw_exception` alone. A program that a library
does not declare for a target is skipped there.
`b2 declared-targets -d0` lists the targets each library declares.

A library may also run some of its programs in lanes of its own, which
`test` and `example` leave out: the HTTP components wasmtime serves, for
one. `b2 declared-lanes -d0` lists them, each with the target it runs on
and its kind, `original` when it runs the original's language, which needs
Node, else `programs`, and one runs as

    b2 toolset=clang-wasip2 testing.launcher=wasmtime libs/<name>/test//<lane>

A component's bindings are generated by wit-bindgen when a WASI toolset
builds it, or when a native build names the explicit target
`<bindings>-headers`, as wasi's API reference does to parse them; so
`b2 test` with the host's toolset never needs wit-bindgen or the WIT, and
`b2 doc` does. b2 finds
wit-bindgen where `-sWIT_BINDGEN=<path>` says, else at
`.local/wit-bindgen/wit-bindgen`, else on `PATH`; the WIT of each version
where `-sWASI_WIT_P2=<dir>` and `-sWASI_WIT_P3=<dir>` say, each the
`wit/deps` directory of the Rust crate `wasip2` 1.0.4 or `wasip3` 0.9.0,
else in `.local/wasi-wit/p2` and `.local/wasi-wit/p3`; and the wasmtime that
serves a component where `-sWASMTIME=<path>` says, else on `PATH`. When one
is needed and not there, the build stops, naming it and every place it
looked.

### Emscripten

A library that declares emscripten, as trystero does, is built for it with
b2's `emscripten` toolset, registered against Emscripten 6.0.11 from emsdk in
`~/user-config.jam`, where `/path/to/emsdk` is the emsdk's directory and
`/path/to/node` the node that runs a program:

    local emsdk = /path/to/emsdk ;
    local node = /path/to/node ;
    using emscripten : : $(emsdk)/upstream/emscripten/em++ : <nodejs>$(node) ;

It builds wasm32, single-threaded and static, and runs each test and example
with node itself, so it takes no `testing.launcher`:

    b2 toolset=emscripten libs/trystero/test libs/trystero/example

A program for a browser, which node cannot run, is linked and never run.

### trystero's libraries

trystero needs three libraries that webcpp does not build yet: libsecp256k1
0.8.0, natively and built with Emscripten, and, for its native backend,
libdatachannel 0.24.6, built with the compiler and the standard library that
build the programs, and OpenSSL 3. Its page says how each is built. The
build finds each where `-sSECP256K1_ROOT=<dir>`,
`-sSECP256K1_EMSCRIPTEN_ROOT=<dir>`, `-sLIBDATACHANNEL_ROOT=<dir>` and
`-sOPENSSL_ROOT=<dir>` on b2's command line say, each the directory of its
`include/` and `lib/`, never the environment, else in
`.local/secp256k1-native`, `.local/secp256k1-emscripten`,
`.local/libdatachannel` and `.local/openssl` of the checkout, where the CI
installs them, else, natively outside Windows, in `/usr/include` or
`/usr/local/include`, where a system install is legitimate; a relative `-s`
is read from b2's working directory. When none holds a library's header,
trystero is left out, its tests and examples skipped, with one line that
names the library and every place it looked, and every other library
builds; `b2 doc` then names trystero on the index without a link, and makes
no page for it, and the lint stops, naming the library it did not find.
`webcpp-require-external=on` on b2's command line, which the CI gives, stops
the build instead.

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
library is developed inside Boost. [CONTRIBUTING.md](CONTRIBUTING.md) is the
way in: what webcpp asks of a library, how to propose one, and how a change
is made and accepted. [AGENTS.md](AGENTS.md) holds every rule a
contributor, human or agent, needs to port a library or change one: the
layout, the names, the build, the tests, the documentation, the evidence a
port gives and how a change is made.

## License

Distributed under the [Boost Software License, Version 1.0](LICENSE_1_0.txt).
