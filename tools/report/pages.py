# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""The pages of the test report, written from its lanes (lanes.py) into a directory:

  index.html          the libraries by lanes;
  <library>.html      a library's tests and examples by lanes;
  output/<lane>/...   what b2 captured of each failure, which the failure's cell links to.

Each page stands alone: its style is inline, with no script, font or image, so the directory can
be published as it is. The directory is served as the site's report/, beside the index page and
the libraries' pages (tools/ci/assemble.py): the brand links the site's index, `../` from the
directory, and a library's page links its documentation, `../libs/<library>/`. The footer links
github.com/webcpporg, the only site outside it a page links to. Below 600 pixels
wide, each row of a matrix becomes a card: its name, then a chip per lane, so that a phone shows
every verdict without scrolling sideways.
"""

from __future__ import annotations

import html
import posixpath
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import quote

from lanes import EMPTY, KINDS, PASS, UNBUILT, Action, Lane, Row, problems, step, worst

OWN_SITE = 'https://github.com/webcpporg/'

NOT_BUILT = "Not built in this lane, as when it does not declare the lane's target."

OUTSIDE = 'outside failure'

STYLE = """
:root {
  --bg: #ffffff; --fg: #1f2328; --muted: #59636e; --line: #d1d9e0; --raised: #f6f8fa;
  --link: #0969da; --pass-bg: #d3f3dc; --pass-fg: #0f5a26; --fail-bg: #cf222e;
  --fail-fg: #ffffff; --na-bg: #eceff2; --na-fg: #6e7781;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117; --fg: #e6edf3; --muted: #9198a1; --line: #30363d; --raised: #151b23;
    --link: #4493f8; --pass-bg: #163d24; --pass-fg: #7ee2a0; --fail-bg: #c4272a;
    --fail-fg: #ffffff; --na-bg: #21262d; --na-fg: #8b949e;
  }
}
*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial,
    sans-serif;
}
/* Only the sides: main and footer set their own top and bottom. */
.wrap { max-width: 1120px; margin: 0 auto; padding-left: 16px; padding-right: 16px; }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
code, pre { font-family: var(--mono); font-size: 13px; }
code { overflow-wrap: anywhere; }
.bar { background: var(--raised); border-bottom: 1px solid var(--line); }
.bar nav {
  display: flex; flex-wrap: wrap; gap: 4px 8px; padding-top: 10px; padding-bottom: 10px;
  font-size: 14px;
}
.bar nav span { color: var(--muted); }
.bar nav .brand { color: var(--fg); font-weight: 700; }
main { padding-top: 28px; padding-bottom: 40px; }
h1 { font-size: 26px; line-height: 1.25; margin: 0 0 14px; overflow-wrap: anywhere; }
h1 code { font-size: 0.85em; }
h2 { font-size: 18px; line-height: 1.3; margin: 32px 0 10px; overflow-wrap: anywhere; }
h3 { font-size: 13px; margin: 16px 0 6px; color: var(--muted); }
p { margin: 0 0 12px; }
.verdict {
  margin: 0 0 24px; padding: 10px 14px; border-radius: 6px; border-left: 4px solid var(--na-fg);
  background: var(--raised);
}
.verdict.passing { border-left-color: var(--pass-fg); background: var(--pass-bg); }
.verdict.failing { border-left-color: var(--fail-bg); }
.problems ul { margin: 0 0 24px; padding-left: 20px; }
.problems li { margin: 4px 0; overflow-wrap: anywhere; }
/* The table scrolls inside its frame when it is wider than the page. */
.scroll {
  width: fit-content; max-width: 100%; overflow-x: auto; margin: 0 0 8px;
  border: 1px solid var(--line); border-radius: 6px;
}
.matrix { border-collapse: separate; border-spacing: 0; }
.matrix th, .matrix td {
  padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap;
}
.matrix tbody tr:last-child > * { border-bottom: 0; }
.matrix thead th {
  background: var(--raised); color: var(--muted); font-size: 12px; font-weight: 600;
  vertical-align: bottom;
}
.matrix .name {
  position: sticky; left: 0; z-index: 1; background: var(--bg);
  border-right: 1px solid var(--line);
}
.matrix thead .name { background: var(--raised); z-index: 2; }
.matrix tbody .name { font-family: var(--mono); font-size: 13px; font-weight: 500; }
/* A long name wraps, so that the column stuck at the left leaves room for the lanes: a cell
   ignores max-width, what it holds does not. */
.matrix tbody .name > * {
  display: block; width: max-content; max-width: 40vw; white-space: normal;
  overflow-wrap: anywhere;
}
.matrix .type { color: var(--muted); font-size: 13px; }
/* A lane's header wraps at a hyphen when its column is narrower than its name or toolset, so
   that 9 lanes fit at desktop width without the table scrolling sideways: nowrap, the rule
   above, would hold every header to its widest line's full width instead. */
.matrix .lane {
  text-align: center; font-family: var(--mono); color: var(--fg); white-space: normal;
}
.matrix .lane .toolset {
  display: block; font: 400 11px/1.4 var(--mono); color: var(--muted);
}
.matrix .lane.empty, .matrix .lane.outside { color: var(--fail-bg); }
.matrix .lane.empty::after, .matrix .lane.outside::after {
  display: block; font: 700 10px/1.4 system-ui, sans-serif; letter-spacing: 0.04em;
  text-transform: uppercase;
}
.matrix .lane.empty::after { content: "empty"; }
.matrix .lane.outside::after { content: "outside failure"; }
.matrix td.cell {
  padding: 0; min-width: 60px; text-align: center; font-size: 13px; font-weight: 600;
  border-left: 1px solid var(--bg);
}
.matrix td.cell > * { display: block; padding: 6px 8px; }
.matrix td.cell a { color: inherit; }
.pass { background: var(--pass-bg); color: var(--pass-fg); }
.fail { background: var(--fail-bg); color: var(--fail-fg); }
.na { background: var(--na-bg); color: var(--na-fg); font-weight: 400; }
/* On a phone, each row is a card: its name, its type, and a chip per lane that names the lane
   (and its mark, when it built nothing or failed outside its tests). The header row is still
   there for a screen reader, which the explicit roles keep reading as a table. */
@media (max-width: 600px) {
  .scroll { width: auto; overflow: visible; }
  .matrix, .matrix tbody { display: block; }
  .matrix thead {
    position: absolute; width: 1px; height: 1px; margin: -1px; overflow: hidden;
    clip-path: inset(50%); white-space: nowrap;
  }
  .matrix tbody tr {
    display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 12px;
    border-bottom: 1px solid var(--line);
  }
  .matrix tbody tr:last-child { border-bottom: 0; }
  .matrix tbody th, .matrix tbody td { display: block; padding: 0; border: 0; }
  .matrix tbody .name {
    position: static; flex: 0 0 100%; background: none; white-space: normal; border: 0;
  }
  .matrix tbody .name > * { width: auto; max-width: none; }
  .matrix .type { flex: 0 0 100%; margin-top: -6px; font-size: 12px; }
  .matrix td.cell {
    display: inline-flex; min-width: 0; border-radius: 4px; font-size: 12px;
    text-align: left; white-space: nowrap;
  }
  .matrix td.cell::before {
    content: attr(data-lane) ":"; padding: 2px 0 2px 8px; font-weight: 400;
  }
  .matrix td.cell[data-note]::before {
    content: attr(data-lane) " (" attr(data-note) "):";
  }
  .matrix td.cell > * { padding: 2px 8px 2px 5px; }
}
.tag {
  display: inline-block; min-width: 72px; padding: 1px 8px; border-radius: 4px;
  text-align: center; font-size: 12px; font-weight: 600; line-height: 1.6;
  vertical-align: 0.1em;
}
.legend dl { display: grid; grid-template-columns: max-content 1fr; gap: 8px 14px; margin: 0; }
.legend dl div { display: contents; }
.legend dd { margin: 0; color: var(--muted); font-size: 14px; }
.build { margin-top: 28px; border-top: 1px solid var(--line); }
.build h2 { margin-top: 20px; font-size: 15px; font-weight: 600; }
.build h2 code { font-size: 13px; }
.facts {
  display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 4px 14px;
  margin: 0 0 4px; font-size: 14px;
}
.facts dt { color: var(--muted); }
.facts dd { margin: 0; }
/* Output keeps its lines, so that a compiler's caret stays under what it points at: a long line
   scrolls inside its box. */
pre {
  margin: 0; padding: 12px 14px; background: var(--raised); border: 1px solid var(--line);
  border-radius: 6px; white-space: pre; overflow-x: auto; line-height: 1.45;
}
details { margin-top: 12px; }
summary { cursor: pointer; color: var(--muted); font-size: 13px; }
summary + pre { margin-top: 6px; }
footer {
  border-top: 1px solid var(--line); padding: 16px 0 28px; color: var(--muted);
  font-size: 13px;
}
"""


def e(text: str) -> str:
    return html.escape(text, quote=True)


def plural(count: int, word: str) -> str:
    return f'{count} {word}' if count == 1 else f'{count} {word}s'


def page_of(library: str) -> str:
    return f'{quote(library, safe="")}.html'


def output_of(lane: Lane, row: Row) -> str:
    """The page of row's failure in lane, relative to the directory."""
    category = 'example' if row.example else 'test'
    return (f'output/{lane.name}/{quote(row.library, safe="")}/'
            f'{category}-{quote(row.name, safe="")}.html')


def outside_of(lane: Lane) -> str:
    """The page of lane's failures outside every test and example, relative to the directory."""
    return f'output/{lane.name}/outside.html'


def href(path: str, up: str = '') -> str:
    return e(up + quote(path, safe='/#'))


def note_of(lane: Lane) -> str | None:
    """What marks a lane in a matrix: empty when it built nothing, or its failures outside every
    test and example."""
    if not lane.built():
        return 'empty'
    return OUTSIDE if lane.outside else None


def page(title: str, crumbs: Sequence[tuple[str, str | None]], up: str,
         body: list[str]) -> str:
    """A whole page: crumbs are the trail at its top, each a label and its link (None for the
    page itself), and up leads from it to the directory."""
    trail = [f'<a class="brand" href="{href("../", up)}">webcpp</a>']
    for label, link in [('test matrix', 'index.html'), *crumbs]:
        trail.append('<span>/</span>')
        trail.append(f'<a href="{href(link, up)}">{e(label)}</a>' if link else e(label))
    return '\n'.join([
        '<!doctype html>',
        '<html lang="en">',
        '<head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="color-scheme" content="light dark">',
        f'<title>{e(title)}</title>',
        f'<style>{STYLE}</style>',
        '</head>',
        '<body>',
        f'<header class="bar"><nav class="wrap">{"".join(trail)}</nav></header>',
        '<main class="wrap">',
        *body,
        '</main>',
        '<footer><div class="wrap">Copyright (c) 2026 WebCpp.org &middot; '
        f'<a href="{OWN_SITE}">github.com/webcpporg</a></div></footer>',
        '</body>',
        '</html>',
        '',
    ])


def verdict_paragraph(failures: int, failing_lanes: int, lanes: int, built: bool) -> str:
    if failures:
        return (f'<p class="verdict failing"><strong>Failing.</strong> '
                f'{plural(failures, "failure")} in {failing_lanes} of {plural(lanes, "lane")}.</p>')
    if not built:
        return '<p class="verdict"><strong>Not built.</strong> No lane built any of it.</p>'
    return (f'<p class="verdict passing"><strong>Passing.</strong> Every test and example '
            f'built in {plural(lanes, "lane")} passed.</p>')


def cell(lane: Lane, verdict: str | None, link: str | None) -> str:
    """The cell of a lane in a matrix row: data-lane names the lane, data-note its mark, for the
    chip a phone shows."""
    note = note_of(lane)
    data = f' data-lane="{e(lane.name)}"' + (f' data-note="{e(note)}"' if note else '')
    if verdict is None:
        return (f'<td role="cell" class="cell na"{data} title="{e(NOT_BUILT)}">'
                '<span>n/a</span></td>')
    style = 'pass' if verdict == PASS else 'fail'
    text = f'<a href="{href(link)}">{e(verdict)}</a>' if link else f'<span>{e(verdict)}</span>'
    return f'<td role="cell" class="cell {style}"{data}>{text}</td>'


def lane_header(lane: Lane) -> str:
    """A lane's column header: its name, the toolset it was built with when that differs from the
    name (case-insensitively; a native lane is named after its toolset and would otherwise repeat
    it), and its mark."""
    note = note_of(lane)
    classes, title = 'lane', ''
    if note == 'empty':
        classes, title = 'lane empty', EMPTY
    elif note == OUTSIDE:
        classes, title = 'lane outside', 'an action outside every test and example failed'
    titled = f' title="{e(title)}"' if title else ''
    toolset = ''
    if lane.toolset is not None and lane.toolset.lower() != lane.name.lower():
        toolset = f'<span class="toolset">{e(lane.toolset)}</span>'
    return (f'<th scope="col" role="columnheader" class="{classes}"{titled} '
            f'data-lane="{e(lane.name)}">{e(lane.name)}{toolset}</th>')


def legend() -> list[str]:
    entries = [('pass', PASS, 'Every build of it in the lane passed.')]
    entries += [('fail', kind, meaning) for kind, meaning in KINDS.items()]
    entries.append(('na', 'n/a', NOT_BUILT))
    lines = ['<section class="legend">', '<h2>Legend</h2>', '<dl>']
    for style, label, meaning in entries:
        lines.append(f'<div><dt><span class="tag {style}">{e(label)}</span></dt>'
                     f'<dd>{e(meaning)}</dd></div>')
    lines += ['</dl>', '</section>']
    return lines


def table(heads: list[str], lanes: list[Lane],
          rows: list[tuple[list[str], list[str]]]) -> list[str]:
    """A matrix: heads name the columns before the lanes, and each row is the cells before the
    lanes, the first its name, and one cell per lane. The roles are explicit, so that the table
    stays one for a screen reader when a phone lays its rows out as cards."""
    first, *others = heads
    head = (f'<th scope="col" role="columnheader" class="name">{e(first)}</th>'
            + ''.join(f'<th scope="col" role="columnheader">{e(text)}</th>' for text in others)
            + ''.join(lane_header(lane) for lane in lanes))
    lines = ['<div class="scroll">', '<table class="matrix" role="table">',
             f'<thead role="rowgroup"><tr role="row">{head}</tr></thead>',
             '<tbody role="rowgroup">']
    for before, cells in rows:
        lines.append(f'<tr role="row">{"".join(before)}{"".join(cells)}</tr>')
    lines += ['</tbody>', '</table>', '</div>']
    return lines


def lane_problems(lanes: list[Lane]) -> list[str]:
    """The section that names each lane that built nothing, each library a lane built nothing
    of, and each failure outside every test and example, by its file; empty when there is
    none."""
    items = []
    for lane in lanes:
        if not lane.built():
            items.append(f'<li><strong>{e(lane.name)}</strong>: {e(EMPTY)}.</li>')
        for library in lane.unbuilt():
            items.append(f'<li><strong>{e(lane.name)}</strong>: {e(library)}: {e(UNBUILT)}.'
                         '</li>')
        for number, action in enumerate(lane.outside, 1):
            link = href(f'{outside_of(lane)}#failure-{number}')
            items.append(
                f'<li><strong>{e(lane.name)}</strong>: <a href="{link}"><code>'
                f'{e(posixpath.basename(action.path))}</code>: {e(step(action.name))}</a>, '
                'outside every test and example.</li>')
    if not items:
        return []
    return ['<section class="problems">', '<h2>Lanes</h2>', '<ul>', *items, '</ul>',
            '</section>']


def name_cell(text: str, link: str | None = None) -> str:
    # A long name breaks after an underscore first, as it does after a dash.
    name = e(text).replace('_', '_<wbr>')
    inner = f'<a href="{href(link)}">{name}</a>' if link else f'<span>{name}</span>'
    return f'<th scope="row" role="rowheader" class="name">{inner}</th>'


def index_page(lanes: list[Lane], libraries: dict[str, list[Row]]) -> str:
    rows = []
    for library, library_rows in libraries.items():
        cells = []
        for lane in lanes:
            verdict = worst(lane.rows[row.id].verdict() for row in library_rows
                            if row.id in lane.rows)
            cells.append(cell(lane, verdict, page_of(library) if verdict else None))
        rows.append(([name_cell(library, page_of(library))], cells))
    failures = [len(problems(lane)) for lane in lanes]
    body = ['<h1>Test matrix</h1>',
            verdict_paragraph(sum(failures), sum(1 for count in failures if count), len(lanes),
                              any(lane.built() for lane in lanes))]
    body += lane_problems(lanes)
    body += table(['Library'], lanes, rows)
    body += legend()
    return page('Test matrix - webcpp', [], '', body)


def library_page(library: str, lanes: list[Lane], library_rows: list[Row]) -> str:
    rows = []
    failures = 0
    failing_lanes = set()
    for row in library_rows:
        cells = []
        for lane in lanes:
            found = lane.rows.get(row.id)
            verdict = found.verdict() if found else None
            failed = verdict not in (None, PASS)
            if failed:
                failures += 1
                failing_lanes.add(lane.name)
            cells.append(cell(lane, verdict, output_of(lane, row) if failed else None))
        rows.append(([name_cell(row.name), f'<td role="cell" class="type">{e(row.type)}</td>'],
                     cells))
    built = any(lane.rows[row.id].builds for lane in lanes for row in library_rows
                if row.id in lane.rows)
    documentation = href(f'../libs/{library}/')
    body = [f'<h1>{e(library)}</h1>',
            f'<p><a href="{documentation}">The documentation of {e(library)}</a></p>',
            verdict_paragraph(failures, len(failing_lanes), len(lanes), built)]
    body += lane_problems(lanes)
    body += table(['Test', 'Type'], lanes, rows)
    body += legend()
    return page(f'{library} - webcpp test matrix', [(library, None)], '', body)


def action_lines(action: Action, file: str) -> list[str]:
    """What b2 recorded of an action that built file: its rule and exit status, its output, and
    its command."""
    output = action.output.strip('\n') or '(no output)'
    rule = action.name or "one of b2's own"
    return ['<dl class="facts">',
            f'<dt>Action</dt><dd><code>{e(rule)}</code></dd>',
            f'<dt>Exit status</dt><dd>{action.status}</dd>',
            f'<dt>File</dt><dd><code>{e(file)}</code></dd>',
            '</dl>',
            '<h3>Output</h3>',
            f'<pre>{e(output)}</pre>',
            f'<details><summary>Command</summary><pre>{e(action.command or "(none)")}</pre>'
            '</details>']


def output_page(lane: Lane, row: Row) -> str:
    verdict = row.verdict() or ''
    body = [f'<h1><code>{e(row.id)}</code> on {e(lane.name)}</h1>',
            f'<p class="verdict failing"><span class="tag fail">{e(verdict)}</span> '
            f'{e(KINDS.get(verdict, ""))}</p>']
    for build in row.builds:
        if build.kind == PASS:
            continue
        body += ['<section class="build">',
                 f'<h2>Built in <code>{e(build.directory)}</code></h2>']
        # Builds that fail otherwise than the page's verdict says, which is the most significant.
        if build.kind != verdict:
            body.append(f'<p><span class="tag fail">{e(build.kind)}</span> '
                        f'{e(KINDS[build.kind])}</p>')
        if build.culprit is not None:
            body += action_lines(build.culprit, posixpath.basename(build.culprit.path))
        elif lane.outside:
            body.append('<p>The failures of the lane outside every test and example:</p><ul>')
            for number, action in enumerate(lane.outside, 1):
                link = href(f'outside.html#failure-{number}', '../')
                body.append(f'<li><a href="{link}"><code>{e(posixpath.basename(action.path))}'
                            f'</code>: {e(step(action.name))}</a></li>')
            body.append('</ul>')
        else:
            body.append('<p>No action of the lane outside every test and example failed: the '
                        'lane was likely not built from scratch.</p>')
        body.append('</section>')
    crumbs = [(row.library, page_of(row.library)), (f'{row.name} on {lane.name}', None)]
    return page(f'{row.id} on {lane.name} - webcpp test matrix', crumbs, '../../../', body)


def outside_page(lane: Lane) -> str:
    body = [f'<h1>{e(lane.name)}: failures outside every test and example</h1>',
            '<p>b2 skips what needs a target that failed: the tests and examples that need these '
            'are not run.</p>']
    for number, action in enumerate(lane.outside, 1):
        body += [f'<section class="build" id="failure-{number}">',
                 f'<h2><span class="tag fail">{e(step(action.name))}</span> '
                 f'<code>{e(posixpath.basename(action.path))}</code></h2>',
                 *action_lines(action, action.path), '</section>']
    crumbs = [(f'{lane.name}: outside every test and example', None)]
    return page(f'{lane.name}: failures outside every test and example - webcpp test matrix',
                crumbs, '../../', body)


def write(lanes: list[Lane], out: Path) -> None:
    """Writes the pages of lanes into out, which it makes if need be."""
    libraries: dict[str, list[Row]] = {}
    for library in sorted({row.library for lane in lanes for row in lane.rows.values()}):
        by_id: dict[str, Row] = {}
        for lane in lanes:
            for row in lane.rows.values():
                if row.library == library:
                    by_id.setdefault(row.id, row)
        libraries[library] = sorted(by_id.values(), key=Row.order)
    pages = {'index.html': index_page(lanes, libraries)}
    for library, library_rows in libraries.items():
        pages[page_of(library)] = library_page(library, lanes, library_rows)
    for lane in lanes:
        for row in lane.rows.values():
            if row.verdict() not in (None, PASS):
                pages[output_of(lane, row)] = output_page(lane, row)
        if lane.outside:
            pages[outside_of(lane)] = outside_page(lane)
    for name, text in pages.items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
