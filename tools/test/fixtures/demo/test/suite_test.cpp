// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// A Boost.Test suite, native only. A build for WASI stops here, so that a suite the filter should
// have skipped fails loudly instead. It prints how its own sources were built, which the tests of
// tools/test read from its output: whether the compiler defined __cpp_exceptions and __cpp_rtti.

#ifdef __wasi__
#error "a Boost.Test suite is built for native only"
#endif

#include <webcpp/demo.hpp>

#include <boost/test/unit_test.hpp>

#include <cstdio>

BOOST_AUTO_TEST_CASE(prints_how_it_was_built) {
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
}

BOOST_AUTO_TEST_CASE(answers) {
    BOOST_TEST(webcpp::demo::answer() == 42);
}

BOOST_AUTO_TEST_CASE(doubles) {
    BOOST_TEST_REQUIRE(webcpp::demo::twice(21) == 42);
    BOOST_TEST(webcpp::demo::twice(0) == 0);
}
