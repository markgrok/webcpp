// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// Rewrites a converted page: Asciidoctor.js loads it with `-r`.
//
// MrDocs writes its reference with an HTML character reference in place of
// each character AsciiDoc could read as markup, `&lowbar;` for `_`, which
// Asciidoctor passes to the page. Two of them stand for another character in
// HTML than the one MrDocs read: `&hyphen;` is U+2010 and `&circ;` U+02C6. So
// each is written back as the ASCII character MrDocs read, which a reader
// copies and a search finds, and so is a U+2010 itself.
//
// Each word of a span of inline code that holds a space becomes an element of
// its own, so the page's style can break a line between the words of
// `get(a, b)` and never inside one, at the hyphen of `--recursive` or the dot
// of `xstate.done.state.<id>`: CSS alone breaks text wherever Unicode allows
// it.

import { Extensions, Postprocessor } from '@asciidoctor/core';

// The table of MrDocs's AsciiDoc generator: each character it escapes, by the
// name of its reference.
const MRDOCS = new Map([
  ['circ', '^'], ['lowbar', '_'], ['ast', '*'], ['grave', '`'], ['num', '#'],
  ['lsqb', '['], ['rsqb', ']'], ['lcub', '{'], ['rcub', '}'], ['lt', '<'],
  ['gt', '>'], ['bsol', '\\'], ['verbar', '|'], ['hyphen', '-'], ['equals', '='],
  ['amp', '&'], ['semi', ';'], ['plus', '+'], ['colon', ':'], ['period', '.'],
  ['quot', '"'], ['apos', "'"], ['sol', '/']
]);

// The characters a page keeps as references: those HTML needs, in text and in
// an attribute, and the two whose literal form in a page's text is the mark
// of a fault to doc-check.py --rendered, the ++ of a passthrough and the
// backtick of an unclosed span, as Asciidoctor itself writes {cpp}
// C&#43;&#43;.
const KEPT = new Map([
  ['<', '&lt;'], ['>', '&gt;'], ['&', '&amp;'], ['"', '&quot;'], ['+', '&#43;'], ['`', '&#96;']
]);

const REFERENCE = /&([A-Za-z]+);|&#([0-9]+);|&#[xX]([0-9A-Fa-f]+);/g;

// The text with each of MrDocs's references, and each numeric reference to a
// printable ASCII character, written as the character it stands for, and each
// U+2010 as `-`. A character a page keeps as a reference stays one, unless
// `markup` asks for the text the HTML shows, every reference read.
export function decodeEntities(text, { markup = false } = {}) {
  return text
    .replace(REFERENCE, (reference, name, decimal, hex) => {
      let character;
      if (name !== undefined) {
        character = MRDOCS.get(name);
      } else {
        const code = decimal !== undefined ? Number.parseInt(decimal, 10) : Number.parseInt(hex, 16);
        character = code >= 0x20 && code <= 0x7e ? String.fromCharCode(code) : undefined;
      }
      if (character === undefined) {
        return reference;
      }
      return !markup && KEPT.has(character) ? KEPT.get(character) : character;
    })
    .replace(/\u2010/g, '-');
}

// Inline code is the one `<code>` Asciidoctor writes with no attribute, a
// block's having its language; that of a page holds no markup.
const SPACED_CODE = /<code>([^<]*\s[^<]*)<\/code>/g;

function wordsOfCode(html) {
  return html.replace(SPACED_CODE, (_code, text) => {
    const words = text.replace(/\S+/g, (word) => `<span>${word}</span>`);
    return `<code class="words">${words}</code>`;
  });
}

class Page extends Postprocessor {
  process(_document, output) {
    return wordsOfCode(decodeEntities(output));
  }
}

Extensions.register(function () {
  this.postprocessor(Page);
});
