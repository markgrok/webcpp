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
// Each table of the guide and the reference is in a box of its own, which
// scrolls when a word of the table is too long for the page, as a block of
// code does: the page never gets wider than the screen, and a table that fits
// is laid out as it was.
//
// A table of three columns or more gives each cell the text of its column's
// header, `data-label`, which a phone's style shows above the cell once it
// stacks the table's rows; a table of two columns, a name and what it is,
// reads stacked without them.
//
// A name too long for a phone's line, in inline code, in a heading of the
// reference, `webcpp::xactor::scheduler::run_one`, or in a bare URL, may break
// between its parts, which a `<wbr>` marks: after a `::`, a `_`, a `/`, or a
// `.` between letters, before the `(` or the `<` that ends a name, and in code
// between the words of a name in camel case. So a phone breaks it there and
// never between two letters of a word, which the style allows only to a part
// still wider than the line. From 600px, where such a name has room, only the
// break after a `::` of a heading stays, as the reference's headings always
// had it: the others are `<wbr class="part">`, which the style hides there.

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
// block's having its language; it holds text, and the link MrDocs gives the
// name of a header, `<webcpp/xactor/scheduler.hpp>`.
const INLINE_CODE = /<code>((?:[^<]|<a\b[^>]*>|<\/a>)*)<\/code>/g;

// The longest word of inline code that a phone's line holds whole: at 320px,
// 24 characters of the code font take about 240px of a column of 290px, which
// a list item or a stacked table cell narrows to about 260px.
const WHOLE = 24;

// A break after a `::`, which a heading of the reference keeps at every width;
// and one between the other parts of a name, which the style keeps only on a
// phone: from 600px every such name has room on a line.
const SCOPE = '<wbr>';
const PART = '<wbr class="part">';

// The points a name breaks at, in text that holds no markup and its
// references, each with what it becomes: after each `::`; after a run of `_`
// and after a `/` or a run of them, each inside a name; after a `.` between
// letters, not that of `3.5`; and before a `(` or a `<` that follows a name,
// not the second `<` of `<<`.
const BREAKS = [
  [/::/g, (scope) => scope + SCOPE],
  [/(?<=[A-Za-z0-9])_+(?=[A-Za-z0-9])/g, (run) => run + PART],
  [/(?<=[^\s/])\/+(?=[^\s/])/g, (run) => run + PART],
  [/(?<=[A-Za-z])\.(?=[A-Za-z])/g, (dot) => dot + PART],
  [/(?<=\w)(?=\(|&lt;)/g, () => PART]
];

// Code breaks at these too, and between the words of a name written in camel
// case, `resolveHistory` and `DefaultTransition`: never prose, whose JavaScript
// is one word. And the hyphens that open a flag, `-mexec-model=reactor` or
// `--target`, at the start of a word or after a space, a `=`, a `(`, a `,` or
// the `;` of a reference such as `&gt;`, stay with the flag's first character
// in a span the style keeps on one line: a break right after them would end a
// line with a hyphen alone, which reads as a dash.
const CODE_BREAKS = [
  ...BREAKS,
  [/(?<=[a-z])(?=[A-Z])/g, () => PART],
  [/(?<=^|[\s=(,;])-+[A-Za-z0-9]/g, (flag) => `<span class="lead">${flag}</span>`]
];

// A character reference, which no break goes inside: `&#xAB;` and `&rArr;`
// hold a lower case letter before an upper case one.
const ANY_REFERENCE = /&(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#[xX][0-9A-Fa-f]+);/g;

function breakable(text, points = BREAKS) {
  return points.reduce((broken, [point, mark]) => {
    const references = [...broken.matchAll(ANY_REFERENCE)].map((reference) => [
      reference.index,
      reference.index + reference[0].length
    ]);
    return broken.replace(point, (match, ...rest) => {
      const offset = rest[rest.length - 2];
      const inside = references.some(([start, end]) => offset > start && offset < end);
      return inside ? match : mark(match);
    });
  }, text);
}

// The html of inline code with each run of its text between two tags made
// breakable: never an attribute.
function breakableCode(html) {
  return html.replace(/(^|>)([^<]+)/g, (_text, end, text) => end + breakable(text, CODE_BREAKS));
}

// The text of html, its markup removed.
function textOf(html) {
  return html.replace(/<[^>]+>/g, '');
}

// Whether a word of inline code, its markup aside, is short enough to stay on
// one line, as a reader reads it.
function isWhole(word) {
  return decodeEntities(textOf(word), { markup: true }).length <= WHOLE;
}

// A word of inline code, as an element: `whole`, or breakable between its
// parts.
function wordOf(element, word) {
  return isWhole(word)
    ? `<${element} class="whole">${word}</${element}>`
    : `<${element}>${breakableCode(word)}</${element}>`;
}

function wordsOfCode(html) {
  return html.replace(INLINE_CODE, (_code, text) => {
    if (!/\s/.test(textOf(text))) {
      return wordOf('code', text);
    }
    if (text.includes('<')) {
      // Code that holds a link and a space, which MrDocs does not write, cannot be cut into
      // words without cutting the link: the code breaks between its parts.
      return `<code>${breakableCode(text)}</code>`;
    }
    const words = text.replace(/\S+/g, (word) => wordOf('span', word));
    return `<code class="words">${words}</code>`;
  });
}

// A bare URL, which Asciidoctor writes as the text of its link, and which holds
// no break yet: one in a heading has its breaks already.
const BARE_URL = /(<a href="[^"]*" class="bare">)([^<]*)(<\/a>)/g;

function partsOfURLs(html) {
  return html.replace(BARE_URL, (_link, open, text, close) => open + breakable(text) + close);
}

// The tag that opens a table of Asciidoctor's, `id` before `class` when it has
// one.
const TABLEBLOCK = /^<table\b[^>]*\sclass="tableblock\b/;

// A table of Asciidoctor's, which holds no other table.
const TABLE = /<table\b[^>]*\sclass="tableblock\b[^>]*>(?:(?!<table)[\s\S])*?<\/table>/g;
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

// The tag that opens or closes a table.
const TABLE_TAG = /<table\b[^>]*>|<\/table>/g;

function boxedTables(html) {
  // Whether each table open at this point is boxed: a note's, which Asciidoctor lays out as a
  // table too, is not.
  const open = [];
  return html.replace(TABLE_TAG, (tag) => {
    if (tag !== '</table>') {
      const boxed = TABLEBLOCK.test(tag);
      open.push(boxed);
      return boxed ? `<div class="table-scroll">\n${tag}` : tag;
    }
    return open.pop() ? `${tag}\n</div>` : tag;
  });
}

// A heading, with what it holds.
const HEADING = /(<h([1-6])\b[^>]*>)([\s\S]*?)(<\/h\2>)/g;

// The parts of a heading, its tags and the text between them.
const TAG = /(<[^>]+>)/;

function partsOfHeadings(html) {
  return html.replace(HEADING, (_heading, open, _level, inner, close) => {
    // Only the text between the heading's tags, and outside its inline code, whose breaks
    // wordsOfCode marked: never an attribute.
    let code = false;
    const broken = inner
      .split(TAG)
      .map((part, index) => {
        if (index % 2 === 1) {
          code = /^<code\b/.test(part) || (code && !/^<\/code>/.test(part));
          return part;
        }
        return code ? part : breakable(part);
      })
      .join('');
    return open + broken + close;
  });
}

// The elements whose text is code, or no text at all, where an apostrophe stays as written.
const VERBATIM = /^<(\/?)(pre|code|kbd|samp|script|style|textarea)\b/;
// A plural's apostrophe, `the operands' nodes`, after an s that ends a word; not the one that
// closes a word a straight quote opened, `the 'actors'`, which stays a quote.
const PLURAL = /(?<!'[\w-]*)(?<=[A-Za-z]s)'(?=[\s.,;:!?)\]]|$)/g;
// An apostrophe right after a name of code, or a link around one, `x`'s, before an s that ends
// the word, or before the end of the word itself.
const AFTER_CODE = /^'(?=s(?![A-Za-z])|[\s.,;:!?)\]]|$)/;

// Asciidoctor makes an apostrophe curly only between two letters, so the page's prose shows a
// straight one after the s of a plural and after a name of code, among curly ones, and so does
// MrDocs's reference. These become curly too, written as Asciidoctor writes its own, &#8217;,
// outside code, a listing, a script and a style; a quote, 'word', and a year, '90s, stay
// straight.
function curledApostrophes(html) {
  const parts = html.split(TAG);
  let verbatim = 0;
  let afterCode = false;
  return parts
    .map((part, index) => {
      if (index % 2 === 1) {
        const element = VERBATIM.exec(part);
        if (element && !part.endsWith('/>')) {
          verbatim += element[1] ? -1 : 1;
        }
        afterCode = verbatim === 0 && /^<\/(code|a)>$/.test(part) &&
          (afterCode || /^<\/code>$/.test(part));
        return part;
      }
      if (verbatim > 0) {
        return part;
      }
      let text = part.replace(PLURAL, '&#8217;');
      if (afterCode) {
        text = text.replace(AFTER_CODE, '&#8217;');
      }
      afterCode = afterCode && part === '';
      return text;
    })
    .join('');
}

class Page extends Postprocessor {
  process(_document, output) {
    const page = labelledTables(wordsOfCode(decodeEntities(output)));
    return curledApostrophes(boxedTables(partsOfURLs(partsOfHeadings(page))));
  }
}

Extensions.register(function () {
  this.postprocessor(Page);
});
