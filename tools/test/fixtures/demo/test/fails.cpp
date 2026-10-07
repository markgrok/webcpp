// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// Fails on every target: a failed assertion ends the run with a nonzero status, which
// webcpp.run-fail expects.

#include <webcpp/demo.hpp>

#include <boost/core/lightweight_test.hpp>

int main() {
    BOOST_TEST_EQ(webcpp::demo::answer(), 41);
    return boost::report_errors();
}
