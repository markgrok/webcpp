// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// Does not compile, on any target, which webcpp.compile-fail expects.

#include <webcpp/demo.hpp>

static_assert(webcpp::demo::answer() == 41, "the answer is 42");
