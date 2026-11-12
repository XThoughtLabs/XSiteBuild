# Profile files: field reference

Contents: 1 `site.yaml` · 2 `DESIGN.md` · 3 `trace-map.yaml` · 4 `contrast.yaml` · 5 `policy.yaml` · 6 `waivers.yaml` · 7 `ready.json`

All YAML is read strictly: duplicate keys fail (even with identical values), only `true`/`false` are booleans, at most 1 MB per file, at most 20 levels of nesting. Token names: lowercase letters, digits, single hyphens.

## 1. `site.yaml`

```yaml
name: site-x
source: css                 # css: the site's CSS is the source; design: DESIGN.md is (generated tokens.css)
css: [../site/x.css]        # the site's stylesheets, relative to this folder
deploy_root: ../site        # the published folder; this folder must lie outside it
public_tokens: ../site/tokens.css   # design-first only: inside the deploy root, never inside this folder
component_stylesheets: [../site/y.css]   # design-first, once component CSS exists: every field they define for the component's selector binds to it (generate_css.py; .<component> unless the map names one), the others keep --comp- variables; traced and hashed like css
policy_version: 1
```

## 2. `DESIGN.md`

Front matter between two lines of exactly `---`. Groups (none empty): `colors` (colour or `"{colors.other}"`), `typography` (levels with `fontFamily`, `fontSize`, `fontWeight` number, `lineHeight` quoted string, `letterSpacing`), `rounded`, `spacing` (dimensions in px, em, rem, or references resolving to one), `components` (fields `backgroundColor`, `textColor` (resolving to a colour), `typography` as `"{typography.level}"`, `rounded`, `size`, `height`, `width` (resolving to a dimension), `padding` string). Prose below: the owner reviews it; the checker reads only the excerpts that `policy.extras` quote, which must occur in it verbatim.

## 3. `trace-map.yaml`

```yaml
colors:
  ink: {var: --ink}                         # a :root custom property holding the value
  primary: {ref: "{colors.ink}"}            # an alias: the DESIGN.md value must be this reference
  white: {sel: .button, prop: color}        # a literal bound to a selector (CSS-first only)
typography:
  display: {sel: [.hero h1], clamp_expr: "clamp(32px, 5vw, 56px)"}   # every property of the level read there
  body: {sel: [body]}
  title: {vars: {fontSize: --type-title-size}}                       # design-first
rounded:
  card: {sel: .card, prop: border-radius}
spacing:
  gap: {var: --gap}
components:
  card:
    backgroundColor: {sel: .card, prop: background, ref: "{colors.paper}"}
    typography: {sel: .card p, ref: "{typography.card-text}"}
  link:
    backgroundColor: {host: body, own: .link, ref: "{colors.paper}"}   # the surface it sits on
overrides:
  - {sel: .hero h1, media: "(max-width: 600px)", prop: font-size, value: 30px}
```
Optional per binding: `media` (read inside that condition), `pattern` (a regex whose group 1 is compared), `kind`; for component typography `inherit` (the selectors its properties are inherited from when it declares none; default `body`). A binding must bind something: `sel` names at least one selector (with `prop`, except typography), `var` a custom property, `vars` every property of its token; an empty binding fails P2. A selector or `:root` variable declared several times with different values in one context gives INCOMPLETE.

## 4. `contrast.yaml`

```yaml
surfaces:
  light:
    card: [paper]                 # every surface the text component sits on
    tag: [paper, tint]            # a translucent surface after the opaque one beneath it
    button-primary: [self]        # its own background
  dark:
    card: [paper-dark]
base:
  link-hover: link                # a state without its own background takes its base component's
baseline:                         # known failures kept by the owner's decision; never worse
  - {component: caption, scheme: light, text: "{colors.caption-grey}", surface: paper, method: fractional, ratio: 4.1203,
     text_colour: "#767676", surface_colour: "#fffdf7", decision: "owner's words"}
```
A baseline entry holds only while its resolved colours are unchanged: `text_colour` is the text token's colour in that scheme, `surface_colour` the surface's colour (a list, one per layer, for a layered surface). The component's own background is always checked, listed or not.

## 5. `policy.yaml`

Every section is required. Floor sections `fonts`, `roles`, `reserved` can never be `off`, and are never empty (`reserved: []` is the empty set). `scheme` can never be `off` either: the checks need its mode. The sections that may be `off: <reason>` (NOT_CONFIGURED, never a pass): `extras`, `derived_vars`, `headings`, `labels`, `forbidden_text_colours`, `fills`, `measure`, `capitals`, `buttons`, `accessibility`, `tiers`, `decisions`. Each section's fields have the types below; a wrong type, an unknown token, or an empty floor section fails the policy check.

| Section | Fields | Used by |
|---|---|---|
| `roles` | per scheme (`light`, `dark`: every scheme of the mode, each a non-empty mapping), per property (`color`, `background-color`, `border-color`, `outline-color`, `box-shadow`, `fill`, `stroke`) the allowed tokens, each in that scheme's `scheme.sets` | A2, check_css |
| `reserved` | tokens never painted in new work (`[]` when none) | A2 (floor) |
| `extras` | list of `{id, rgb: [r, g, b], alpha: 0.08 or [0.18, 0.4], roles: [...], quote}`; roles from: `text`, `background`, `decoration-background`, `gradient-stop`, `border`, `outline`, `box-shadow`, `fill`, `stroke`, `svg-text`; the quote is copied verbatim from DESIGN.md and contains the alpha and the base colour (as `rgb(...)` or `{colors.token}`) | A2, check_css |
| `derived_vars` | list of `{name: --shadow, roles: [box-shadow]}`: variables built only from allowed values (the whole value is read, in every `:root` context that declares it, references resolved; each paint must be allowed in each of its roles in each scheme that context applies to; a paint the checker cannot read fails); a page may never redefine them | check_design, check_css |
| `fonts` | `faces` (at least one): `{family, file, sha256, postscript, weight: [min, max], style (normal, italic, oblique), coverage: [[first, last], ...] (non-empty)}`, the file present with that SHA-256; `stack_vars` (font-stack variables declared in `:root`, the first family of their value an approved face family and every other family an approved face family, a generic family or a family listed in `fallback_families`, else FAIL, the same rule as a literal stack's; a stack of generic families alone fails; never redefined by a page); `fallback_families` (optional: a list of non-empty family names, the system fallbacks a font-stack variable, or a literal `font-family` stack of a page's own CSS, may name after the approved face, such as a platform's UI font; it allows the stack only: A1 still fails text that one of them actually draws); `code_roles: system-monospace` or `off` | A1, check_css, check_design |
| `headings` | `tokens`; `accent: {tokens, max_share, max_runs}` or none; `selectors` | A3 |
| `labels` | `selectors`; `style: {max_size_px, min_weight}` | A5, A7, A8 |
| `forbidden_text_colours` | tokens never used for text | A5 |
| `fills` | list of `{tokens, alpha_above, max_area_px2}` (a named heuristic) | A4 |
| `measure` | `default_px`; `roles: [{selector, px}]` | A7 |
| `capitals` | `labels-only` or `off` | A8 |
| `scheme` | `mode: light-only | dark-only | both`; `sets` per scheme of the mode (non-empty token lists); for `both`, `pairs` (light-set token: dark-set token), complete: every light-set token that is not in the dark set has a pair | A2, A3, A5, A9 |
| `buttons` | `selectors`; `paint: {background, text}` (palette tokens; an unknown token fails) or `paint: selectors-only` (identified by the selectors alone, said explicitly); `max_per_view` | A11 |
| `accessibility` | axe `tags` (tags axe-core 4.14.0 knows; default wcag2a, wcag2aa, wcag21aa, wcag22aa); `default` and `tiers` per rule: `blocking` or `advisory`, each overriding the default for that rule only (defaults: html-has-lang, document-title, image-alt, button-name, link-name, label blocking; every other rule advisory) | A12 |
| `tiers` | per non-floor assertion (A2, A3, A4, A5, A7, A8, A9, A11, A13; A12's rules take their tiers in `accessibility`): `blocking`, `waivable`, `advisory`. Defaults: A3, A5, A7, A9, A13 blocking; A4, A8 waivable; A11 advisory | all |
| `decisions` | the owner's decisions the profile rests on, quoted verbatim | reports |

Font facts: `font_facts.py <font file>` prints the PostScript name, the coverage ranges and the SHA-256, read with fontTools when it can read the file, otherwise by the browser (WOFF2 without brotli included). Copy them into the face.

## 6. `waivers.yaml`

```yaml
waivers:
  - {id: w1, assertion: A4, page: reports/q3.html, selector: "main > div.banner", page_sha256: "<sha of the page>",
     reason: "...", owner_words: "the owner's words verbatim", date: "2026-11-10"}
```
Only waivable assertions; never a floor one; no bare `*`; the waiver lapses when the page changes (its SHA-256: 64 lowercase hex digits, of the bytes the checker staged). Every field is a string; `date` is `YYYY-MM-DD`; ids are unique. For A13 the selector is the snapshot entry (e.g. `heading|2|Contact`).

## 7. `ready.json`

Written only by `check_design.py --issue` (which refuses the overrides `--css`, `--tokens`, `--deploy-root`), to a new file renamed into place. Never edit it. It is a JSON object with exactly the keys `receipt_version` (1), `checker`, `issued`, `commit`, `profile` (each file: `blob` and `sha256`), `css`, `plugin_scripts`, `fonts`, no key twice, with paths relative to the site design folder. Consumers check that schema and its inventories (the folder's files, the CSS files of `site.yaml` including `component_stylesheets`, the policy's font files) before reading any file it names; then every hash; where a repository is present they also check that each profile file's bytes equal its committed bytes at `HEAD` and at the recorded commit (`git cat-file`, CRLF to LF only; a `filter`, `ident` or `working-tree-encoding` attribute on a path gives INCOMPLETE), and that `ready.json` itself is tracked at `HEAD` with its bytes equal to its committed blob: the owner commits it after `--issue` (a Git failure or `--no-git` then gives INCOMPLETE). A staged copy with no repository at all gets "approval verified at issue, not re-verifiable here" only when the consumer is given `--receipt-sha256` equal to the receipt's SHA-256 (taken where the repository is); otherwise INCOMPLETE.
