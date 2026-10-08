// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// The Boost.Test framework of one suite, header-only, its module named by BOOST_TEST_MODULE,
// which tools/webcpp.jam defines from the suite's name. webcpp.boost-test compiles it as an
// object of its own, always with exceptions on, so that a user who builds without them turns
// them off in the suite's own sources alone: Boost.Test 1.92 has an unguarded try
// (unit_test_main.ipp) that GCC rejects without exceptions, and built without them by clang, a
// failed BOOST_TEST_REQUIRE never ends the run.

#include <boost/test/included/unit_test.hpp>
