// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// Declared for native only. A build for WASI stops here, so that a program the filter should have
// skipped fails loudly instead.

#ifdef __wasi__
#error "native_only is declared for native only"
#endif

#include <webcpp/demo.hpp>

#include <boost/core/lightweight_test.hpp>

int main() {
    BOOST_TEST_EQ(webcpp::demo::answer(), 42);
    return boost::report_errors();
}
