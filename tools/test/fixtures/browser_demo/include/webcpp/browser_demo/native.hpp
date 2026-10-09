// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// A header that builds only natively, against a dependency of the host's, the fake one of
// deps/include, which reports errors by throwing: it needs exceptions, which
// /webcpp/browser_demo//native declares.

#ifndef WEBCPP_BROWSER_DEMO_NATIVE_HPP
#define WEBCPP_BROWSER_DEMO_NATIVE_HPP

#include <boost/config.hpp>

#ifdef BOOST_NO_EXCEPTIONS
#error "<webcpp/browser_demo/native.hpp> needs exceptions: fake_dependency throws"
#endif

#include <fake_dependency.hpp>

namespace webcpp::browser_demo {

/** Returns the answer the fake dependency gives to a question, or nothing when it refuses.

    @param question The question, which the dependency refuses when it is negative.
    @return The answer, or -1 when the dependency refuses the question.
*/
inline int native_answer(int question) noexcept {
    try {
        return fake_dependency::answer(question);
    } catch (fake_dependency::refusal const&) {
        return -1;
    }
}

}  // namespace webcpp::browser_demo

#endif
