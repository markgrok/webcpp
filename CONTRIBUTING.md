# Contributing to webcpp

webcpp welcomes libraries and changes from anyone, written by hand or with
the coding agents of your choice. This page is the way in: what webcpp asks
of a library, how to propose one, and how a change is made and accepted.
[AGENTS.md](AGENTS.md) is the rulebook it summarises, with every rule in
full; each library's own `libs/<name>/AGENTS.md` adds only what is specific
to it. When this page and AGENTS.md seem to differ, AGENTS.md rules.

## For coding agents

Give your agent this file and AGENTS.md before it starts. AGENTS.md is
written so that an agent with no other context can port a library by
following it: it names every file, command and check, and the evidence that
counts as done. Agent systems that read an `AGENTS.md` at the root of a
repository find it there already; for others, point them at it. Nothing in
webcpp depends on one agent system.

## What webcpp is

A collection of header-only C++20 libraries that bring to C++ the
libraries other languages use for the web. Each is either a port of a widely
used original at an exact version, proven against that original, or a
library of webcpp's own. webcpp follows Boost's model: this repository is
the superproject, each library has a repository of its own under
[webcpporg](https://github.com/webcpporg), checked out as a submodule under
`libs/<name>`, and everything is built, tested and documented with b2.

## The rules every library keeps

Each line is a rule of AGENTS.md, named by its chapter.

- **Header-only C++20, Boost and the standard library first.** Any other
  dependency needs the maintainer's decision (chapter 6).
- **A port follows an exact version of its original,** under a licence
  compatible with the Boost Software License (MIT, BSD, Apache-2.0; not
  GPL), and keeps the original's notice in `LICENSE-<ORIGIN>.txt`; webcpp's
  own files are BSL-1.0 only (chapter 2).
- **Fidelity and evidence.** A port behaves as its original does, and proves
  it: the original's tests become cases whose expected results the pinned
  original writes (its oracle), and every example of the page has a twin
  in the original's language that prints the same output (chapters 4, 5).
- **Errors as values.** An operation that can fail returns
  `boost::system::result<T>` with the library's own error category
  (chapter 6).
- **Exceptions are the user's choice.** Every library compiles and works
  both with and without exceptions, through its configuration
  (`WEBCPP_<NAME>_NO_EXCEPTIONS` in `<webcpp/<name>/config.hpp>`), and raises
  every exception through `boost::throw_exception`, never a bare `throw`
  (chapter 6).
- **Every variant is tested.** The lint and the CI test every variant a
  library supports: exceptions on and off, and the library's own
  configurations (chapter 9; the CI's levels are in chapter 13).
- **Allocators are the user's.** A data structure that makes sense to share
  takes an `Allocator` template parameter with fancy pointers, so that it
  can live in a Boost.Interprocess segment and be used by another process;
  everything else allocates through an allocator its user gives. A test that
  counts allocations proves it (chapter 6).
- **Asynchronous code runs on xactor,** webcpp's actor system, whose
  scheduler drives every library the same way (chapter 6).
- **No global or static mutable state, and determinism:** no clock, file,
  network, process, thread, environment or entropy unless that is the
  library's purpose, said on the line that reaches it (chapter 6).
- **The targets.** A library declares the targets it runs on (native,
  wasip2, wasip3, emscripten) and passes on every one it declares
  (chapter 9).
- **Documentation.** Every public symbol has a Doc Comment, every library a
  page built with Asciidoctor and an API reference built with MrDocs, every
  listing of the page included from a compiled example (chapters 7, 8).
- **The specification before the code, a failing test before the
  implementation,** and a defect reproduced the way a user meets it before
  it is fixed (chapter 10).
- **Text.** English in everything written to a file; no em dash (U+2014);
  the licence notice at the top of every source file (chapter 11).

## Bringing a library

1. **Propose it.** Open an issue on
   [webcpporg/webcpp](https://github.com/webcpporg/webcpp/issues) that names
   the library, the original and its exact version, its licence, the targets
   you mean to support, and its use on the web. The maintainer answers
   whether it fits and settles the name.
2. **Develop it inside a checkout of the superproject,** as `libs/<name>`, a
   git repository of your own (`git init` there): the build, the lint and
   the tests treat it as a library as soon as it has its files. Follow
   AGENTS.md chapter 2's checklist (`meta/libraries.json`, `build.jam`, the
   test, example and doc Jamfiles, `README.md`, `AGENTS.md`,
   `LICENSE_1_0.txt`, the CI workflow) and chapter 10's "Porting a library,
   step by step".
3. **Reach green, from scratch,** as AGENTS.md chapter 10 defines it: every
   declared lane with `b2 -a`, the library's own lanes, `b2 -a doc`, the
   lint ending in `lint: clean`, and the tests of the build when you changed
   it.
4. **Hand it over.** Publish your repository and tell the maintainer in the
   issue. The maintainer reviews it, creates `webcpporg/<name>` from one
   import commit of it (a webcpp repository starts from one import commit,
   AGENTS.md chapter 11), names you among its authors and maintainers in
   `meta/libraries.json`, and adds it as a submodule of the superproject;
   from then on its CI runs on every change, and you change it by pull
   requests as below.

## Changing a library or the superproject

- **Fork the repository** you change (the library's, or `webcpporg/webcpp`
  for the build, the tools and the documentation), and open a pull request.
  A change that spans a library and the superproject is two pull requests
  that name each other.
- **One change per pull request,** with its test: a behaviour is written
  down before it is built, a test is seen failing before the code that
  makes it pass, and a change of the build or of a tool comes with a test of
  `tools/` that fails without it (chapter 10).
- **Fix what you meet:** a lint finding, a failing test or a flaky one, even
  when it is not yours; say what you could not fix.
- **Generated files are never edited by hand:** each has the command that
  writes it (AGENTS.md names them).

## Commits

- Commit under your own name and address. Stage and commit explicit paths,
  never `git add -A`; in the superproject, never `git add libs`.
- A subject says what the change does, prefixed by the part it touches
  (`tools/doc: ...`, `xactor: ...`).
- **No trailer of any kind:** no `Co-authored-by`, no `Signed-off-by`, no
  agent name. git reads a last paragraph that starts with `word:` as a
  trailer (`std::` does), so start such a paragraph otherwise.
- English, no em dash, and none of the words the lint refuses (AGENTS.md
  chapter 11).

## How a contribution is reviewed

The maintainer, often with review agents, checks a pull request against
AGENTS.md: the rules above, the evidence (tests that failed before the
change, an oracle and twins for a port), the page, and the CI. Expect
questions about anything a test does not prove, and about inputs the tests
do not cover: hostile input, deep nesting, allocation failure, a build
without exceptions, every declared target.

## License

By contributing, you agree that your contribution is distributed under the
[Boost Software License, Version 1.0](LICENSE_1_0.txt), and, for the parts
of a port that derive from its original, also under the original's licence,
whose notice the library keeps.
