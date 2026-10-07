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
  and runs the tests of the build itself.

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
