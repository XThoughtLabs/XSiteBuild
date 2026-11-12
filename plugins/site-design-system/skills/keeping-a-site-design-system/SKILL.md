---
name: keeping-a-site-design-system
description: "Keeps a website's design system true to its CSS, in three modes: document (derive or update DESIGN.md, trace-map.yaml, contrast.yaml and policy.yaml from an existing site, seeded by inventory_css.py), audit (a read-only report of the site's design-system health: check_design.py --verify, check_css.py --report on the site's CSS, check_page.py on chosen pages), and extend (add a token or component in the right order). After the owner commits a profile, check_design.py --issue writes the ready receipt that agents need; Google's design.md lint and diff are optional reports, never gates. Use when a site's CSS or DESIGN.md changes, when a token or component is added, when the receipt is missing or stale, or when the user asks to document or audit a site's design. (рус.: обновить DESIGN.md, сверить со стилями сайта, аудит дизайна сайта, описать дизайн-систему, добавить компонент)"
---

# Keeping a site design system

Status: plugin site-design-system 0.1.0, 2026-11-10 (changed after the outside audit, round 1, the same day); plan 0.4 sections B.2, B.3, B.5.2, B.6, B.7. Owner of the site design folder: inventory, derivation, trace, token contrast, policy, waivers, approval and receipt. The design-first start is owned by `starting-a-site-design-system`; pages by `building-in-a-site-design-system`.

## Where the files are

- The site design folder is named by the owner (ask when unknown). It holds `site.yaml`, `DESIGN.md`, `trace-map.yaml`, `contrast.yaml`, `policy.yaml`, `waivers.yaml`, `README.md` and `ready.json`. It lives in the site's private repository, outside the deploy root.
- `site.yaml` names the site's CSS files (`css`), the deploy root, `source` (`css`: the CSS is the source; `design`: `DESIGN.md` is, see `starting-a-site-design-system`) and, design-first, `public_tokens`.
- The field reference of every file is in `references/profile-files.md`. Read it before writing or changing a profile file.

## Three modes

### Document (an existing site, `source: css`)

1. `inventory_css.py <css files> --json inventory.json`: every `:root` custom property and every colour, font, size, weight, line height, letter spacing, radius, shadow and spacing value with its selectors, media conditions and at-rule context. Exit 3 names unsupported at-rules (`@supports`, `@layer`, `@container`, `@scope`, `@import`): their contents cannot be traced; tell the owner.
2. Write `DESIGN.md` from the inventory: tokens in the front matter, prose below. A value used under different roles becomes different tokens only when the design means different things; ask when unsure.
3. Write `trace-map.yaml`: each token has exactly one projection, `var: --name` (a `:root` custom property holding the value) or `sel:` + `prop:` (a literal bound to selectors). Typography levels name their selectors; fluid sizes add `clamp_expr`; components name `sel`/`prop` per field (a host surface: `host:` and `own:`); mobile-only values go under `overrides`.
4. Write `contrast.yaml` (surfaces per scheme; a baseline only for known failures the owner decides to keep) and `policy.yaml` (every section; see the reference).
5. `check_design.py --site <folder>` until PASS. Then the owner reads the prose and commits; then `--issue`; then the owner commits `ready.json` (approval counts only once it is committed).

### Audit (read-only; writes nothing into the profile)

Report, in this order: `check_design.py --verify` outcome and counts; `check_css.py --site <folder> --report <site css files>` (hard-coded values by property and file: every colour part, gradient stop and family stack of style rules and `@keyframes`, read as the role check reads them; unsupported at-rules are named, not counted); `check_page.py` on pages the owner names (needs a fresh receipt); naming (tokens that break the naming rule); component completeness (text components without a surface in `contrast.yaml`, components without bindings). State what was not checked.

### Extend (add a token or component)

Order: the source side first (`source: css`: the CSS, then `DESIGN.md`, `trace-map.yaml`, `contrast.yaml`, `policy.yaml`; `source: design`: `DESIGN.md`, then `generate_css.py --write`, then the component CSS); then `--verify`; then the owner's commit; then `--issue`. Until then the receipt is stale and pages cannot be checked.

## Commands

Plugin root: two folders above this skill's base directory (in Claude Code also `${CLAUDE_PLUGIN_ROOT}`). Windows: `py -3 -I` instead of `python3 -I`.

```
python3 -I "<plugin root>/scripts/inventory_css.py" <css> [...] [--json FILE]
python3 -I "<plugin root>/scripts/check_design.py" --site "<folder>" [--verify | --issue] [--json FILE]
python3 -I "<plugin root>/scripts/check_css.py" --site "<folder>" --report <css> [...]
python3 -I "<plugin root>/scripts/font_facts.py" <font file> [--family NAME]
```
Outcomes: PASS 0, FAIL 1, ERROR 2, INCOMPLETE 3 (never a pass), INTERNAL 4. `--verify` (the default) writes nothing. `--issue` resolves `HEAD` once to one commit, checks that every file of the folder equals its committed bytes there (read-only Git plumbing only: `git rev-parse <commit>:./<path>`, `git cat-file blob <id>`, which runs no filter, compared with the very bytes the checks read after CRLF to LF only; `git check-attr`: a path with a `filter`, `ident` or `working-tree-encoding` attribute is never approved), refuses to issue when any input changed during the run, and only then writes `ready.json` to a new file in the folder and renames it into place (an existing `ready.json` that is a link, a junction, a hard link or not a regular file is refused): the commit, every profile file's blob and SHA-256, the SHA-256 of the CSS files (`css` and `component_stylesheets`), of every plugin script and vendored file, and of the fonts. Any later change to one of these makes the receipt stale (INCOMPLETE for every consumer). `--issue` prints the receipt's SHA-256 and ends with the owner's step: **the owner commits `ready.json`**; approval counts only once it is committed (the CEO's decision of 2026-11-10, below). Committing it does not make it stale: the receipt names the profile's commit, and a later HEAD whose profile files are byte-equal is fine. `--issue` refuses the report-only overrides `--css`, `--tokens` and `--deploy-root`; `--json` never writes into the site design folder (ERROR 2).

Consumers check the receipt's schema first (a JSON object with exactly the receipt's keys and no duplicate key, version 1, hex ids and digests, inventories equal to the folder's files, the CSS files of `site.yaml` and the policy's font files), before reading any file it names; an invalid receipt is INCOMPLETE. They re-check every profile file against `HEAD` and the receipt's commit wherever a repository is present, and require `ready.json` itself to be tracked at `HEAD` with its bytes equal to its committed blob ("the receipt is not committed, or changed since its commit"); `--no-git` there gives INCOMPLETE. **Trust model:** the owner's commit is the approval, for the profile files and for the receipt with the CSS, script and font hashes it holds; an agent never commits, so an edited stylesheet with an edited receipt stays uncommitted and INCOMPLETE.

> «Квитанцию коммичу я (Recommended)»
>
> (translation) "I commit the receipt." (the CEO, 2026-11-10, on how approval binds the receipt's hashes) A staged copy must sit outside any Git repository (inside an unrelated one, its files are "not tracked at HEAD": INCOMPLETE). With no repository at all, nothing proves the receipt came from `--issue`, so approval counts only when the task gives the consumer `--receipt-sha256 <SHA-256 of the issued ready.json>`, taken where the repository is (the owner's decision of 2026-11-10); without it, or with another value: INCOMPLETE.

## What the stages check

- **P2 parse:** strict YAML (duplicate keys refused even with identical values; YAML 1.2 booleans; at most 1 MB per file and 20 levels of nesting); schemas; typed tokens, component fields typed by what they resolve to (a dimension as `textColor` fails); binding coverage both ways (every token bound, every binding a token); a binding naming no selector, property or variable (`sel: []`, empty `vars`, an empty field) fails.
- **P1 trace:** each binding's CSS value equals the token by typed exact comparison (hex of 3, 4, 6, 8 digits expanded; `rgb()`/`rgba()` spellings; `0.10` equals `0.1`; `#001234` never equals `#1234`; an authored alpha `0.56` never equals `0.563`, nor `#00000001` 0.0039). Clamp parts compared, design-first too (DESIGN.md keeps the maximum); overrides compared under their media condition. A selector or `:root` variable declared several times with different values in one context gives INCOMPLETE (which one applies is not decided). Component typography is compared whole: every property of the token (family included) declared by the component's selector, or, when it declares none, found along its inheritance chain (`inherit`, default `body`). `@font-face`, `@keyframes`, `@view-transition`, `@page` are classified; any other at-rule gives INCOMPLETE. Unreadable site CSS (unbalanced braces) is ERROR 2.
- **P3 token contrast:** every text component on every listed surface and always on its own bound background, per scheme (with `both`, a light token, followed through aliases, is its dark pair), by WCAG 2.x with fractional compositing; 4.5:1, or 3:1 for large text (24 px, or 18.67 px at weight 700 and above) at the smallest size the text reaches (a `clamp()` minimum; `rem` at 16 px; an `em` size is undecided: INCOMPLETE between 3:1 and 4.5:1). A baseline entry keeps a known failure only while it gets no worse and its resolved `text_colour` and `surface_colour` are unchanged.
- **Policy:** sections present; floor never off and never empty; every section's keys and types (the reference's table); roles for every scheme of the mode, within that scheme's set; complete scheme pairs; face files present with their SHA-256; axe tags known to axe-core 4.14.0; tiers and waivers valid and typed; extras' quotes found verbatim in `DESIGN.md` with their values; derived variables read whole (a paint the checker cannot read fails).
- **Publication boundary:** the folder outside the deploy root.

## Baseline, tiers and waivers

Only through the owner's commit: they are profile files. Never add a baseline entry, change a tier or write a waiver to make a check pass without the owner's words; record those words verbatim (`decision`, `owner_words`). Floor items (fonts A1, reserved tokens in A2, contrast A6, self-containment A10, containment and the receipt) have no tier and cannot be waived.

## Google's design.md tool (optional)

Pinned 0.4.0, run only after `--verify` passes, as a report. Its lint and diff are never gates and its exports are never a source of truth.

## Guarantee and limits

The trace is declaration-level: it proves each bound declaration equals its token, not the effective cascade of every element. Rendered pages are checked by `check_page.py`.

## Traps (incidents with evidence)

- The v0.1 trace passed a swap of two colour tokens (their values exchanged) because it compared value sets, not bindings (research audits, 2026-11-09). The trace now compares each token with its own binding.
- Bare numeric line heights were dropped by Google's tool (research probe p5, 2026-11-08): `lineHeight` is a quoted string.
- The v2 normaliser compared `#001234` and `#1234` equal (plan audit, 2026-11-10): 4-digit hex expands to `#11223344`; comparisons are typed and exact.
- In this build, a policy `off:` key was read as a boolean by PyYAML's YAML 1.1 rules (test failure, 2026-11-10): the loader now keeps only `true`/`false` as booleans.
- In this build, the receipt first recorded absolute Windows paths, unreadable on another machine (2026-11-10): CSS and font paths are relative to the site design folder.
- The outside audit (2026-11-10) made a hand-written `ready.json` without commit or blobs pass on a copy with no repository: the receipt's schema is now checked first, and such a copy needs `--receipt-sha256`.
- Round 2 of the outside audit (2026-11-10) edited a site stylesheet and rewrote its hash in `ready.json` with the profile untouched, and the consumer passed: where a repository is reachable the receipt must now equal its committed blob, so the owner commits `ready.json` after `--issue` (the CEO's decision). An `ident` attribute let two texts share one blob through Git's filters: approval now compares `git cat-file` bytes (CRLF to LF only) and refuses paths with a `filter`, `ident` or `working-tree-encoding` attribute.
- The same audit found that `generate_css.py --write` wrote CRLF on Windows and `--verify` then failed the regeneration: it now writes LF everywhere.

## Self-check scenarios

1. The site's CSS changed a colour value. → Extend order: update `DESIGN.md` (and the policy if a role changes), `--verify` until PASS, owner commits, `--issue`, owner commits `ready.json`.
2. The user asks "how healthy is our site's design system?" → Audit mode: the four reports, nothing written into the profile.
3. `check_page.py` says "stale receipt: policy.yaml changed since the receipt". → Do not edit `ready.json`; `--verify`, ask the owner to commit, then `--issue`, then ask the owner to commit `ready.json` ("the receipt is not committed" says this step is missing).
4. A task checks pages against a staged copy of the folder with no repository, and the checkers say "approval counts only with --receipt-sha256". → Ask for the SHA-256 of the issued `ready.json`, taken where the repository is; give it as `--receipt-sha256`; never compute it from the staged copy itself.
