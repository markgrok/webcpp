---
name: webcpp-library-conventions
description: "Create, review or specify a webcpp library: its names, layout, configuration header, errors and exceptions, and the checklist of a new library."
---

# A webcpp library's conventions

The rules are in `AGENTS.md`: chapter 2 ("The checklist of a new library", "Third-party code"),
chapter 3 (Names), chapter 6 (C++ rules, C libraries, exceptions and RTTI, what the lint
enforces), chapter 7 (Doc Comments). A library's own `AGENTS.md` adds only what is specific to it.

## New library
1. Choose the kind: own, port (skill `webcpp-port-methodology`) or wrapper.
2. Until the owner makes `webcpporg/<name>`, work in a local `git init` at `libs/<name>`.
3. Write the checklist files of chapter 2: `meta/libraries.json`, `build.jam` (target
   `/webcpp/<name>//<name>`), README, `AGENTS.md`, licence files, `doc/changelog.adoc`, CI calling
   the superproject's `library.yml`.
4. `<webcpp/<name>/config.hpp>` includes `<webcpp/config.hpp>` first and defines
   `WEBCPP_<NAME>_NO_EXCEPTIONS`; every public header includes it first.
5. See `b2 libs/<name>/test` build the headers-alone tests of an empty convenience header.

## Reviewing code
- Names against the table of chapter 3: namespace `webcpp::<name>`, `detail`, macros
  `WEBCPP_<NAME>_*`, include guards, error category `webcpp.<name>`, snake_case.
- Errors as values; headers that must compile without exceptions do; allocation as specified.
- What a target lacks is declared, not skipped (chapter 9, "Tests").
- Every public symbol documented (skill `webcpp-docs-site-release`).
- The lint: `tools/lint/lint.sh` (chapter 6) prints `lint: clean`.
