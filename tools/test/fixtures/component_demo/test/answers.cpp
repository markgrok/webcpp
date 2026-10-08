// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// A served program on the world of component_demo, written on its raw bindings: each request is
// answered with its method and its target in the body, the method again in the header x-method,
// which a HEAD answer, without a body, still carries, and the status 404 for /missing, 200 for
// any other target.

#include <webcpp/component_demo.hpp>

#include <boost/throw_exception.hpp>

extern "C" {
#include <demo_world.h>
}

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {

struct answer {
    std::uint16_t status;
    std::string method;
    std::string body;
};

std::string_view view_of(const demo_world_string_t& text) {
    return {reinterpret_cast<const char*>(text.ptr), text.len};
}

std::string_view method_name(const wasi_http_types_method_t& method) {
    switch (method.tag) {
        case WASI_HTTP_TYPES_METHOD_GET: return "GET";
        case WASI_HTTP_TYPES_METHOD_HEAD: return "HEAD";
        case WASI_HTTP_TYPES_METHOD_POST: return "POST";
        case WASI_HTTP_TYPES_METHOD_PUT: return "PUT";
        case WASI_HTTP_TYPES_METHOD_DELETE: return "DELETE";
        case WASI_HTTP_TYPES_METHOD_CONNECT: return "CONNECT";
        case WASI_HTTP_TYPES_METHOD_OPTIONS: return "OPTIONS";
        case WASI_HTTP_TYPES_METHOD_TRACE: return "TRACE";
        case WASI_HTTP_TYPES_METHOD_PATCH: return "PATCH";
        default: return view_of(method.val.other);
    }
}

answer answer_to(std::string_view method, std::string_view target) {
    if (target == "/throw") {
        // No request asks for it: the call is here so that the program links
        // boost::throw_exception, which on wasip2, built without exceptions, only the handler
        // webcpp.serve links (tools/throw_exception.cpp) defines.
        boost::throw_exception(std::runtime_error("asked to throw"));
    }
    const std::uint16_t status = target == "/missing" ? 404 : 200;
    return {status, std::string(method), std::string(method) + " " + std::string(target) + "\n"};
}

// The result of append is not read: it fails only on a forbidden or malformed header, and these
// are neither.
void append(wasi_http_types_borrow_fields_t fields, const char* name, std::string_view text) {
    wasi_http_types_field_name_t key{};
    demo_world_string_set(&key, name);
    wasi_http_types_field_value_t value{
        .ptr = reinterpret_cast<std::uint8_t*>(const_cast<char*>(text.data())),
        .len = text.size(),
    };
    wasi_http_types_header_error_t error{};
    static_cast<void>(wasi_http_types_method_fields_append(fields, &key, &value, &error));
}

wasi_http_types_own_fields_t headers_of(const answer& reply) {
    const wasi_http_types_own_fields_t headers = wasi_http_types_constructor_fields();
    append(wasi_http_types_borrow_fields(headers), "content-type", "text/plain");
    append(wasi_http_types_borrow_fields(headers), "x-method", reply.method);
    return headers;
}

}  // namespace

#if defined(__wasip2__)

extern "C" void exports_wasi_http_incoming_handler_handle(
    exports_wasi_http_incoming_handler_own_incoming_request_t request,
    exports_wasi_http_incoming_handler_own_response_outparam_t out) {
    const wasi_http_types_borrow_incoming_request_t borrowed =
        wasi_http_types_borrow_incoming_request(request);
    wasi_http_types_method_t method{};
    wasi_http_types_method_incoming_request_method(borrowed, &method);
    demo_world_string_t path{};
    const bool has_path = wasi_http_types_method_incoming_request_path_with_query(borrowed, &path);
    const answer reply = answer_to(method_name(method), has_path ? view_of(path) : "/");
    wasi_http_types_method_free(&method);
    if (has_path) {
        demo_world_string_free(&path);
    }
    wasi_http_types_incoming_request_drop_own(request);

    const wasi_http_types_own_outgoing_response_t response =
        wasi_http_types_constructor_outgoing_response(headers_of(reply));
    static_cast<void>(wasi_http_types_method_outgoing_response_set_status_code(
        wasi_http_types_borrow_outgoing_response(response), reply.status));
    wasi_http_types_own_outgoing_body_t body{};
    static_cast<void>(wasi_http_types_method_outgoing_response_body(
        wasi_http_types_borrow_outgoing_response(response), &body));
    wasi_http_types_result_own_outgoing_response_error_code_t result{};
    result.val.ok = response;
    wasi_http_types_static_response_outparam_set(out, &result);

    // blocking-write-and-flush takes at most 4096 bytes a call.
    wasi_http_types_own_output_stream_t stream{};
    static_cast<void>(wasi_http_types_method_outgoing_body_write(
        wasi_http_types_borrow_outgoing_body(body), &stream));
    std::string_view pending = reply.body;
    while (!pending.empty()) {
        const std::size_t size = pending.size() < 4096 ? pending.size() : 4096;
        demo_world_list_u8_t bytes{
            .ptr = reinterpret_cast<std::uint8_t*>(const_cast<char*>(pending.data())),
            .len = size,
        };
        wasi_io_streams_stream_error_t error{};
        static_cast<void>(wasi_io_streams_method_output_stream_blocking_write_and_flush(
            wasi_io_streams_borrow_output_stream(stream), &bytes, &error));
        pending.remove_prefix(size);
    }
    wasi_io_streams_output_stream_drop_own(stream);
    wasi_http_types_error_code_t error{};
    static_cast<void>(wasi_http_types_static_outgoing_body_finish(body, nullptr, &error));
}

#elif defined(__wasip3__)

namespace {

// Waits inside the task until what is pending on waitable completes, and returns its status.
std::uint32_t wait_for(std::uint32_t waitable) {
    const demo_world_waitable_set_t set = demo_world_waitable_set_new();
    demo_world_waitable_join(waitable, set);
    demo_world_event_t event{};
    demo_world_waitable_set_wait(set, &event);
    demo_world_waitable_join(waitable, 0);
    demo_world_waitable_set_drop(set);
    return event.code;
}

}  // namespace

extern "C" demo_world_callback_code_t exports_wasi_http_handler_handle(
    exports_wasi_http_handler_own_request_t request) {
    const wasi_http_types_borrow_request_t borrowed = wasi_http_types_borrow_request(request);
    wasi_http_types_method_t method{};
    wasi_http_types_method_request_get_method(borrowed, &method);
    demo_world_string_t path{};
    const bool has_path = wasi_http_types_method_request_get_path_with_query(borrowed, &path);
    const answer reply = answer_to(method_name(method), has_path ? view_of(path) : "/");
    wasi_http_types_method_free(&method);
    if (has_path) {
        demo_world_string_free(&path);
    }
    wasi_http_types_request_drop_own(request);

    wasi_http_types_stream_u8_writer_t writer{};
    wasi_http_types_stream_u8_t contents = wasi_http_types_stream_u8_new(&writer);
    wasi_http_types_future_result_option_own_trailers_error_code_writer_t trailers_writer{};
    const wasi_http_types_future_result_option_own_trailers_error_code_t trailers =
        wasi_http_types_future_result_option_own_trailers_error_code_new(&trailers_writer);
    wasi_http_types_tuple2_own_response_future_result_void_error_code_t made{};
    wasi_http_types_static_response_new(headers_of(reply), &contents, trailers, &made);
    wasi_http_types_future_result_void_error_code_drop_readable(made.f1);
    static_cast<void>(wasi_http_types_method_response_set_status_code(
        wasi_http_types_borrow_response(made.f0), reply.status));
    exports_wasi_http_handler_result_own_response_error_code_t result{};
    result.val.ok = made.f0;
    exports_wasi_http_handler_handle_return(result);

    std::string_view pending = reply.body;
    while (!pending.empty()) {
        demo_world_waitable_status_t status = wasi_http_types_stream_u8_write(
            writer, reinterpret_cast<const std::uint8_t*>(pending.data()), pending.size());
        if (status == DEMO_WORLD_WAITABLE_STATUS_BLOCKED) {
            status = wait_for(writer);
        }
        pending.remove_prefix(DEMO_WORLD_WAITABLE_COUNT(status));
        if (DEMO_WORLD_WAITABLE_STATE(status) != DEMO_WORLD_WAITABLE_COMPLETED) {
            break;
        }
    }
    wasi_http_types_stream_u8_drop_writable(writer);
    wasi_http_types_result_option_own_trailers_error_code_t none{};
    if (wasi_http_types_future_result_option_own_trailers_error_code_write(
            trailers_writer, &none) == DEMO_WORLD_WAITABLE_STATUS_BLOCKED) {
        static_cast<void>(wait_for(trailers_writer));
    }
    wasi_http_types_future_result_option_own_trailers_error_code_drop_writable(trailers_writer);
    return DEMO_WORLD_CALLBACK_CODE_EXIT;
}

extern "C" demo_world_callback_code_t exports_wasi_http_handler_handle_callback(
    demo_world_event_t* /*event*/) {
    return DEMO_WORLD_CALLBACK_CODE_EXIT;
}

#endif
