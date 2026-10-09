// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// Parses JSON with the definitions of Boost.JSON, on every target.

#include <boost/core/lightweight_test.hpp>
#include <boost/json/parse.hpp>
#include <boost/json/value.hpp>

int main() {
    boost::json::value const parsed = boost::json::parse(R"({"answer": 42})");
    BOOST_TEST_EQ(parsed.at("answer").as_int64(), 42);
    return boost::report_errors();
}
