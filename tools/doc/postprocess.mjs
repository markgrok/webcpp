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
// it. A word short enough for a phone's line, a span of one word or a word of
// several, is marked `whole`, which the style keeps on one line at any width;
// a longer one breaks where it must.
//
// A table of three columns or more gives each cell the text of its column's
// header, `data-label`, which a phone's style shows above the cell once it
// stacks the table's rows; a table of two columns, a name and what it is,
// reads stacked without them.
//
// The heading of a name of the reference, `webcpp::xactor::scheduler::run_one`,
// may break after each `::`, so that a phone breaks it between scopes and not
// inside an identifier.

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
        const code =
          decimal !== undefined ? Number.parseInt(decimal, 10) : Number.parseInt(hex, 16);
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
const INLINE_CODE = /<code>([^<]*)<\/code>/g;

// The longest word of inline code that a phone's line holds whole: at 320px,
// 24 characters of the code font take about 240px of a column of 290px, which
// a list item or a stacked table cell narrows to about 260px.
const WHOLE = 24;

// The class of a word of inline code, as a reader reads it: `whole` when it is
// short enough to stay on one line.
function classOf(word) {
  return decodeEntities(word, { markup: true }).length <= WHOLE ? ' class="whole"' : '';
}

function wordsOfCode(html) {
  return html.replace(INLINE_CODE, (_code, text) => {
    if (!/\s/.test(text)) {
      return `<code${classOf(text)}>${text}</code>`;
    }
    const words = text.replace(/\S+/g, (word) => `<span${classOf(word)}>${word}</span>`);
    return `<code class="words">${words}</code>`;
  });
}

// A table of Asciidoctor's, which holds no other table.
const TABLE = /<table class="tableblock[^"]*">(?:(?!<table)[\s\S])*?<\/table>/g;
const HEADER_CELL = /<th\b[^>]*>([\s\S]*?)<\/th>/g;
const BODY = /<tbody>[\s\S]*?<\/tbody>/;
const ROW = /<tr>[\s\S]*?<\/tr>/g;
const CELL = /<(td|th)\b/g;

// The text of a header cell, as an attribute's value: its markup removed, and
// its references kept, a quote among them.
function labelOf(cell) {
  return cell.replace(/<[^>]+>/g, '').trim().replace(/"/g, '&quot;');
}

function labelledTables(html) {
  return html.replace(TABLE, (table) => {
    const head = table.match(/<thead>[\s\S]*?<\/thead>/);
    if (head === null || /\b(colspan|rowspan)=/.test(table)) {
      return table;
    }
    const labels = [...head[0].matchAll(HEADER_CELL)].map((cell) => labelOf(cell[1]));
    if (labels.length < 3) {
      return table;
    }
    return table.replace(BODY, (body) =>
      body.replace(ROW, (row) => {
        let column = 0;
        return row.replace(CELL, (cell) => {
          const label = labels[column++];
          return label === undefined ? cell : `${cell} data-label="${label}"`;
        });
      })
    );
  });
}

// A heading, with what it holds.
const HEADING = /(<h([1-6])\b[^>]*>)([\s\S]*?)(<\/h\2>)/g;

function scopesOfHeadings(html) {
  return html.replace(HEADING, (_heading, open, _level, inner, close) => {
    // Only the text between the heading's tags: never an attribute.
    const broken = inner.replace(/(^|>)([^<]*)/g, (_text, end, text) =>
      end + text.replace(/::/g, '::<wbr>')
    );
    return open + broken + close;
  });
}

class Page extends Postprocessor {
  process(_document, output) {
    return scopesOfHeadings(labelledTables(wordsOfCode(decodeEntities(output))));
  }
}

Extensions.register(function () {
  this.postprocessor(Page);
});
