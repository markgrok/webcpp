---
name: webcpp-build-and-lanes
description: "Build and test webcpp: targets (native, wasip2, wasip3, emscripten), a library's lanes and own lanes, the Jamfile rules, the report, CI, and what counts as green."
---

# Building and testing webcpp

The rules are in `AGENTS.md`: chapter 1 ("Prerequisites", "The build commands"), chapter 9
(Targets, The Jamfile API, Tests, Lanes, The report, CI), chapter 10 (Process) and chapter 12 (b2
facts). The CI is `.github/workflows/library.yml`, which `ci.yml` and each library call.

## Iterating on one library
```
unset CPATH CPLUS_INCLUDE_PATH C_INCLUDE_PATH
b2 libs/<name>/test libs/<name>/example
b2 toolset=clang-wasip2 testing.launcher=wasmtime libs/<name>/test libs/<name>/example   # and clang-wasip3
b2 toolset=emscripten libs/<name>/test libs/<name>/example                                 # no launcher
b2 declared-targets -d0 && b2 declared-lanes -d0                                           # what CI will run
```
One toolset per command. Test and example Jamfiles use only the `webcpp.*` rules of chapter 9.

## A lane, as CI runs it
`b2 -a --dump-tests --out-xml=<lane>.xml toolset=<toolset> libs/<name>/test libs/<name>/example`,
then `tools/report/report.py`; b2's exit status is not the verdict. `tools/ci/matrix.py` runs
plan, lane and own lane the CI's way. Parallel lanes use distinct `--build-dir`.

## Green, before asking for a merge (chapter 10)
1. Every declared lane and own lane from scratch (`b2 -a`), oracle included.
2. `b2 -a doc`.
3. `tools/lint/lint.sh ...` prints `lint: clean`.
4. Every `tools/**/*_test.py` whose subject changed.
5. CI green, the library's and the superproject's.

## When something is odd
Read chapter 12 before debugging b2: most surprises are recorded there.
