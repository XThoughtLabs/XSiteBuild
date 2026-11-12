# font_facts.py

The facts a policy face needs, read from a font file.

- **Inputs:** `<font file> [--family NAME] [--ranges 0x20-0x24F,...] [--method auto|fonttools|browser]`.
- **Method:** fontTools reads the cmap (WOFF2 needs brotli); otherwise Chromium draws each probe code point and CDP says which the font itself drew (canonical equivalents drawn by the font count, as A1 sees them).
- **Prints:** a YAML face entry with the file's SHA-256, PostScript name and coverage ranges; weight range and style are the owner's decision (a variable font's axes are printed when fontTools reads them).
