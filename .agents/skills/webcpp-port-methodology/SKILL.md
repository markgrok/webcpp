---
name: webcpp-port-methodology
description: "Port a library from another language into webcpp, or specify such a port: choosing and pinning the original, its licence, the oracle and twins, and fidelity."
---

# Porting a library

The rules are in `AGENTS.md`: chapter 2 ("Choosing"), chapter 4 (Fidelity), chapter 5 (Evidence:
oracle and twins) and chapter 10 ("Porting a library, step by step"). xstate is the model
(`libs/xstate/AGENTS.md`, `libs/xstate/test/oracle/`).

## Steps
1. Pin the original at an exact release; record it in `meta/libraries.json` (`"port-of"`) and the
   library's `AGENTS.md`. Check its licence against chapter 2; keep its notice in
   `LICENSE-<ORIGIN>.txt`.
2. Make `libs/<name>` (skill `webcpp-library-conventions`).
3. Port the original's tests as data-driven cases; write the oracle in `test/oracle/` (the pinned
   original, its scripts, the Jamfile with `webcpp.original`, `webcpp.cases`, `webcpp.twins`,
   `webcpp.lane`); write expected results only with `b2 libs/<name>/test/oracle//update-expected`.
   See the cases fail.
4. Port the code header by header, with Doc Comments, until the cases pass natively, then on every
   declared target.
5. Write the page: the guide with each example's twin, the guarantees, the testing chapter, the
   reference and the appendix "Differences", each difference with `example/diff_<topic>.cpp` and
   its twin.
6. The definition of green from scratch (skill `webcpp-build-and-lanes`), oracle lane included:
   `b2 -a libs/<name>/test/oracle//oracle`.

## Never
- State by hand what the original does; edit an expected result; leave a difference unrecorded.
