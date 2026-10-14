---
name: webcpp-docs-site-release
description: "Write a library's page and Doc Comments, build the site, or prepare a release of webcpp."
---

# Docs, site and releases

The rules are in `AGENTS.md`: chapter 7 (Doc Comments and the API reference), chapter 8
(Documentation), chapter 9 ("The site", "CI") and chapter 11 ("The changelog", "Releases"). The
site's own rules are `site/AGENTS.md`, and its specification is the organization's `site`
capability in webcpporg/proposals.

## A library's page
1. Doc Comments for every public symbol, with the commands chapter 7 allows.
2. The page's sections as chapter 8 lists them; C++ only by include of an example or a tagged region.
3. Counts by the build's attributes (`{n-tests}` ...), never typed.
4. `b2 -a libs/<name>/doc` passes doc-check and MrDocs strict.

## The site
`b2 site` (preview) or `b2 site -sWEBCPP_SITE=release -sWEBCPP_SITE_VERSION=<version>`, then
`b2 site-serve`. The superproject's CI builds and publishes the preview; nothing is published by hand.

## A release
Only when the owner asks, following chapter 11's numbered steps: `b2 check-release`,
`b2 whats-new` (the owner approves the highlights), `b2 -a dist`; the tag and the GitHub Release
are the owner's.
