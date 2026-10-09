// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// A dependency of the host's, as a library installed outside webcpp is, which reports errors by
// throwing. Its warnings are not webcpp's: .clang-tidy's HeaderFilterRegex reports nothing here.

#ifndef FAKE_DEPENDENCY_HPP
#define FAKE_DEPENDENCY_HPP

#include <stdexcept>

namespace fake_dependency {

// What answer throws for a question it refuses.
class refusal : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// The answer to question, which must not be negative.
inline int answer(int question) {
    if (question < 0) {
        throw refusal("a negative question");
    }
    return 42;
}

}  // namespace fake_dependency

#endif
