// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// A header that builds only on emscripten: it reads the page through Emscripten's own
// <emscripten/val.h>.

#ifndef WEBCPP_BROWSER_DEMO_PAGE_HPP
#define WEBCPP_BROWSER_DEMO_PAGE_HPP

// Like Emscripten's own headers, <emscripten/wire.h> among them, which declares a binding of long
// and one of int64_t, page.hpp holds only for wasm32's types: a native parse on a 64-bit host
// stops here, first.
static_assert(sizeof(long) == 4, "page.hpp is read for wasm32");

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
