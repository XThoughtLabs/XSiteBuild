---
name: starting-a-site-design-system
description: "Starts the design system of a new website before its CSS exists: takes an aesthetic direction (with the frontend-design skill when installed, otherwise a built-in checklist), writes DESIGN.md tokens and prose, creates the site's private design folder and profile, writes the site's page policy, generates the public tokens.css and its trace map with generate_css.py, and runs check_design.py until it passes; the owner's commit approves the profile and the ready receipt follows. Use when the user starts a new site, landing page or web app and no stylesheet exists yet, or asks for a design system from scratch. (рус.: новый сайт, дизайн-система с нуля, начать сайт, токены для нового сайта)"
---

# Starting a site design system (design-first path)

Status: plugin site-design-system 0.1.0, 2026-11-10 (changed after the outside audit, round 1, the same day); plan 0.4 sections B.3.3 and B.5.1. Owner of the design-first path. The site design folder itself (trace, contrast, policy, waivers, approval, receipt) is owned by `keeping-a-site-design-system`; pages are owned by `building-in-a-site-design-system`.

## When to use, when not

- Use: a new site, landing page or web app; no stylesheet yet; the user asks for a design system from scratch.
- Do not use: the site already has CSS → `keeping-a-site-design-system` (document mode, CSS-first: `source: css`).

## Where things go (ask; never guess)

1. Ask the owner where the site's **private design folder** goes: a folder in the site's own private repository, **outside the deploy root** (the folder that is published). Never inside it: `check_design.py` fails a folder inside the deploy root and reports INCOMPLETE when `site.yaml` names none.
2. Ask where the **public token file** `tokens.css` goes: the site's public asset path, inside the deploy root. It holds values only.
3. The site design folder holds exactly: `site.yaml`, `DESIGN.md`, `trace-map.yaml`, `contrast.yaml`, `policy.yaml`, `waivers.yaml`, `README.md`, and later `ready.json` (written only by `check_design.py --issue`). Any other file in it blocks approval until committed.

## Order of work

1. **Direction.** If Anthropic's `frontend-design` skill is installed, follow it and record its version in `README.md`. If not, use the checklist below; never install anything. Record the owner's approved direction verbatim in `policy.yaml` `decisions`.
   Checklist: purpose and audience; one reference site or image; palette with a role for every colour (text, background, border, accent, status); at most two type roles (display, body); shapes (radii) and density (spacing scale); motion (or none).
2. **`DESIGN.md`.** YAML front matter between two lines of exactly `---`, then prose. Groups: `colors`, `typography`, `rounded`, `spacing`, `components` (none may be empty). Rules:
   - token names: lowercase letters, digits, single hyphens (`card-text`, not `card_text`);
   - colours: `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb()`, `rgba()`, `transparent`, or a reference `"{colors.name}"`;
   - dimensions in `px`, `em` or `rem` only (never `pt`);
   - `lineHeight` always a **quoted** string (`"1.5"`): bare numbers are dropped by Google's design.md 0.4.0 model;
   - a fluid size keeps its **upper bound** in `DESIGN.md` (`fontSize: 56px`); its whole `clamp()` goes in `trace-map.yaml` as `clamp_expr`;
   - `fontWeight` is a number; component fields: `backgroundColor`, `textColor`, `typography`, `rounded`, `padding`, `size`, `height`, `width`.
   - Exports of other tools are never a source of truth.
3. **`site.yaml`:** `name`, `source: design`, `css` (the site's component stylesheets, may be added later), `deploy_root`, `public_tokens` (path of `tokens.css`, relative to the folder; inside the deploy root, never inside the site design folder), `policy_version: 1`. Add `component_stylesheets` only when component CSS exists (then component fields bind to selectors, not variables); those files are loaded by the trace and hashed into the receipt like `css`.
4. **`policy.yaml`, before generating:** `generate_css.py` reads the policy (its `scheme.mode` and, for `both`, the light-to-dark `pairs`), so the policy comes first. Every section is required (see `keeping-a-site-design-system` and its reference for each section's fields and types). The floor sections `fonts`, `roles`, `reserved` can never be `off` and never be empty (`reserved: []` is the empty set; `fonts.faces` lists at least one face with its coverage; `roles` names each scheme of the mode). `scheme` can never be `off` either: the checks need its mode. Every other section may be `off: <reason>`; its assertions then report NOT_CONFIGURED, never a pass. Fonts: each face's file (it must exist and have the SHA-256 the policy names), SHA-256, PostScript name, weight range, style and coverage ranges (read them from the font file, see `keeping-a-site-design-system`).
5. **Generate.** `generate_css.py --site <folder>` prints; `--write` writes `tokens.css` (LF line ends on every platform) and `trace-map.yaml`. Variable names: `--color-<t>`, `--radius-<t>`, `--space-<t>`, `--type-<level>-family|size|weight|line|tracking`, `--comp-<component>-<field>`. With `scheme.mode: both`, a `@media (prefers-color-scheme: dark)` block maps each light colour to its pair. The first line says "generated, do not edit" with the source's SHA-256. Never edit `tokens.css` by hand: `check_design.py` fails any difference from a fresh regeneration. Regeneration rewrites `trace-map.yaml`: component fields bind to their generated variables until `site.yaml` names `component_stylesheets`; from then on every field those stylesheets define for the component's selector (the selector the map already names for it, else `.<component>`) binds to that selector, typography included when they declare a font property there, and the rest keep their variables. A component typography those stylesheets do not declare still needs its `sel` re-added after regenerating (P1 fails without it).
6. **`contrast.yaml`:** for each scheme, every text component and every surface it sits on (`surfaces: {light: {card: [paper]}}`); a translucent surface names the opaque surface beneath (`[paper, tint]`); a component without its own background names its base component under `base:`. The component's own background is always checked too. `baseline: []` for a new site.
7. **Check.** `check_design.py --site <folder>` (read-only `--verify` is the default) until PASS (exit 0). Fix every FAIL; an INCOMPLETE names what could not be verified.
8. **Approval.** The owner reviews the prose (the checker reads only the excerpts that `policy.extras` quote from it, verbatim) and commits the folder. Agents never commit it.
9. **Receipt.** After the commit: `check_design.py --site <folder> --issue` writes `ready.json` (only when every file of the folder equals its committed version, and no input changed during the run); then the owner commits `ready.json` too: approval counts only once it is committed (`--issue` ends with that step). Pages need a fresh, committed receipt.

## Commands

Plugin root: two folders above this skill's base directory (in Claude Code also `${CLAUDE_PLUGIN_ROOT}`).

```
python3 -I "<plugin root>/scripts/generate_css.py" --site "<folder>" [--write]
python3 -I "<plugin root>/scripts/check_design.py" --site "<folder>" [--verify | --issue] [--json report.json]
```
Windows: `py -3 -I "<plugin root>\scripts\check_design.py" ...`. Outcomes: PASS 0, FAIL 1, ERROR 2 (an input or dependency unusable, named), INCOMPLETE 3 (never a pass), INTERNAL 4. Dependencies: Python 3.10+ and PyYAML; nothing installs itself; a missing one gives ERROR naming it: ask the owner.

## Traps

- A fluid size written as its lower bound in `DESIGN.md`: the trace fails (the upper bound must equal the clamp's maximum).
- `lineHeight: 1.5` without quotes: P2 fails (Google's 0.4.0 model drops bare numbers; research probe, 2026-11-08).
- A policy key `off:` (or `on`, `yes`, `no`) read by a YAML 1.1 parser as a boolean: the checker uses YAML 1.2 booleans only (only `true`/`false`); a section switched off reads as switched off.
- `tokens.css` touched by hand to fix one value: the regeneration check fails; change `DESIGN.md` and regenerate.
- A token added to `DESIGN.md` without regenerating: P2 fails (no binding) and the regeneration check fails.
- Generating before `policy.yaml` exists: `generate_css.py` stops with ERROR 2 (it needs the scheme pairs). In this build the skill first listed the policy after generation (outside audit, 2026-11-10).
- `--tokens` pointing into the site design folder or outside the deploy root: `generate_css.py --write` refuses it (ERROR 2).

## Self-check scenarios

1. The user asks for a landing page design for a new product; no CSS exists. → This skill: ask for the private folder and the public token path; direction; DESIGN.md; site.yaml; policy; generate; contrast; `--verify` until PASS; owner commits; `--issue`.
2. The user asks to document the design of their existing blog. → Not this skill: `keeping-a-site-design-system`, document mode (`source: css`).
3. `check_design.py` reports `P1 tokens.css differs from a fresh regeneration`. → Do not edit `tokens.css`; run `generate_css.py --write` from `DESIGN.md`, then `--verify` again.
