# browser_demo

A library that declares native and emscripten, which the tests of the build
place in `libs/browser_demo` of a scratch superproject: its tests run under
node on emscripten, `page` is linked for a browser and never run, and
`driven` is run by a script of node's in the own lane `driver`. Its page,
`doc/html/index.html`, is built with `b2 libs/browser_demo/doc`.
