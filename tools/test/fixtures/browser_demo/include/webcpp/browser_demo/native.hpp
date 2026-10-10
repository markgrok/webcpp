// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// A header that builds only natively, against a dependency of the host's, the fake one of
// deps/include, which /webcpp/browser_demo//native brings.

#ifndef WEBCPP_BROWSER_DEMO_NATIVE_HPP
#define WEBCPP_BROWSER_DEMO_NATIVE_HPP

#include <boost/config.hpp>

// fake_dependency reports errors by throwing, and native_answer catches them: it exists only with
// exceptions, and without them (BOOST_NO_EXCEPTIONS) this header declares nothing.
#ifndef BOOST_NO_EXCEPTIONS

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

#endif  // BOOST_NO_EXCEPTIONS

#endif
