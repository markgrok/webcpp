// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// Passes on every target, and prints how it was built, which the tests of tools/test read from
// its output: whether the compiler defined __cpp_exceptions and __cpp_rtti, which
// -fno-exceptions and -fno-rtti leave undefined.

#include <webcpp/demo.hpp>

#include <boost/core/lightweight_test.hpp>
#include <boost/throw_exception.hpp>

#include <cstdio>
#include <stdexcept>

// A throw that escapes main ends the run, which fails the test, as it should.
// NOLINTNEXTLINE(bugprone-exception-escape)
int main(int argc, char** /*argv*/) {
    // Never taken, since no test passes an argument, but a throw site the compiler keeps: built
    // without exceptions, the program links only with the handler of tools/throw_exception.cpp.
    if (argc > 1) {
        boost::throw_exception(std::invalid_argument("pass takes no argument"));
    }
#ifdef __cpp_exceptions
    std::puts("__cpp_exceptions: defined");
#else
    std::puts("__cpp_exceptions: undefined");
#endif
#ifdef __cpp_rtti
    std::puts("__cpp_rtti: defined");
#else
    std::puts("__cpp_rtti: undefined");
#endif
    BOOST_TEST_EQ(webcpp::demo::answer(), 42);
    return boost::report_errors();
}
