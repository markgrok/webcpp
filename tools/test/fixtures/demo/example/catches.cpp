// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// A throw caught: it prints only where exceptions work.

#include <cstdio>
#include <exception>
#include <stdexcept>

int main() {
    try {
        throw std::runtime_error("boom");
    } catch (const std::exception& failure) {
        std::printf("caught: %s\n", failure.what());
    }
}
