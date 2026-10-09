// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

#ifndef WEBCPP_BROWSER_DEMO_HPP
#define WEBCPP_BROWSER_DEMO_HPP

#include <string_view>

namespace webcpp::browser_demo {

/** Returns the word the fixture's example greets with.

    @return The word "hello".
*/
constexpr std::string_view greeting() noexcept {
    return "hello";
}

}  // namespace webcpp::browser_demo

#endif
