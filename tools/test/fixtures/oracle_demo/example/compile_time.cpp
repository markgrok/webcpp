// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

#include <webcpp/oracle_demo.hpp>

#include <cstdio>

static_assert(webcpp::oracle_demo::square(4) == 16);

int main() {
    std::puts("square(4) is 16 at compile time.");
}
