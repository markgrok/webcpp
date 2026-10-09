// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// Greets the name its standard input holds, which node reads on emscripten.

// tag::hello[]
#include <webcpp/browser_demo.hpp>

#include <iostream>
#include <string>

int main() {
    std::string name;
    std::getline(std::cin, name);
    std::cout << webcpp::browser_demo::greeting() << ", " << name << '\n';
}

// end::hello[]
