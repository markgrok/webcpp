// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// The Jamroot's configuration check: this compiles only against Boost 1.92 or newer.

#include <boost/version.hpp>

static_assert(BOOST_VERSION >= 109200);
