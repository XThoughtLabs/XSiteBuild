# inventory_css.py

The deterministic inventory that seeds a CSS-first profile (plan 0.4 B.3.2).

- **Inputs:** `<css> [...] [--json FILE]`.
- **Lists:** `:root` custom properties; the declarations of the properties named in the script's `PROPS` (colours, fonts, sizes, weights, line heights, letter spacing, radii, shadows, spacing: the shorthands and the common longhands such as `border-top-color`, `padding-left`, `text-shadow`), with file, line, selectors and media conditions; `@font-face`, `@keyframes` (whole), non-binding at-rules; unsupported at-rules (exit 3). Properties outside `PROPS` are not listed.
