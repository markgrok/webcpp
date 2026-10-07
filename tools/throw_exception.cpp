// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// What a throw becomes in a program built without exceptions: Boost declares both overloads of
// boost::throw_exception and leaves their definitions to the program. These report what was
// thrown on the standard error and abort. tools/webcpp.jam links this file into every program it
// builds without exceptions.

#include <boost/assert/source_location.hpp>
#include <boost/config.hpp>
#include <boost/throw_exception.hpp>

#include <cstdio>
#include <cstdlib>
#include <exception>

#ifdef BOOST_NO_EXCEPTIONS

namespace boost {

// The result of each write is discarded: the next statement ends the process either way.

void throw_exception(const std::exception& failure) {
    static_cast<void>(std::fprintf(stderr, "throw_exception: %s\n", failure.what()));
    std::abort();
}

void throw_exception(const std::exception& failure, const source_location& location) {
    static_cast<void>(std::fprintf(stderr, "throw_exception: %s at %s:%u\n", failure.what(),
                                   location.file_name(), static_cast<unsigned>(location.line())));
    std::abort();
}

}  // namespace boost

#endif
