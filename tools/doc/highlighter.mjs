// Copyright (c) 2026 WebCpp.org
//
// Distributed under the Boost Software License, Version 1.0. (See
// accompanying file LICENSE_1_0.txt or copy at
// https://www.boost.org/LICENSE_1_0.txt)

// Highlights a page's source blocks when it is built, with highlight.js, so
// the page needs no script and no network: Asciidoctor.js loads it with `-r`,
// and webcpp.doc asks for it with `source-highlighter=hljs-static`.
//
// A block of plain code (the default substitutions) is highlighted as it is
// written. A block whose substitutions include macros is markup: MrDocs writes
// its synopses so, with a character reference in place of each character
// AsciiDoc could read, `&lt;` and `&lowbar;`, and `link:#anchor[text]` for
// each type the reference documents. Asciidoctor applies the block's other
// substitutions, replacements and macros, to what the highlighter returns, so
// such a block is highlighted as the C++ it stands for, each link kept out of
// highlight.js's way and put back for the macros substitution to make, and
// every other character Asciidoctor could still read (`->` an arrow, `...` an
// ellipsis) written as a character reference, which postprocess.mjs decodes.

import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

import { SyntaxHighlighter, SyntaxHighlighterBase } from '@asciidoctor/core';
import hljs from 'highlight.js/lib/core';
import bash from 'highlight.js/lib/languages/bash';
import cpp from 'highlight.js/lib/languages/cpp';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';

import { decodeEntities } from './postprocess.mjs';

hljs.registerLanguage('bash', bash);
hljs.registerLanguage('cpp', cpp);
hljs.registerLanguage('javascript', javascript);
hljs.registerLanguage('json', json);

const require = createRequire(import.meta.url);
const theme = readFileSync(require.resolve('highlight.js/styles/github.css'), 'utf8');

// A link macro of a synopsis, its text holding no `]`.
const LINK = /link:[^\s[\]]+\[[^\]]*\]/g;

// What stands for the n-th link while highlight.js reads the code: one word,
// which it neither splits nor escapes.
const placeholder = (index) => `webcppLink${index}x`;
const PLACEHOLDER = /webcppLink(\d+)x/g;

function escape(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function highlighted(source, lang) {
  if (!hljs.getLanguage(lang)) {
    return escape(source);
  }
  return hljs.highlight(source, { language: lang }).value;
}

// The highlighted HTML with each ASCII character of its text that is neither a
// letter, a digit, `_` nor a space written as a numeric character reference,
// which neither the replacements nor the macros substitution reads.
function inert(html) {
  return html.replace(/(<[^>]*>)|([^<]+)/g, (_match, tag, text) => {
    if (tag) {
      return tag;
    }
    return decodeEntities(text, { markup: true }).replace(
      /[!-/:-@[-^`{-~]/g,
      (character) => `&#${character.charCodeAt(0)};`
    );
  });
}

class StaticHighlighter extends SyntaxHighlighterBase {
  handlesHighlighting() {
    return true;
  }

  highlight(node, source, lang) {
    if (!node.hasSubstitution('macros')) {
      return highlighted(source, lang);
    }
    const links = [];
    const code = decodeEntities(
      source.replace(LINK, (link) => placeholder(links.push(link) - 1)),
      { markup: true }
    );
    return inert(highlighted(code, lang)).replace(PLACEHOLDER, (_match, index) => links[index]);
  }

  // The theme styles the code element by its hljs class.
  format(node, lang, opts) {
    return super.format(node, lang, {
      ...opts,
      transform: (_pre, code) => {
        code.class = [code.class, 'hljs'].filter(Boolean).join(' ');
      }
    });
  }

  hasDocinfo(location) {
    return location === 'head';
  }

  docinfo() {
    return `<style>\n${theme}</style>`;
  }
}

SyntaxHighlighter.register(StaticHighlighter, 'hljs-static');
