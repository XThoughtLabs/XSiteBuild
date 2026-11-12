---
name: building-in-a-site-design-system
description: "Builds pages, dashboard panels, report pages and images in a given website's design system and checks them before hand-over: reads the site's DESIGN.md, policy and ready receipt, uses the site's token variables or bound values, makes static pages (page scripts are never run by the checks), runs check_css.py and check_page.py (contained browser, the site's identity rules, axe-core contrast and a small set of accessibility rules), and for a redesign proves the page's structure was preserved with a before/after snapshot. Use when an agent creates, changes or redesigns an HTML page, panel or image for a site that has a design folder. (рус.: сделать страницу в стиле сайта, дашборд, отчёт в фирменном стиле, переделать страницу, проверить страницу)"
---

# Building in a site design system

Status: plugin site-design-system 0.1.0, 2026-11-10 (changed after the outside audit, rounds 1 and 2, the same day); plan 0.4 sections B.7.4, B.8, B.5.3. Owner of pages, panels, images, redesigns and the hand-over. The site design folder (tokens, policy, waivers, receipt) is owned by `keeping-a-site-design-system`; a new site's start by `starting-a-site-design-system`.

## 1. The receipt first

1. Get the site design folder's path from the task or the owner (never guess).
2. Read `site.yaml`, `DESIGN.md`, `policy.yaml`, `waivers.yaml`.
3. The checkers verify `ready.json` before reading the bundle (`check_page.py` first checks its inputs, the vendored axe-core and Playwright). Missing, invalid, stale or not committed (INCOMPLETE `RCPT`): **stop and report**; never edit `ready.json` or a profile file to get past it, and never commit anything. A stale or uncommitted receipt is renewed only by `keeping-a-site-design-system` (`--verify`, the owner's commit, `--issue`, the owner's commit of `ready.json`).
4. A staged copy of the site design folder with no Git repository: approval counts only with `--receipt-sha256 <SHA-256 of the issued ready.json>`, which the task must give (taken where the repository is). Without it the checkers report INCOMPLETE; never compute it from the copy itself.

## 2. Building rules

- **Bundle:** one folder with the page and its public assets only (the site's stylesheets copied in, fonts, images). Never a file of the site design folder, under any name (a file with the same bytes as one of them is refused); never `.git`, `.env*`, `*.pem`, `*.key` anywhere in a path (a folder named `.env` too); no links, junctions or hard links. Both checkers read every bundle file through the same guard and refuse the bundle (ERROR) without quoting the refused file.
- **Colours:** in role-bearing properties (`color`, `background*`, `border*`, `outline*`, `box-shadow`, `fill`, `stroke`) use only the site's contract variables (`var(--name)` from `trace-map.yaml`) of tokens the policy allows for that role and scheme; a literal-bound token's exact value in its roles; an extra in its roles and alpha range; a derived variable in its roles; `currentColor`, `transparent` or a CSS-wide keyword. Never a raw value, a named colour, a `var()` with a hard-coded fallback, a reserved token, or a redefinition of a contract variable.
- **Fonts:** the approved faces only (`policy.fonts.faces`), served from the bundle (the file whose SHA-256 the policy names; any served file whose first bytes are a font's is checked, whatever its name), weights inside the approved range; a font-stack variable or a literal stack, both on one rule: an approved face first, then only approved faces, generic families and the policy's `fonts.fallback_families`. Every `@font-face` source is a bundle file: never `data:`, `blob:`, `local()` or a remote URL (A1 FAIL). Code (`code`, `pre`, `kbd`, `samp`) uses the system monospace stack when `code_roles` is `system-monospace`; monospace nowhere else.
- **Text:** no forbidden text colours; SVG text's `fill-opacity` is composed with its opacity (the composed colour must keep the contrast), and a paint server, `context-fill` or `context-stroke` as its fill or a visible stroke gives INCOMPLETE; headings in heading tokens (accent only within the allowance); reading text no wider than the measure (the layout width; a transform does not shrink it); capitals only in labels, in either scheme; contrast at least 4.5:1 (3:1 for large text) on every surface, including faded parents (`opacity`). The glyph paint is what counts: keep `-webkit-text-fill-color` unset or equal to `color`; SVG text is judged by its `fill`. Do not fade (opacity below 1) a box that paints its own background behind text: the contrast of such a group is not computed (INCOMPLETE).
- **Static:** no `<script>`, no inline `on*` handler, no `javascript:` URL: any of them gives INCOMPLETE (the owner's decision, 2026-11-10), since page scripts never run during checks (Content-Security-Policy `script-src 'none'`) and what they would render is not checked. Content made by scripts counts as absent; charts are inline SVG; no `@import`; no remote resources (fonts, images, styles, frames): the checks run without network.
- **Visible to the checker:** no shadow DOM (`<template shadowrootmode>` or custom elements), no `data:` frames, no CSS nesting, no `::first-line` or `::first-letter` colours, no text in `::before`/`::after` `content`, no meta refresh, no gradient interpolated in a space other than sRGB (`in oklab` and the like), no element that paints (a background, border, shadow or image) over text (an element with `pointer-events: none` included), no `box-shadow`, `outline` or `border-image` that reaches text (a blurred inset shadow on a text's element or its ancestors, a neighbour's outer shadow or outline; a card's own outer shadow is fine, with its reach (offset, spread and 1.5 × blur) kept off the text around the card; a solid inset band with no blur on a text's element or its ancestors, such as a link's shadow underline, is composed, so its colour must keep the text's contrast over it too, and it must not be animated), no `filter` or `backdrop-filter` on an element that holds text or on its ancestors, no `blur()` or `drop-shadow()` filter within its reach of text (3 × blur, or the drop shadow's offset and 1.5 × its blur, beyond the box), none on an element with children, text, a `::before`/`::after`, its own shadow, SVG or an image, none animated, and no `-webkit-box-reflect` anywhere on the page, no shadow, outline or border image on a `::before`/`::after` or on a transformed element, no `display: contents` on an element that holds text, no text block taller or wider than the viewport (1280×800 and 390×844: split long text into paragraphs), no transparent same-bundle frame over a painted area of the page (give the frame's own document an opaque background), no colour in a space other than sRGB (`color(display-p3 …)`, `lab()`, `oklch()`): the checker cannot verify them and reports INCOMPLETE. The checker never marks the page and never resizes the viewport: it scrolls, and compares every element's paint (colours, visibility, display, offsets, margins, transforms, `clip`, `zoom`, `content-visibility`, shadows, borders, outlines, background size and position, padding, sizes, border images, decorations) at each scroll position with the first read (so give lazily loaded images their `width` and `height`), so a scroll-driven animation or any style that changes with scrolling gives INCOMPLETE too: the paint must stay the same while it checks. **Reader preferences:** it also loads the page again in every combination of `prefers-reduced-motion`, `prefers-contrast` (`more`, `less`) and `prefers-reduced-transparency`, and a frame that paints differently in any of them (a layer drawn or hidden, a colour, shadow, border or outline changed, a box moved or resized, an animation still running once the page has loaded) gives its text INCOMPLETE: rules for these preferences may change `animation`, `transition` or `scroll-behavior`, never what is painted. Leave `accent-color`, `caret-color`, `column-rule-color`, `border-image`, `filter: drop-shadow()`, `::marker` and `text-emphasis-color` unset: no checker judges them.
- **Colours everywhere they are written:** gradient stops of any spelling (a named colour, `hsl()`, `oklch()` is a raw value), SVG `fill`, `stroke` and `stop-color` (attributes too: a gradient paint server's stops are judged), the family of a `font` shorthand (write it out, or as exactly one font-stack variable: any other `var()` in the shorthand is INCOMPLETE), every definition of a page variable (keep it to a few: more than 64 expanded for one declaration is INCOMPLETE) and every `var()` fallback. Same-bundle frame documents are checked like the page.
- **Schemes:** a `light-only` or `dark-only` site paints the same and shows the same elements in both colour schemes (no `prefers-color-scheme` rules: hiding or fading a section in one scheme fails A9 too); a `both` site paints from each scheme's set and changes the page background between them. Capitals (A8), primary buttons (A11, both desktop renders) and the accessibility rules (A12) are checked in both schemes.
- **Publication:** for a page meant for publication, follow any publication rules in the site's `DESIGN.md` or policy.

## 3. Commands

Plugin root: two folders above this skill's base directory (in Claude Code also `${CLAUDE_PLUGIN_ROOT}`). Windows: `py -3 -I` instead of `python3 -I`.

```
python3 -I "<plugin root>/scripts/check_css.py"  --site "<folder>" --bundle "<bundle>" --page index.html [--json css.json] [--receipt-sha256 HEX]
python3 -I "<plugin root>/scripts/check_page.py" "<bundle>" --page index.html --site "<folder>" --out "<shots dir>" [--json page.json] [--receipt-sha256 HEX]
```
Reports, snapshots and screenshots never go into the site design folder (ERROR 2); an output that cannot be written is ERROR 2.
- `check_css.py`: the static role check of the page's own CSS and of its same-bundle frame documents (linked sheets, `<style>`, `style=""`, SVG `fill`/`stroke`/`stop-color` attributes). The site's approved stylesheets (SHA-256 in the receipt) are listed, not re-checked.
- `check_page.py`: stages only the page's reference closure, serves it from 127.0.0.1, renders it four times (1280×800 and 390×844, light and dark), loads each render again in the 11 other combinations of reader preferences (reduced motion, contrast, reduced transparency), runs axe-core 4.14.0 (contrast per frame; the policy's accessibility tags) and assertions A1–A13. On Linux it runs in its own network namespace (`containment: os`); as root give `--run-as <unprivileged user>` (Chromium's sandbox refuses root); elsewhere `containment: browser`. Screenshots go to `--out` (dark ones kept only for dark findings).
- Dependencies: Python 3.10+, PyYAML; for `check_page.py` Playwright for Python and its Chromium. A missing one gives ERROR naming it: ask the owner; never install anything yourself.
- Outcomes: PASS 0, FAIL 1, ERROR 2, INCOMPLETE 3 (never a pass), INTERNAL 4.

## 4. Each outcome

- **FAIL:** fix the page and run both checks again (at most three check-and-fix loops in a bounded task; then report).
- **INCOMPLETE:** remove its cause (an image behind text, an overlay, a painted pseudo-element behind text, a script-made section, shadow DOM, a `data:` frame, a `::first-line` colour) or name it in the hand-over; never report INCOMPLETE as a pass.
- **WARN:** advisory; name it in the hand-over.
- **WAIVED:** only through a waiver the owner committed; never write one yourself.
- **ERROR:** an input or dependency is unusable; report it with the checker's words.

Hand-over: the bundle path, both outcomes with their counts, the containment level, every INCOMPLETE and WARN item, the screenshots.

## 5. Redesigns (structure kept)

1. Before changing a page: `check_page.py ... --snapshot before.json` on the old page.
2. After: `check_page.py ... --kept before.json --kept-sha256 <the SHA-256 the --snapshot run printed>` on the new page (without the digest, or with another, A13 is INCOMPLETE). Every link (resolved URL and text), form (action, method) and field it owns (name, type; each `input`, `button`, `select`, `textarea`, `output`, `fieldset` and `object` counts under its owner, the form its `form` attribute or its position names, `<input type="image">` included), native `button`, `summary`, `select`, `textarea`, `[role=button]`, inline `on*` attribute, heading (level and text) and landmark must still be present and visible. A removal passes only through a committed A13 waiver naming the entry. A13 compares the desktop light render (1280 px, light) only. Behaviour registered by scripts is not checked (NOT_CHECKED).
3. The snapshot records the old page's full SHA-256, its entries and its coverage; a snapshot with no entries, an old format or taken from a run that could not see the whole structure (a frame not checked, shadow DOM, a budget) cannot prove preservation: INCOMPLETE. Take it again from a complete run.

## 6. Images

Guidance only (no checker reads raster images in 0.1.0): use the palette's tokens and approved fonts in any image text; say in the hand-over that images were not checked.

## Traps

- A page linking a remote web font or stylesheet: A10 fails and the text falls back to a system font (A1 fails too).
- Text drawn by a fallback font because the font file was not copied into the bundle: A1 fails ("drawn by a non-approved font") and A10 names the missing file.
- Default browser colours (blue links, grey buttons, form controls): A2 fails until each is given a contract variable.
- A decorative overlay touching text: A6 reports INCOMPLETE even when axe passes (the contrast at that spot is unknown).
- In this build, structure entries first carried the checker's random loopback port, so every link and form looked removed (test failure, 2026-11-10): entries now use origin-relative URLs.
- In this build's smoke test, A7 measured a timeline list item that only laid out a date and a text block (1,120 px against 720 px), a false FAIL (2026-11-10): A7 now skips an element whose content is only block-level children, and still measures text wrapped in inline elements (`<p><a><strong>…`).
- The outside audit (2026-11-10) showed text drawn invisible by `-webkit-text-fill-color` or SVG `fill` passing on its `color`, a page CSS rule keyed to the checker's own marker switching to good colours during the check, and an approved font name loaded from an unapproved `data:` font: each is now a FAIL or INCOMPLETE.
- Round 2 of the outside audit (2026-11-10) showed a layer hidden by `scale: 0` under the checker's marker, SVG text at `fill-opacity: 0.01`, a gradient below 4.5:1 between its samples, a `url(#missing) <reserved colour>` fill and a `color(srgb …)` background all passing: the checker now adds no marker and never resizes the viewport, composes `fill-opacity`, proves a gradient's lowest contrast, and judges every paint (or reports it INCOMPLETE).

## Self-check scenarios

1. "Make a progress report page in our site's style" with a site design folder named. → This skill: receipt check, bundle, build with contract variables, `check_css.py`, `check_page.py`, fix, hand-over.
2. `check_page.py` prints `stale receipt: CSS ../site/x.css changed`. → Stop; report; the owner renews the receipt (`keeping-a-site-design-system`).
3. "Redesign the contact page; keep everything working." → `--snapshot` before (note the SHA-256 it prints), build, `--kept` with `--kept-sha256` after; any removal needs the owner's committed waiver.
