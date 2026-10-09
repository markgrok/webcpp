// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// On emscripten, a program is wasm32: a pointer holds four bytes.

#include <boost/core/lightweight_test.hpp>

int main() {
#ifdef __EMSCRIPTEN__
    BOOST_TEST_EQ(sizeof(void*), 4U);
#else
    BOOST_TEST(sizeof(void*) >= 4U);
#endif
    return boost::report_errors();
}
