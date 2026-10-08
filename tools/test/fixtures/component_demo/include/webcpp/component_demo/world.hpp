// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

#ifndef WEBCPP_COMPONENT_DEMO_WORLD_HPP
#define WEBCPP_COMPONENT_DEMO_WORLD_HPP

// A header of the world's bindings, which builds only for WASI: with the bindings wit-bindgen
// generates for one version and the macro of that version, WEBCPP_COMPONENT_DEMO_P2 or
// WEBCPP_COMPONENT_DEMO_P3, which /webcpp/component_demo//demo-http gives a program built for
// wasip2 or wasip3.
#if defined(WEBCPP_COMPONENT_DEMO_P2) == defined(WEBCPP_COMPONENT_DEMO_P3)
#error "webcpp/component_demo/world.hpp builds for wasip2 or wasip3, with one of their macros"
#endif

extern "C" {
#include <demo_world.h>
}

#include <string_view>

namespace webcpp::component_demo {

/** Returns the text a string of the world's bindings holds, without copying it.

    @param text A string of the bindings.
    @return A view of its bytes.
*/
inline std::string_view text_of(const demo_world_string_t& text) noexcept {
    return {reinterpret_cast<const char*>(text.ptr), text.len};
}

#ifdef WEBCPP_COMPONENT_DEMO_P2

/** Returns the WASI version whose bindings the header is built with.

    @return p2.
*/
constexpr std::string_view version() noexcept {
    return "p2";
}

#else

/** Returns the WASI version whose bindings the header is built with.

    @return p3.
*/
constexpr std::string_view version() noexcept {
    return "p3";
}

#endif

}  // namespace webcpp::component_demo

#endif
