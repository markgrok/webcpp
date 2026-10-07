// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

#include <webcpp/oracle_demo.hpp>

#include <boost/core/lightweight_test.hpp>

int main() {
    BOOST_TEST_EQ(webcpp::oracle_demo::square(3), 9);
    BOOST_TEST_EQ(webcpp::oracle_demo::half(7), 3);
    return boost::report_errors();
}
