# webcpp

webcpp is a collection of header-only C++20 libraries that bring to C++ the
libraries other languages use for the web. It follows Boost's guidelines and
model: this repository is the superproject, each library has a repository of
its own under `libs/<name>`, and everything is built and tested with b2.

## Prerequisites

- Boost 1.92 or newer, installed;
- b2;
- a C++20 compiler;
- Python 3.9 or newer, which compares the examples with their expected output
  and runs the tests of the build itself;
- for the lint, wasi-sdk 34, whose clang-format and clang-tidy it runs, and
  Node, with which it installs Pyright;
- for the documentation, Node, which runs Asciidoctor.js, MrDocs 2026.9.29,
  which writes each library's API reference, and clang++.

If Boost is not on the compiler's default include path, tell b2 where it is
in `user-config.jam`. For Homebrew's Boost:

    using boost : 1.92 : <include>/opt/homebrew/opt/boost/include <library>/opt/homebrew/opt/boost/lib ;

b2 refuses to run while `CPATH`, `CPLUS_INCLUDE_PATH` or `C_INCLUDE_PATH` is
set, since the compiler would read another Boost from them.

## Building

    git clone --recursive https://github.com/webcpporg/webcpp
    cd webcpp
    b2 test

`b2 libs/<name>/test` tests one library, and
`b2 install --prefix=<dir>` copies every library's headers to
`<dir>/include/webcpp/`.

## Documentation

    b2 doc

builds the index page, `doc/html/index.html`, and each library's page,
`libs/<name>/doc/html/index.html`, with its API reference from MrDocs;
`b2 libs/<name>/doc` builds one. A public symbol without a Doc Comment, a
template parameter without `@tparam` and a `detail` symbol without a brief
each fail the build, naming the symbol and the file; so does a Doc Comment's
`@see "<title>"` that names no section of its library's page. MrDocs is
found at `.local/mrdocs/bin/mrdocs`, on `PATH`, or where `-sMRDOCS=<path>`
says; clang++ on `PATH`, or where `-sCLANG=<path>` says. The Node packages are
installed into `tools/doc/node_modules` by `npm ci` on first use. The tests of
the documentation's tools are `tools/doc/*_test.py` and
`tools/test/doc_test.py`.

## Linting

    tools/lint/lint.sh --clang-format <wasi-sdk>/bin/clang-format --clang-tidy <wasi-sdk>/bin/clang-tidy

lints the superproject and every library under `libs/`, and names each rule
that fails. `--shard K/N` analyses one of N slices of the files with
clang-tidy, which takes most of the time, and runs every other rule.
`python3 tools/lint/lint_test.py` tests the lint itself.
