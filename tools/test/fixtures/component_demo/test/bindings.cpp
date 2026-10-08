// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

#include <webcpp/component_demo.hpp>

#include <demo_world.h>

// A world-level name of the bindings, renamed demo_world.
static_assert(sizeof(demo_world_string_t) > 0);

int main() {
    demo_world_string_t text{};
    return static_cast<int>(text.len);
}
