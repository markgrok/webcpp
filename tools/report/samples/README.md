# Samples of b2's --out-xml

Each file is what `b2 -a --dump-tests --out-xml=FILE` wrote for one lane, run
in a scratch superproject that holds the fixture library demo
(`tools/test/fixtures/demo`) and the libraries
`tools/report/record_samples.py` plants beside it. That script records them,
`python3 tools/report/record_samples.py [NAME ...]`, and trims each of the
`<os>` element (uname, which names the host), every `<properties>` and
`<sources>` element, and the actions b2 runs for itself that succeeded: what
`report.py` never reads. Never edit a sample by hand; record it again.
`report_test.py` records every sample afresh, untrimmed, and checks that the
report reads it as it reads the committed one.

They were recorded on 2026-10-07 on macOS arm64 with B2 5.5.3, Apple clang 21
and wasi-sdk 34. The paths b2 recorded are those of the scratch superproject
under `$TMPDIR`, and the wasi-sdk is reached through a link outside the home
directory, which the script checks no sample names.

| Sample | Lane | Built | What it shows |
| --- | --- | --- | --- |
| `native-pass.xml` | `toolset=clang` | `libs/demo/test libs/demo/example` | every kind of test and example passing: run, run-fail, compile, compile-fail, the headers alone, a Boost.Test suite, a program that links Boost.JSON's definitions |
| `wasip2-pass.xml` | `toolset=clang-wasip2 testing.launcher=wasmtime` | `libs/demo/test libs/demo/example` | the same on wasip2, where the native-only programs, the Boost.Test suite and `catches` are not built |
| `native-failures.xml` | `toolset=clang` | demo's `pass` and `rejects`, `libs/planted/test libs/planted/example` | a pass and an expected compile failure beside a test that fails to run, one that fails to compile, one that fails to link, a compile-fail test that compiles, a run-fail test that exits with 0, an example that prints otherwise and one that does not compile |
| `wasip2-empty.xml` | `toolset=clang-wasip2 testing.launcher=wasmtime` | `libs/nativeonly/test`, a library that declares native only | a lane in which every program is skipped |
| `wasip2-dependency.xml` | `toolset=clang-wasip2 testing.launcher=wasmtime` | demo's `pass`, with `tools/throw_exception.cpp` broken | a failure outside every test, and the test it keeps from running: on wasip2 every program is built without exceptions and links the handler |
| `native-odd-output.xml` | `toolset=clang` | `libs/odd/test//prints` | a failure whose output holds `]]>`, markup and a byte that is not UTF-8, which b2 writes into its CDATA as they are |
