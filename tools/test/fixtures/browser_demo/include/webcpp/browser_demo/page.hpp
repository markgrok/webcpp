// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// A header that builds only on emscripten: it reads the page through Emscripten's own
// <emscripten/val.h>.

#ifndef WEBCPP_BROWSER_DEMO_PAGE_HPP
#define WEBCPP_BROWSER_DEMO_PAGE_HPP

#include <emscripten/val.h>

#include <string>

namespace webcpp::browser_demo {

/** Returns the title of the page the program runs in.

    @return The title of the page's document.
*/
inline std::string page_title() {
    return emscripten::val::global("document")["title"].as<std::string>();
}

}  // namespace webcpp::browser_demo

#endif
