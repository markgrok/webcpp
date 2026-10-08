// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

#include <webcpp/component_demo.hpp>

#include <demo_world.h>

// A program that names a type of the bindings at the world level, where wit-bindgen
// writes the world renamed demo_world: it compiles only with the bindings of its target.
int main() {
    const demo_world_string_t text{};
    return static_cast<int>(text.len);
}
