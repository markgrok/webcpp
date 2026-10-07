// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

#ifndef WEBCPP_DEMO_ANSWER_HPP
#define WEBCPP_DEMO_ANSWER_HPP

namespace webcpp::demo {

namespace detail {

/** Returns the sum of two values, with which twice adds a value to itself. */
template <class T>
constexpr T sum(T left, T right) noexcept {
    return left + right;
}

}  // namespace detail

/** Returns the number the fixture's test expects.

    @return 42.
*/
constexpr int answer() noexcept {
    return 42;
}

/** Returns a value added to itself.

    @tparam T An arithmetic type.
    @param value The value to double.
    @return Twice the value.
*/
template <class T>
constexpr T twice(T value) noexcept {
    return detail::sum(value, value);
}

}  // namespace webcpp::demo

#endif
