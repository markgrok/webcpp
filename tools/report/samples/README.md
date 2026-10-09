# Samples of b2's --out-xml

Each file is what `b2 -a --dump-tests --out-xml=FILE` wrote for one lane, run
in a scratch superproject that holds the fixture library demo
(`tools/test/fixtures/demo`), or component_demo
(`tools/test/fixtures/component_demo`) with the checkout's wit-bindgen and
WIT, or browser_demo (`tools/test/fixtures/browser_demo`) with the
checkout's emsdk, and the libraries `tools/report/record_samples.py` plants
beside it. That
script records them, `python3 tools/report/record_samples.py [NAME ...]`, and
trims each of the `<os>` element (uname, which names the host), every
`<properties>` and `<sources>` element, and the actions b2 runs for itself
that succeeded: what `report.py` never reads. It writes the temporary
directory, which names the machine too, as `$TMPDIR`. Never edit a sample by
hand; record it again. `report_test.py` records every sample afresh,
untrimmed, and checks that the report reads it as it reads the committed one.

They were recorded on 2026-10-08, on macOS arm64 with B2 5.5.3, Apple clang 21
and wasi-sdk 34; the served ones with wit-bindgen 0.62.0 and wasmtime 47.0.3;
the emscripten ones with Emscripten 6.0.11 and Node 26.7.0, in a cache of
Emscripten's that the recording made, whose system libraries the first links
build and say so in their output.
The paths b2 recorded are those of the scratch superproject under `$TMPDIR`,
and the wasi-sdk is reached through a link outside the home directory, which
the script checks no sample names.

| Sample | Lane | Built | What it shows |
| --- | --- | --- | --- |
| `native-pass.xml` | `toolset=clang` | `libs/demo/test libs/demo/example` | every kind of test and example passing: run, run-fail, compile, compile-fail, the headers alone, a Boost.Test suite, a program that links Boost.JSON's definitions |
| `wasip2-pass.xml` | `toolset=clang-wasip2 testing.launcher=wasmtime` | `libs/demo/test libs/demo/example` | the same on wasip2, with exceptions as on every target, where the native-only programs and the Boost.Test suite are not built |
| `native-failures.xml` | `toolset=clang` | demo's `pass` and `rejects`, `libs/planted/test libs/planted/example` | a pass and an expected compile failure beside a test that fails to run, one that fails to compile, one that fails to link, a compile-fail test that compiles, a run-fail test that exits with 0, an example that prints otherwise and one that does not compile |
| `wasip2-empty.xml` | `toolset=clang-wasip2 testing.launcher=wasmtime` | `libs/nativeonly/test`, a library that declares native only | a lane in which every program is skipped |
| `wasip2-skipped-library.xml` | `toolset=clang-wasip2 testing.launcher=wasmtime` | `libs/demo/test libs/demo/example libs/nativeonly/test` | two libraries in one lane, one of which declares native only: demo's programs pass, and every program of nativeonly is skipped |
| `wasip2-dependency.xml` | `toolset=clang-wasip2 testing.launcher=wasmtime` | demo's `parses_json`, with `tools/boost_json.cpp` broken | a failure outside every test, and the test it keeps from running: Boost.JSON's definitions, which `parses_json` links |
| `native-odd-output.xml` | `toolset=clang` | `libs/odd/test//prints` | a failure whose output holds `]]>`, markup and a byte that is not UTF-8, which b2 writes into its CDATA as they are |
| `wasip2-served.xml` | `toolset=clang-wasip2 testing.launcher=wasmtime` | `libs/component_demo/test` | component_demo's tests passing, among them `answers`, an HTTP component that `webcpp.serve` builds, serves with wasmtime and checks, a test of type `serve` |
| `wasip2-served-failure.xml` | `toolset=clang-wasip2 testing.launcher=wasmtime` | `libs/component_demo/test`, with `answers.expected` saying 405 where the component answers 404 | a served test whose transcript differs: a run failure, whose output holds the diff and what wasmtime wrote |
| `emscripten-pass.xml` | `toolset=emscripten` | `libs/browser_demo/test libs/browser_demo/example` | browser_demo's tests and example passing under node, which b2's toolset runs itself, among them `page`, which `webcpp.link` links for a browser and never runs, a test of type `link` |
| `emscripten-driven-failure.xml` | `toolset=emscripten` | `libs/browser_demo/test/driver//driver`, with `drive.mjs` exiting with 1 | a test of `webcpp.drive` whose script fails: a run failure |
