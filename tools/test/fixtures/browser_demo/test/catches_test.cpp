// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// Throws and catches: exceptions work on every target.

#include <boost/core/lightweight_test.hpp>

#include <stdexcept>
#include <string>

int main() {
    std::string caught;
    try {
        throw std::runtime_error("thrown");
    } catch (std::runtime_error const& error) {
        caught = error.what();
    }
    BOOST_TEST_EQ(caught, "thrown");
    return boost::report_errors();
}
