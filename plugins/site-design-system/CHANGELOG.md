# Changelog

## Changed after HQ's check of CC-07 (0.1.0, not released; 2026-11-12)

HQ ran head CC-07 in the cloud (Linux, Chromium: 689 tests pass, 309 of 312 mutants killed, none of HQ's attacks on A6 a false PASS any more) and measured what the strict A6 rules cost on honest pages: one decorative blurred circle far from any text made all 28 runs of the page INCOMPLETE (U1); a link's own shadow underline made its text INCOMPLETE (U2); and two defence layers had no test that fails when one alone is removed (Y1). The CEO's words that govern these fixes (HQ session, 2026-11-12; question forms; times of the answers not read):

> «CC-08, потом конец (Recommended)»
>
> (translation) "CC-08, then the end." — what next with the audit: a blur counts only near itself, a link with a shadow underline passes, tests for the layers, the stacks; after HQ's check, the end of the audit and the package.

> «Везде первым одобренный (Recommended)»
>
> (translation) "The approved face first everywhere." — on Claude Code's Question 5 of CC-07: in a stack variable and in a literal stack alike, the first family is an approved face, then the fallbacks.

And in Claude Code's session, on its plan for TASK-CC-08 (2026-11-12; the clock read 02:02:02 before the question and 02:03:53 after the answers):

> «Считать точно (Recommended)»
>
> (translation) "Compute exactly." — on U2's contradiction: composed exactly, HQ's accent link (5.09 on paper) over its 8 % ink underline band gives 4.34, below 4.5, so the task's rule gives FAIL where its test expected exit 0. The rule stands; that page gives A6 FAIL, and the passing control is the same underline under a link whose colour keeps the contrast over it.

> «Да, выполняй (Recommended)»
>
> (translation) "Yes, carry it out." — the plan.

The fixes, made by Claude Code (task TASK-CC-08), each with a test that fails without it and mutants (origin `0.1.0-a6`) naming their killers:

- **U1, a blur anywhere made the whole frame INCOMPLETE:** a `blur(r)` or `drop-shadow(dx dy b)` filter gives A6 INCOMPLETE only to the runs whose rectangles meet what it can paint, where the run was evidenced: the element's border box grown by 3 × r (r is the Gaussian's deviation), or moved by the drop shadow's offset and grown by 1.5 × b, functions in order, plus one pixel (`filter_ops`, `filter_reach`; `UNSEEN` measures filtered elements). The border box bounds what the filter takes in only for an element with no child elements or text, no rendered `::before`/`::after`, no shadow, outline or border image of its own, not SVG, replaced content or a list item; any other, a transformed one, a filter that cannot be read (now including an SVG filter `url()`, which X2 did not count) and a `::before`/`::after` filter keep the frame-wide rule; an element not measured stays INCOMPLETE; an animated filter (`getAnimations()`, a delayed one included) gives every run INCOMPLETE.
- **U2, an element's own shadow underline made its text INCOMPLETE:** a solid inset layer (no blur, a readable colour) of the run's element or an ancestor is composed exactly into the fallback's backdrop, with its alpha, above its element's backgrounds and in paint order; one element's layers with the same offset and spread are one group, and the run passes only over the plain backdrop and every combination of the groups (comparing only the plain backdrop and all bands together could pass a run part of which lies under one band alone), fails when one has a real point below the threshold. More than 4 groups, a band inside a faded group, an animated painter, and text in a stacking layer with a negative `z-index` between the painter and the text (painted beneath the band: X2's INCOMPLETE kept, never reopened) are INCOMPLETE; every other shadow reaching the run stays INCOMPLETE. HQ's `shadow_stack` and `shadow_always` now give A6 FAIL.
- **Y1, two layers no test isolated:** the per-scroll comparison is proved by `test_render_compares_paints_at_every_scroll_position`, which drives the renderer through scripted page reads (no browser: only the middle scroll offset paints differently, so the read after the evidence and the fresh loads see nothing); offsets and margins in the paint list by a browser test where a layer of fixed size moves by `top` alone in the middle of the scroll range (HQ's `scroll_mid_top` moved its height too) and by a check of the list. The two mutants keep their names; their new killers come first.
- **The CEO's decision on Question 5:** `check_design.py` certifies a font-stack variable, and `check_css.py` accepts it, only when its first family is an approved face, as for a literal stack; a stack of generic families alone fails in both. A1 is unchanged.
- **Found while narrowing, recorded only:** a list item's `::marker` drawn under another element's text, and text in a negative `z-index` layer painted beneath an ancestor's opaque background, are not detected (README's limits; reported to HQ).
- **Tests moved, not removed:** the X2 cases `shadow_stack` and `shadow_always` (recorded and browser) moved from "INCOMPLETE" to the new FAIL tests; X2's `blur` and `drop-shadow` cases far from the text moved to the controls that keep the pass, and the frame-wide cases now name a filtered element with content.
- **Mutant anchors moved** (same mutations): "R2-M07 stack values unchecked", "X2 unmeasured painter taken as not reaching", "X2 drop-shadow and blur filters ignored".
- **Documents:** README (this section, the limits), `scripts/docs/check_page.md`, `check_css.md`, `check_design.md`, the building skill (solid bands, blurs near text, stacks) and the profile reference (`stack_vars`).

## Changed after HQ's check of CC-06 (0.1.0, not released; 2026-11-12)

HQ ran head CC-06 in the cloud (Linux, Chromium 153: the whole suite, the full mutation run, its probes and pixel checks) and found W1–W5 closed, 298 of 299 mutants killed (the Windows-only one survives there), and two more ways to a false PASS of A6, both checked by pixel (X1, X2, high), the six new browser tests of W1 and W3 failing on Linux for one filter (X3, medium) and the mutation runner crashing on non-ASCII output on Windows (X4, low). The CEO's words that govern these fixes (HQ session, 2026-11-11; question forms; times of the answers not read):

> «Да, и в прямых стеках (Recommended)»
>
> (translation) "Yes, in literal stacks too." — on Claude Code's Question 5 of CC-06 (listed fallback families in a literal `font-family` stack of a page's own CSS): one rule for any stack; A1 still judges the font that actually drew the text.

> «Да, пиши CC-07 (Recommended)»
>
> (translation) "Yes, write CC-07." — the approval of the task.

And in Claude Code's session, on its plan for TASK-CC-07 (2026-11-12; the next clock reading after the answers was 00:12:07):

> «Да, выполняй (Recommended)»
>
> (translation) "Yes, carry it out." — the plan.

> «(1) исправить, (2) записать»
>
> (translation) "(1) fix, (2) record." — on two more ways to a false PASS of A6 that Claude Code found while reading the code: (1) a filter on a text's ancestors (such as `brightness()`), which axe-core does not compose, taken on axe's pass: fixed; (2) a `text-shadow` of a neighbouring element reaching the text: recorded only (README's limits; reported to HQ).

The fixes, made by Claude Code (task TASK-CC-07), each with a test that fails without it and mutants (origin `0.1.0-a5`) naming their killers:

- **X1 (high), a reader-preference change in a paint property PAINTS did not read** (HQ's `contrast_shadow`: an inset ink box-shadow drawn only for more contrast passed): every comparison of paints (the first read, each scroll offset, the read after the evidence, each fresh load) reads one list, `PAINT_PROPS` in `pagejs.py`: the old properties plus box-shadow, border colours, widths, styles and radii, outline colour, width, style and offset, background size, position, repeat, clip, origin, attachment and blend mode, padding, width, height, the border image's source, slice, width, outset and repeat, `-webkit-box-reflect`, `accent-color`, `color-scheme`, text decoration line, style and thickness, mask size, position and repeat, overflow, `offset-path`, SVG stroke width and opacities; a rendered `::before` or `::after` is read with the same list. The fresh loads also compare every element's border box (`BOXES`, page coordinates; every fresh load and the evidence page's first read are at offset 0); the comparisons while scrolling do not (sticky and fixed boxes move).
- **X2 (high), box-shadow not counted as part of the backdrop** (HQ's `shadow_stack`: site X's approved card shadow stacked 60 times as inset shadows of the text's ancestor passed): where each text run is evidenced, `UNSEEN` measures the boxes of every element with a box-shadow, an outline or a border image and the run's text rectangles; a painting layer that reaches the run gives A6 INCOMPLETE ("a shadow paints under the text: <element>"; an outline "is drawn over", a border image "paints under"): an inset shadow of the run's element or an ancestor or of an element whose padding box meets the run; an outer shadow by its offset, spread and 1.5 × blur plus a pixel, never inside its own rounded border box (used radii); an outline by its ring; a border image by its outset. A blur or drop-shadow filter, a reflection, such a paint on a `::before`/`::after`, an unreadable shadow, one of a transformed element, or a box not measured where the run was evidenced gives every text run of the frame INCOMPLETE. No shadow is composed. README's limits list what is still not seen.
- **X3 (medium, tests):** the six browser tests of W1 and W3 filter on the probe paragraph's real path (`div`, HQ's correction); their "no PASS" assertions, and the other A6 ones of `test_check_page.py`, go through `not_a_pass`, which needs an item of the check on that path (a filter matching nothing was vacuous; A6 writes no PASS item per run at all); a test of the helper on recorded items runs on every platform.
- **X4 (low), the mutation runner on Windows:** the child runs with `PYTHONIOENCODING=utf-8` and its output is read as UTF-8 with replacement; a test feeds the runner a real failing killer that prints Cyrillic and bytes that are no text.
- **Filters on text (the CEO's decision (1)):** where axe passed a text run, a `filter` or `backdrop-filter` on its element or an ancestor gives A6 INCOMPLETE ("axe does not compose filters").
- **Literal font stacks (the CEO's decision on Question 5):** `check_css.py` accepts a literal `font-family` stack whose first family is an approved face and whose other families are approved faces, generic families or listed in `fonts.fallback_families`; A1 is unchanged.
- **Mutant anchors moved** (same mutations): "W1 preference comparison removed (renderer)", "W1 frame list not compared", "fallback families ignored (check_css)", "C2 offsets and margins left out of PAINTS", "R2-H02 scale left out of PAINTS".
- **Documents:** README (this section, the limits), `scripts/docs/check_page.md`, `check_css.md`, the building skill (shadows, outlines, border images and filters near text; lazily loaded images; literal stacks) and the profile reference (`fallback_families`).

## Changed after HQ's check of the round-2 fixes (0.1.0, not released; 2026-11-11)

HQ ran the round-2 head (CC-05) in the cloud (Linux, Chromium 153: the whole suite, the full mutation run, Sol's six reproduced probes and its own) and found all 22 findings closed in the code, and one high (W1), two medium (W2, W3) and two low (W4, W5) items. The CEO's decisions that govern these fixes (HQ session, 2026-11-11; question forms; times of the answers not read):

> «Принять как есть (Recommended)»
>
> (translation) "Accept as it is." — on Claude Code's Question 1 of CC-05 (a text run taller or wider than the viewport gives A6 and A1 INCOMPLETE): the INCOMPLETE stays, and so does the building rule to split long text. No code change; README's limit stays.

> «Ключ для запасных (Recommended)»
>
> (translation) "A key for fallbacks." — on Claude Code's Question 6 of CC-05 (the lab's font-stack variable names system fallbacks): the plugin lets a policy name allowed system fallback families; A1 still judges the font that actually drew the text.

And in Claude Code's session, on its plan for TASK-CC-06 (2026-11-11; the next clock reading after the answer was 03:30:52):

> «Все сочетания (Recommended)»
>
> (translation) "Every combination." — on W1's scope: the fresh loads cover every combination of reduced motion, contrast and reduced transparency (11 per render), not each value alone.

The fixes, made by Claude Code (task TASK-CC-06), each with a test that fails without it and a mutant (origin `0.1.0-a4`) naming its killers:

- **W1 (high), evidence in a reader-preference state not every reader has:** the evidence page's state is pinned by CDP `Emulation.setEmulatedMedia` before the load (reduced motion `reduce`, contrast and reduced transparency `no-preference`, its colour scheme) and confirmed by `matchMedia` after the evidence. Then the page is loaded again, fresh (a new context with the same routing, proxy and request log), in each of the 11 other combinations of `prefers-reduced-motion`, `prefers-contrast` (`more`, `less`) and `prefers-reduced-transparency`; every checked frame's PAINTS is compared with the evidence page's first read (a different frame list changes every frame). A difference gives every text run of that frame A6 INCOMPLETE naming the states; a state not confirmed in its load, an unconfirmed evidence state, a missing state or a missing record gives INCOMPLETE too. `forced-colors: active` stays a stated limit.
- **W2 (medium, tests):** HQ's three corrections taken as they are: `make_server`'s inventory argument; the screenshot-link test's capture named as kept (`w1280-light.png`); the deadline test passes `--run-as` when run as root.
- **W3 (medium, test):** a browser test of HQ's probe `scroll_mid` (the layer hidden only in the middle of the scroll range) kills "R2-H02 per-scroll comparison removed (renderer)".
- **W4 (low, test):** translucent text over a gradient whose dark end is below the threshold (FAIL on the worst sample) kills "fallback takes the best stop" without a browser.
- **W5 (low, tests):** the bundle root swapped for another real folder around one read is refused (every platform), and on POSIX a swap between the identity checks reads through the root's descriptor (the real bytes): both kill "R2-M01 bundle root reopened by path for each read".
- **Fallback families (the CEO's decision on Question 6):** the optional policy key `fonts.fallback_families` (a list of non-empty family names; its shape is checked with the policy's); a font-stack variable is certified when every family of its value is an approved face, a generic family or a listed fallback (`check_design.py` and `check_css.py`); A1 is unchanged. `check_design.py`'s FAIL line now names the list (`fonts.fallback_families [...]`).
- **Documents:** README (this section, the limits), `scripts/docs/check_page.md`, `check_design.md`, `check_css.md`, the building skill (the reader-preference rule) and the profile reference (`fallback_families`).

## Changed after round 2 of the outside audit (Sol 6.1) (0.1.0, not released; 2026-11-10)

Sol 6.1 read head H6: NOT_READY, 22 findings (IDs `R2-H01` … `R2-L03`); Gemini Argon 4: READY. HQ judged every finding (none rejected; 19 confirmed, 3 confirmed in part). The CEO's decisions that govern these fixes (HQ session, 2026-11-10; question forms):

> «Квитанцию коммичу я (Recommended)»
>
> (translation) "I commit the receipt." — on R2-H06, how approval binds the receipt: after `ready.json` is issued, the owner commits it too; the check requires the receipt to equal the committed one; one extra commit per receipt.

> «Все 22, включая низкие (Recommended)»
>
> (translation) "All 22, lows included." — on the scope: each fix with a test and a mutant.

The fixes, made by Claude Code (task TASK-CC-05), each with a test that fails without it and a mutant (origin `0.1.0-a3`) naming its killers:

- **R2-H01 (high), Windows aliases:** one portable path-component grammar in `bundlelib.py`, on every platform, before anything is opened, logged or staged (resolver, reader, guard, closure, server keys, `check_css.py`): a trailing dot or space, `:` (streams, drives), `\ < > " | ? *` or a control character, `~` and a digit (8.3 short names), or a Windows device name with or without an extension is refused; a nested drive path is a named result, never INTERNAL.
- **R2-H02 (high), the checker changed the page:** no marker attribute, no appended style, no viewport resize. Element identity is the index in `querySelectorAll('*')` (CDP node ids from the document tree read once; axe with `elementRef`; the overlap probe checks `pointer-events: none` boxes instead of forcing them on). The main frame is scrolled to the offsets that bring every text run wholly into the viewport (at most 40), and each run's contrast, overlap and font evidence is taken there; PAINTS (with `scale`, `rotate`, `translate`, `clip`, `zoom`, `content-visibility` added) is compared with the first read at every offset used; text in a transparent child frame is INCOMPLETE ("the backdrop lies outside the frame"); viewport-size captures at the offsets used replace the full-page capture.
- **R2-H03 (high), contrast:** SVG text composes `fill-opacity` (collected) and gives INCOMPLETE for a paint server, `context-fill`/`context-stroke` or a visible stroke; a gradient passes only by a proved lower bound over every sRGB interval (luminance convex in the position; ternary search with a stated margin), fails at a real point below the threshold, else INCOMPLETE (method in `scripts/docs/check_page.md`).
- **R2-H04 (high), A1's file identity:** the loopback server serves only canonical staged keys (no normalisation of the request: dot segments, `//`, encoded `/` or `\`, case variants are 404, logged as refused, the raw request line read) and logs the staged key and the SHA-256 it sent; A1 judges those bytes.
- **R2-H05 (high), paints that escaped A2:** a `url(…)` paint's fallback colour is judged; a `url(…)` naming no gradient of the document is INCOMPLETE; `color(srgb …)` and `color(srgb-linear …)` are converted exactly (fractional channels kept), other spaces give a floor INCOMPLETE; unreadable backgrounds, shadows and stops are reported, never dropped.
- **R2-H06 (high), the receipt's hashes (the CEO's decision):** where a repository is reachable, `ready.json` must be tracked at HEAD and equal its committed blob; `--issue` prints its SHA-256 and ends with "commit ready.json now"; README and the skills state the trust model; the test helpers commit the receipt.
- **R2-M02 (low by HQ), Git's transformations:** approval and issue compare `git cat-file blob` bytes with the snapshot's after CRLF-to-LF only; `hash-object --path` (which runs clean filters) is gone; a path with a `filter`, `ident` or `working-tree-encoding` attribute is INCOMPLETE.
- **R2-M01 (low by HQ), the staging root:** the bundle root is opened once (a link at the root refused); POSIX reads go through its one descriptor, and its identity is checked before and after every read on every platform.
- **R2-M12 (low by HQ), the private renderer:** the job lists the staged inventory (key and SHA-256); only listed files with matching bytes are served; README and `check_page.md` state the hidden entry's trust boundary.
- **R2-M10 (low by HQ), FAIL evidence:** a named axe violation stays FAIL when the frame's paint changed; an oversized renderer result keeps its A10 evidence (cut, with counts) and reports the rest INCOMPLETE.
- **R2-M08 (medium), A12's evidence:** every checked frame needs an `axe_a11y` result; every rule axe-core 4.14.0 has for the selected tags (from `axe.getRules`, the excluded tags removed, less `color-contrast` and the top-document rules in child frames) must appear in it; `accessibility.default` sets the tier of unlisted rules.
- **R2-M09 (medium), A13:** fields are credited once to their owner (`element.form`; buttons, outputs, fieldsets and objects included; unowned ones listed as such); `--kept` counts only with `--kept-sha256` (printed by `--snapshot`); the item names the desktop light render; rule version `a13-2`.
- **R2-M04 (medium), `check_css.py`'s variable paths:** one resolver, one budget (64 expansions per declaration) in every path; `color-mix()` operands' fallbacks validated; one variable map per document.
- **R2-L01 (low), `color-mix()`:** fractional channels and alpha kept until the exact comparison (no rounding, no tolerance).
- **R2-L03 (low), `--report` truncation:** the total line kept, "report truncated: N of M items printed", no outcome word while the exit is 0; the JSON carries `truncated` and `total` (outcome `REPORT` in report mode).
- **R2-M11 (low by HQ), references by token:** `url(` inside a CSS string is no reference; `<template>` content is not followed (both parsers); every SVG file of the closure is scanned for scripts and handlers.
- **R2-M05 (medium), `rem`:** converted at the root font size the site sets on `html` or `:root` (the smallest across media contexts; 16 px only when none); an uncertain root size takes 4.5:1; the smallest of the token's size and its trace-map font-size overrides is used.
- **R2-M06 (medium), policy shape:** the whole shape of `policy.yaml` is checked before any entry is read (a wrong type anywhere: a named POL FAIL, never INTERNAL 4); `buttons.paint` names palette tokens, or `paint: selectors-only` says so; the Y and Z fixtures name their own tokens (this replaces CC-03's Q6f).
- **R2-M07 (medium), certified variables:** a font-stack variable is certified only when every family of its value is an approved face family or a generic family (`check_design.py` fails it otherwise; `check_css.py` refuses an uncertified one); derived variables are validated for each role and scheme, in every `:root` context that declares them.
- **R2-M13 (medium), P1's dependency graph:** the ambiguity and `!important` checks follow every variable the bound one reaches (every definition, every inheritance branch; `csslite` keeps which properties a rule marks `!important`); once `site.yaml` names component stylesheets, `generate_css.py` binds every field they define for the component's selector to it.
- **R2-M03 (medium), outputs:** one shared writer (`designlib.write_output`) for every file the plugin writes: a new file created exclusively in the destination folder and put in place with `os.replace`; an existing name that is a link, a junction, a hard link or not a regular file is refused (ERROR 2), nothing written; the generator reads `trace-map.yaml` through the same validated name.
- **R2-L02 (low), run limits:** the 120 s deadline counts from before staging; the renderer's result shares the 60 MB artefact budget with the captures; captures are viewport-sized, bounded before capture.
- **Documents:** README (the receipt's commit and the trust model, `--kept-sha256`, what the screenshot shows, the limits), `scripts/docs/check_page.md`, `check_css.md`, `check_design.md`, `generate_css.md`, the three skills and the profile reference.

## Changed after HQ's check of the round-1 fixes (0.1.0, not released; 2026-11-10)

HQ ran the round-1 head in the cloud (Linux, Chromium, the full mutation run, the lab's real site design folder, probes) and found 2 high (V3, V4), 2 medium test defects (V1, V2) and 7 low (C2–C8); the fixes, made by Claude Code (task TASK-CC-04), each with a test that fails without it and a mutant (origin `0.1.0-a2`):

- **V3 (high):** `designlib.typed()` makes a comma list only at a top-level comma; a single value whose commas sit inside a function or a string (`minmax(0, 1fr)`, `cubic-bezier(…)`, `"a, b"`) is one item. It used to call itself without end, which `check_design.py` (a bound rule's declarations) and `check_css.py` (the certified-variable check) reached as INTERNAL 4.
- **V4, C2 (high, low):** A6 compares the paints read before and after checking for every element of a frame, not only the text's ancestors: a sibling layer behind the text that the checker's marker or the taller viewport hides or moves gives every text run of that frame INCOMPLETE. Offsets (`top`, `right`, `bottom`, `left`) and margins are part of the paints.
- **V1, V2 (medium, tests):** the `display: contents` test accepts A6 FAIL or INCOMPLETE on the element (Chromium gives INCOMPLETE); the dark-render test hides its image in the base rule before the dark `@media` block.
- **C3:** A13's fields are `form.elements` and the form's subtree, each once, in document order (`<input type="image">` counts again).
- **C4:** the renderer child writes its result only to the staging folder's `out/result.json`; a job naming any other result path writes nothing.
- **C5:** a reference whose percent-decoded path holds a control character (U+0000–U+001F) is outside the bundle (A10 in `check_page.py`, the CSS failure in `check_css.py`), never INTERNAL.
- **C6:** `check_css.py` expands at most 64 page-variable definitions per declaration (more: one INCOMPLETE) and keeps at most 5,000 report items, failures first, like `check_page.py`.
- **C7:** a `font` shorthand whose family is exactly one approved font-stack variable is checked as `font-family`; any other `var()` in it stays INCOMPLETE.
- **C8:** the tests' child processes run with `-B` (no `__pycache__` in `scripts/`).
- **Documents:** README (limits), `scripts/docs/check_page.md`, `scripts/docs/check_css.md`, the building skill (offsets, margins and sibling layers; `display: contents`; the `font` shorthand and the definition budget).

## Changed after the outside audit, round 1 (0.1.0, not released; 2026-11-10)

Two outside auditors read the audit package of head H5 (Codex Astra: 9 high, 21 medium, 3 low, IDs `AST-…`; Gemini Argon 4: 3 high, 5 medium, 5 low, IDs `AUD-…`). HQ judged every finding (none rejected); the planned fixes, made by Claude Code (task TASK-CC-03):

- **Receipt and approval (AST-H08, AST-H09, AST-M12, AST-M04):** a strict receipt schema (a JSON object with exactly its keys, no duplicate key, version 1, hex ids and digests, `blob` required) and inventories (the folder's files, the CSS files of `site.yaml`, the policy's font files) checked before any named file is read; with no repository, approval counts only with `--receipt-sha256` (new option of `check_css.py` and `check_page.py`; the CEO's decision: «Только с отпечатком» — "only with a fingerprint"); `HEAD` resolved once; every blob computed with `git hash-object --stdin --path` over the bytes the checks read; `--issue` writes to a new file and renames it into place, refuses a linked `ready.json` and inputs that changed during the run.
- **Bundle guard (AST-H01, AST-H02, AUD-F03):** a new shared module `bundlelib.py`: forbidden names in any path component, bytes equal to a site design folder file refused, refused files never quoted; each file read once without following links (POSIX: directory descriptors; Windows: reparse points per component) and the same bytes parsed, hashed and staged; CSS comments stripped before references; one percent-decoding resolver; the first of duplicate attributes.
- **check_page (AST-H03–H07, AST-M01–M03, M13–M16, M18, M21, AST-L01, AUD-F01, AUD-F02, AUD-F13):** paints read before marking and after all evidence (a change: A6 INCOMPLETE); every axe violation a FAIL; text runs by their rectangles (`display: contents`); the fallback samples sRGB gradients, refuses group compositing and more than 512 backdrops, reads the glyph paint (`-webkit-text-fill-color`, SVG `fill`), keeps the size unrounded; A1 binds fonts to approved bytes (first bytes, served approved file, bundle-only `@font-face` sources, empty CDP data INCOMPLETE); every gradient stop and SVG `stop-color` judged; painting descendants count as overlap; nested `srcdoc` and (kind, path) deduplication; closure findings before rendering; outputs before the summary, never inside the site design folder; one deadline; result and screenshot caps before writing; exact child modes tied to the parent's staging folder; A7/A4 layout sizes; A8 and A12 in both schemes, A11 in both desktop renders, A9 presence; A12 needs execution evidence; A13 snapshot schema, coverage and form ownership; summaries INFO; findings keep their render.
- **check_css (AST-M10, AST-M11, AST-H07, AUD-F05, AUD-F10, AST-L02):** every definition of a page variable; fallbacks at every level with a cycle guard; certified variables protected; the `font` shorthand; frame documents; SVG presentation attributes and `stop-color`; `<code style>` as a code role; report mode through the declaration parser, `@keyframes` included.
- **check_design (AUD-F06, AST-M05–M09, AST-M15, AUD-F04, AUD-F07–F09, AUD-F12, AST-M17):** typed component fields; unreadable site CSS ERROR 2; empty bindings refused; several different declarations INCOMPLETE; component typography whole (family, subset, inheritance chain); design-first clamp maximum; P3 own background, smallest size, `rem`/`em`, aliases before pairs, baselines keyed by resolved colours (`text_colour`, `surface_colour`); a policy schema (non-empty floor sections, typed faces with existing files and their SHA-256, roles per scheme within its set, complete pairs, axe tags known to axe-core 4.14.0, accessibility tiers, typed waivers); A12 out of the assertion tiers; derived values read whole; `component_stylesheets` loaded and hashed; hex alpha exact.
- **generate_css (AST-M05, AST-M04, AUD-F11, AST-M20):** LF bytes on every platform; destinations validated; errors ERROR 2, anything else INTERNAL 4; the starting skill writes the policy before generating.
- **Documents (AST-L03, AST-M20, all of the above):** the three skills, the profile reference, the README and the script docs; `inventory_css.py`'s claim narrowed to its list (more longhands added).
- **Tests:** a test that fails without each fix and a mutant (origin `0.1.0-a1`) naming its killers; `tests/test_page_analysis.py` (check_page without a browser); the test helpers write LF on every platform; `check_page.py`'s two entry-point runs skip without Playwright.

## 0.1.0 — 2026-11-10

First version (plan 0.4, approved by the CEO on 2026-11-10; decision J1 during the build).

- Three skills: `starting-a-site-design-system` (design-first), `keeping-a-site-design-system` (the site design folder: document, audit, extend; approval and receipt), `building-in-a-site-design-system` (pages, panels, images, redesigns).
- Scripts: `check_design.py` (P2 parse, P1 trace, P3 token contrast, policy, publication boundary, approval by commit and the `ready.json` receipt), `check_css.py` (static role check; report mode), `check_page.py` (contained Chromium, axe-core 4.14.0, A1–A13), `generate_css.py`, `inventory_css.py`, `font_facts.py`; shared `designlib.py`, `csslite.py`, `policylib.py`, `pagejs.py`.
- Page scripts are blocked by Content-Security-Policy `script-src 'none'` from the loopback server (J1), replacing "JavaScript disabled" of plan 0.4 B.8.1, under which axe-core hangs.
- Fonts are identified by Chromium's CDP (`CSS.getPlatformFontsForNode`); profile font facts are read by `font_facts.py` (fontTools when it can read the file, else the browser), replacing "fontTools at staging" of plan 0.4 B.4.
