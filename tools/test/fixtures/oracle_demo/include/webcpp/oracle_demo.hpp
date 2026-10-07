// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

#ifndef WEBCPP_ORACLE_DEMO_HPP
#define WEBCPP_ORACLE_DEMO_HPP

namespace webcpp::oracle_demo {

/** Returns a value multiplied by itself.

    @param value The value to square.
    @return The value times itself.
*/
constexpr int square(int value) noexcept {
    return value * value;
}

/** Returns half of a value, rounded toward zero, where JavaScript keeps the fraction.

    @param value The value to halve.
    @return The value divided by two, as an integer.
*/
constexpr int half(int value) noexcept {
    return value / 2;
}

}  // namespace webcpp::oracle_demo

#endif
