// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

#include <webcpp/component_demo.hpp>

// Natively, the bindings put no directory on the include path.
#if __has_include(<demo_world.h>)
#error "the bindings reached a native build"
#endif

#include <string_view>

int main() {
    return std::string_view{webcpp::component_demo::world} == "demo" ? 0 : 1;
}
