// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// Parses and serializes JSON on every target, natively also without exceptions and RTTI: it
// links only with the definitions of Boost.JSON that /webcpp//boost_json compiles.

#include <webcpp/demo.hpp>

#include <boost/core/lightweight_test.hpp>
#include <boost/json.hpp>
#include <boost/system/error_code.hpp>

#include <cstdint>
#include <string_view>

int main() {
    constexpr std::string_view text = R"({"answer": 42})";
    boost::system::error_code error;
    const boost::json::value parsed = boost::json::parse(text, error);
    if (!BOOST_TEST(!error)) {
        return boost::report_errors();
    }
    const boost::json::object* object = parsed.if_object();
    if (!BOOST_TEST(object != nullptr)) {
        return boost::report_errors();
    }
    const boost::json::value* answer = object->if_contains("answer");
    if (!BOOST_TEST(answer != nullptr) || !BOOST_TEST(answer->is_int64())) {
        return boost::report_errors();
    }
    BOOST_TEST_EQ(answer->get_int64(), std::int64_t{webcpp::demo::answer()});
    BOOST_TEST_EQ(boost::json::serialize(parsed), R"({"answer":42})");
    return boost::report_errors();
}
