# XSiteBuild

A Claude Code plugin marketplace from XThoughtLabs. It holds one plugin: **site-design-system** 0.1.0.

## site-design-system

A website's design system, kept so that agents can work in it. The plugin starts a design system for a new site, or derives one from an existing site's CSS. It keeps the system in agreement with that CSS, and it builds and checks pages, dashboard panels, report pages and images against it.

Each site keeps its own private **site design folder**: `DESIGN.md`, a trace map, contrast and policy files, waivers, and a `ready.json` receipt. The checkers:

- trace every token in `DESIGN.md` to its declaration in the CSS;
- check token contrast and the site's policy;
- treat the owner's Git commit as the approval of a profile;
- render pages in a contained Chromium with axe-core.

The plugin holds method only. No site's names, colours, fonts or paths are built into its scripts or skills.

Skills:

| Skill | Use when |
|---|---|
| `starting-a-site-design-system` | a new site with no CSS yet |
| `keeping-a-site-design-system` | the CSS or `DESIGN.md` changes; documenting or auditing a site; adding a token or component; the receipt is missing or stale |
| `building-in-a-site-design-system` | an agent makes or changes a page for a site that has a design folder |

## Requirements

- Python 3.10+ and PyYAML, for every script. On Windows, install PyYAML for the Python that runs the scripts, without `--user` (`py -3 -m pip install PyYAML`): the scripts run with `-I`, which ignores the user site-packages.
- Playwright for Python and its Chromium, for `check_page.py` and the browser method of `font_facts.py`.
- fontTools, optional, for `font_facts.py`. WOFF2 files also need brotli.
- Git: the owner's commits approve a profile and its receipt.

A missing dependency gives an ERROR that names it. Nothing installs itself.

## Install

In a terminal:

```
claude plugin marketplace add XThoughtLabs/XSiteBuild
claude plugin install site-design-system@xsitebuild
```

In a Claude Code session:

```
/plugin marketplace add XThoughtLabs/XSiteBuild
/plugin install site-design-system@xsitebuild
```

In one step (Claude Code 2.1.275 or later):

```
/plugin install site-design-system --marketplace XThoughtLabs/XSiteBuild
```

## Read more

[`plugins/site-design-system/README.md`](plugins/site-design-system/README.md) covers the skills, the scripts, the site design folder and its trust model, and the limits. Each script's documentation is in [`plugins/site-design-system/scripts/docs/`](plugins/site-design-system/scripts/docs/).

## Licences

- The plugin: Apache License 2.0, see [`LICENSE`](LICENSE).
- The vendored axe-core 4.14.0 (Deque Systems), in `plugins/site-design-system/scripts/vendor/axe-core/`: Mozilla Public License 2.0. See [`plugins/site-design-system/THIRD-PARTY.md`](plugins/site-design-system/THIRD-PARTY.md) and [`plugins/site-design-system/scripts/vendor/axe-core/LICENSE`](plugins/site-design-system/scripts/vendor/axe-core/LICENSE).
