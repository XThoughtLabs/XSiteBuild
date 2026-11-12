# Third-party components

## axe-core 4.14.0 (Deque Systems), MPL-2.0

- **Files:** `scripts/vendor/axe-core/axe.min.js` (used by `check_page.py`), `scripts/vendor/axe-core/axe.js` (the same release in source form), `scripts/vendor/axe-core/LICENSE` (Mozilla Public License 2.0, full text), `scripts/vendor/axe-core/LICENSE-3RD-PARTY.txt` (axe-core's own third-party notices). Unmodified.
- **Source:** the npm package `axe-core@4.14.0` (published 2026-10-05), fetched once on 2026-11-10; tarball integrity `sha512-9WTZxEjsZ7b13TH8JPmbV2z8CHbl80/2hm3XPEG4JgNdQLK81IBRXmSxHfMAOkSqQeRxT/0dwNDz2GOm3zzpcQ==` (matches the registry). Upstream repository https://github.com/dequelabs/axe-core, tag `v4.14.0`. The source code of the covered files is `axe.js` here and the upstream repository at that tag.
- **SHA-256:** `axe.min.js` `20c09fe157a8a34a30e241aaa1fcdade657734f08ab379ecfbeb7d45cc46e878`; `axe.js` `aae0b8b36278089962105b2351ea64f4da7d3d440b54e162e21616d597aa0d6f`; `LICENSE` `af175b9d96ee93c21a036152e1b905b0b95304d4ae8c2c921c7609100ba8df7e`; `LICENSE-3RD-PARTY.txt` `4f8563870d0fca38bbc3e00b6f670cb7fa9f380ba9f26a7f7d1184a6b18b1653`. `check_page.py` checks both `.js` files against these values before every run (mismatch: ERROR) and never fetches anything at run time.
- **Run with:** Playwright for Python 1.63.0 and its Chromium 153.0.8010.12 (checked 2026-11-10). Page scripts stay blocked (Content-Security-Policy `script-src 'none'`); axe runs through Playwright's evaluation, which the policy does not block (release control, 2026-11-10).
- **Updates:** only on the owner's word: a new release is fetched once, its integrity and hashes recorded here and in `check_page.py`, and the whole suite run.

## Not shipped

- Test fonts (Poppins, Lora; SIL Open Font License) are read from the sandbox's system font folder at test time; they are not part of the package.
