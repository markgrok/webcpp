// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// Reads the file named by its first argument, which webcpp.run gives as the test's input file:
// node reads it from the host's disk on emscripten.

#include <boost/core/lightweight_test.hpp>

#include <fstream>
#include <string>

int main(int argc, char* argv[]) {
    if (!BOOST_TEST_EQ(argc, 2)) {
        return boost::report_errors();
    }
    std::ifstream input(argv[1]);
    std::string line;
    std::getline(input, line);
    BOOST_TEST_EQ(line, "hello");
    return boost::report_errors();
}
