"""pagejs.py — the JavaScript check_page.py evaluates in each frame through Playwright (never page scripts; plan 0.4 B.8).

None of these scripts changes the document it reads (R2-H02): no attribute, element, stylesheet node or text node is
added. An element's identity is its index in document.querySelectorAll('*') of its frame ("<frame key>:<index>"),
recomputed inside each script (the DOM does not change between them: page scripts never run, H1) and, for CDP, mapped
to CDP node ids by check_page.py. PAINTS returns every element's computed paint signature, in document order: the values
of PAINT_PROPS, the one list every comparison reads (X1), for the element and for each rendered ::before and ::after;
check_page.py reads it first, at every scroll position used, after every other evidence and in each fresh load of
another reader preference, and a difference on any element of a frame gives every text run of that frame A6
INCOMPLETE (AST-H03, HQ's V4 and C2, R2-H02, W1). BOXES returns every element's border box in page coordinates; only the
fresh loads compare it with the evidence page's first read (all are read at offset 0; scrolling moves sticky and fixed
boxes, so the other comparisons do not read it; X1). COLLECT reads computed styles, rects, own text, roles and the A13
structure. AXE_RUN runs the vendored axe-core with elementRef and maps each node's element to its index, marking whether
the element lies inside the viewport. OVERLAP checks the text rects with elementsFromPoint and, since that skips
elements with pointer-events: none, also checks the boxes of every such element (nothing is forced on). UNSEEN measures,
where each text run is evidenced, the paints hit testing never sees: the border boxes of every element with a
box-shadow, an outline, a border image or a blur() or drop-shadow() filter, and the run's own text rectangles, all in
viewport coordinates (X2, U1). INSIDE
lists the text runs whose text lies wholly inside the viewport. SCROLL moves the main frame instantly. FONTS_READY waits
for document.fonts.ready within a budget. MEDIA tells, by matchMedia, whether each emulated reader preference is in
effect in the page (W1)."""
import json

# The viewport test shared by AXE_RUN and INSIDE: an element's own text rectangles (its border box when it has no text)
# lie wholly inside the layout viewport (scrollbars excluded).
_INSIDE_FN = r"""
  const vw = Math.min(innerWidth, document.documentElement.clientWidth || innerWidth);
  const vh = Math.min(innerHeight, document.documentElement.clientHeight || innerHeight);
  const insideView = (el) => {
    const rs = [];
    for (const n of el.childNodes) {
      if (n.nodeType === 3 && n.textContent.trim()) {
        const rg = document.createRange(); rg.selectNodeContents(n);
        for (const q of rg.getClientRects()) if (q.width > 0 && q.height > 0) rs.push(q);
      }
    }
    if (!rs.length) { const b = el.getBoundingClientRect(); if (b.width > 0 && b.height > 0) rs.push(b); }
    return rs.length > 0 && rs.every((q) => q.left >= 0 && q.top >= 0 && q.right <= vw && q.bottom <= vh);
  };
"""

# The paint properties every comparison of paints reads (X1): before and after the evidence, at each scroll offset, and
# in each fresh load of another reader preference. A property missing here is a change no comparison can see (HQ's
# contrast_shadow: an inset box-shadow drawn only for readers who asked for more contrast).
PAINT_PROPS = (
    'color', 'background-color', 'background-image', '-webkit-text-fill-color', '-webkit-text-stroke-color',
    '-webkit-text-stroke-width', 'text-shadow', 'opacity', 'visibility', 'display', 'font-family', 'font-size',
    'font-weight', 'font-style', 'fill', 'stroke', 'filter', 'backdrop-filter', 'mix-blend-mode', 'mask-image',
    'clip-path', 'position', 'z-index', 'transform', 'text-decoration-color',
    'top', 'right', 'bottom', 'left', 'margin-top', 'margin-right', 'margin-bottom', 'margin-left',   # a moved layer (C2)
    'scale', 'rotate', 'translate', 'clip', 'zoom', 'content-visibility',   # individual transforms, legacy clip (R2-H02)
    # X1: the paints the list lacked before (shadows, borders, outlines, background geometry, box sizes, decorations)
    'box-shadow',
    'border-top-color', 'border-right-color', 'border-bottom-color', 'border-left-color',
    'border-top-width', 'border-right-width', 'border-bottom-width', 'border-left-width',
    'border-top-style', 'border-right-style', 'border-bottom-style', 'border-left-style',
    'border-top-left-radius', 'border-top-right-radius', 'border-bottom-right-radius', 'border-bottom-left-radius',
    'outline-color', 'outline-width', 'outline-style', 'outline-offset',
    'background-size', 'background-position', 'background-repeat', 'background-clip', 'background-origin',
    'background-attachment', 'background-blend-mode',
    'padding-top', 'padding-right', 'padding-bottom', 'padding-left', 'width', 'height',
    'border-image-source', 'border-image-slice', 'border-image-width', 'border-image-outset', 'border-image-repeat',
    '-webkit-box-reflect', 'accent-color', 'color-scheme',
    'text-decoration-line', 'text-decoration-style', 'text-decoration-thickness',
    'mask-size', 'mask-position', 'mask-repeat', 'overflow-x', 'overflow-y', 'offset-path',
    'stroke-width', 'fill-opacity', 'stroke-opacity',
)

# Every element's signature: the PAINT_PROPS values, then for ::before and ::after their content and, when the
# pseudo-element is rendered (content other than none and normal), the PAINT_PROPS values of the pseudo-element.
PAINTS = r"""
() => {
  const props = """ + json.dumps(list(PAINT_PROPS)) + r""";
  return Array.from(document.querySelectorAll('*')).map((el) => {
    const cs = getComputedStyle(el); const o = [];
    for (const p of props) o.push(cs.getPropertyValue(p));
    for (const ps of ['::before', '::after']) {
      const pc = getComputedStyle(el, ps); const c = pc.getPropertyValue('content');
      o.push(c);
      if (c && c !== 'none' && c !== 'normal') for (const p of props) o.push(pc.getPropertyValue(p));
    }
    return o.join('|');
  });
}
"""

# Every element's border box in page coordinates, in document order, read at offset 0 in the evidence page and in each
# fresh load (X1): a box that moves or changes size only for some reader preference changes what that reader sees.
BOXES = r"""
() => Array.from(document.querySelectorAll('*')).map((el) => {
  const q = el.getBoundingClientRect();
  return [q.left + window.scrollX, q.top + window.scrollY, q.width, q.height].join(',');
})
"""

# X2: at the scroll position where the runs args.ids are evidenced, the border boxes (viewport coordinates) of every
# element whose box-shadow, outline or border image hit testing never sees, or whose blur() or drop-shadow() filter
# paints beyond what it filters (U1), which of those elements has a running or pending animation (U1, U2), and each
# run's own text rectangles. Which of those paints reach a run is computed by check_page.py; an element it expects and
# finds no box for is unmeasured.
UNSEEN = r"""
(args) => {
  const all = Array.from(document.querySelectorAll('*'));
  const box = (q) => [q.left, q.top, q.width, q.height];
  const out = {boxes: {}, runs: {}, animated: []};
  all.forEach((el, i) => {
    const cs = getComputedStyle(el);
    const shadow = !!cs.boxShadow && cs.boxShadow !== 'none';
    const outline = !!cs.outlineStyle && cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0;
    const image = !!cs.borderImageSource && cs.borderImageSource !== 'none';
    const spread = /blur\(|drop-shadow\(/.test(cs.filter || '');      // U1: a filter that paints beyond its input
    if (shadow || outline || image || spread) {
      out.boxes[args.frame + ':' + i] = box(el.getBoundingClientRect());
      // U1, U2: a painter with a running or pending animation or transition (a delayed one included) may paint
      // otherwise after the check; an element that cannot tell counts as animated
      let n = 1;
      try { n = el.getAnimations().length; } catch (e) {}
      if (n > 0) out.animated.push(args.frame + ':' + i);
    }
  });
  for (const id of args.ids) {
    const el = all[parseInt(id.split(':')[1], 10)];
    const rs = [];
    if (el) {
      for (const n of el.childNodes) {
        if (n.nodeType === 3 && n.textContent.trim()) {
          const rg = document.createRange(); rg.selectNodeContents(n);
          for (const q of rg.getClientRects()) if (q.width > 0 && q.height > 0) rs.push(box(q));
        }
      }
    }
    out.runs[id] = rs;
  }
  return out;
}
"""

COLLECT = r"""
(args) => {
  const props = ['color','background-color','background-image','border-top-color','border-right-color',
    'border-bottom-color','border-left-color','border-top-width','border-right-width','border-bottom-width',
    'border-left-width','border-top-style','border-right-style','border-bottom-style','border-left-style',
    'outline-color','outline-style','outline-width','box-shadow','fill','stroke','stroke-width','font-family',
    'font-size','font-weight','font-style','text-transform','opacity','padding-left','padding-right',
    'visibility','display','mix-blend-mode','filter','backdrop-filter','mask-image','clip-path','position',
    'content','width','height','color-scheme','-webkit-text-fill-color','-webkit-text-stroke-color',
    '-webkit-text-stroke-width','text-decoration-line','text-decoration-color','text-shadow','stop-color',
    'stop-opacity','box-sizing','fill-opacity','stroke-opacity',
    // X2: what the reach of a paint hit testing cannot see is computed from (radii, outline offset, border image,
    // reflection) and the transforms that make it not computable
    'border-top-left-radius','border-top-right-radius','border-bottom-right-radius','border-bottom-left-radius',
    'outline-offset','border-image-source','border-image-outset','-webkit-box-reflect',
    'transform','scale','rotate','translate','zoom','offset-path',
    // U2: a negative stacking layer between a shadow's painter and the text is painted beneath that shadow
    'z-index'];
  const pick = (cs) => { const o = {}; for (const p of props) o[p] = cs.getPropertyValue(p); return o; };
  const sel = args.selectors || {};
  const matches = (el, list) => { const r = []; for (const s of (list || [])) { try { if (el.matches(s)) r.push(s); } catch (e) {} } return r; };
  const all = Array.from(document.querySelectorAll('*'));
  const idOf = new Map();
  all.forEach((el, i) => { idOf.set(el, args.frame + ':' + i); });   // identity by index, never written into the DOM (R2-H02)
  const num = (v) => parseFloat(v) || 0;
  // layout sizes, untransformed and unrounded (AST-M13): the content width for A7, the border box for A4
  const contentWidth = (el, cs) => {
    const pad = num(cs.paddingLeft) + num(cs.paddingRight), bord = num(cs.borderLeftWidth) + num(cs.borderRightWidth);
    if (cs.display !== 'inline' && cs.display !== 'contents' && /px$/.test(cs.width)) {
      const w = parseFloat(cs.width);
      return cs.boxSizing === 'border-box' ? w - pad - bord : w;
    }
    return el.clientWidth ? el.clientWidth - pad : null;
  };
  const layoutBox = (el, cs) => {
    if (cs.display !== 'inline' && cs.display !== 'contents' && /px$/.test(cs.width) && /px$/.test(cs.height)) {
      const extraW = cs.boxSizing === 'border-box' ? 0 : num(cs.paddingLeft) + num(cs.paddingRight) + num(cs.borderLeftWidth) + num(cs.borderRightWidth);
      const extraH = cs.boxSizing === 'border-box' ? 0 : num(cs.paddingTop) + num(cs.paddingBottom) + num(cs.borderTopWidth) + num(cs.borderBottomWidth);
      return [parseFloat(cs.width) + extraW, parseFloat(cs.height) + extraH];
    }
    return (el instanceof HTMLElement) ? [el.offsetWidth, el.offsetHeight] : null;
  };
  const path = (el) => {
    const parts = []; let e = el;
    while (e && e.nodeType === 1 && parts.length < 14) {
      let s = e.tagName.toLowerCase();
      if (e.id) { parts.unshift(s + '#' + e.id); break; }
      const p = e.parentElement;
      if (p) { const same = Array.from(p.children).filter(c => c.tagName === e.tagName); if (same.length > 1) s += ':nth-of-type(' + (same.indexOf(e) + 1) + ')'; }
      parts.unshift(s); e = p;
    }
    return parts.join(' > ');
  };
  const sx = window.scrollX, sy = window.scrollY;
  const opCache = new Map();
  const effOp = (el) => {
    if (!el || el.nodeType !== 1) return 1;
    if (opCache.has(el)) return opCache.get(el);
    const v = parseFloat(getComputedStyle(el).opacity) * effOp(el.parentElement);
    opCache.set(el, v); return v;
  };
  // drawn text counts by its own rectangles too: an element with display: contents has no box but draws text (AST-H04)
  const visible = (el, cs, r, rects) => ((r.width > 0 && r.height > 0) || (rects && rects.length > 0))
    && cs.visibility !== 'hidden' && cs.display !== 'none' && effOp(el) > 0;
  const out = {url: location.href, title: document.title, lang: document.documentElement.getAttribute('lang') || '',
    height: Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0),
    width: document.documentElement.scrollWidth, elements: [], structure: [], objects: document.querySelectorAll('object,embed').length,
    shadow_hosts: [], media: {img: document.querySelectorAll('img').length, canvas: document.querySelectorAll('canvas').length,
    video: document.querySelectorAll('video').length},
    // the ids of the document's gradient paint servers: a url(#id) paint naming none of them is not checked (R2-H05)
    paint_servers: all.filter((x) => (x.localName === 'linearGradient' || x.localName === 'radialGradient') && x.id).map((x) => x.id)};
  for (const el of all) {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    let own = ''; const rects = [];
    for (const n of el.childNodes) {
      if (n.nodeType === 3 && n.textContent.trim()) {
        own += n.textContent;
        const rg = document.createRange(); rg.selectNodeContents(n);
        for (const q of rg.getClientRects()) if (q.width > 0 && q.height > 0) rects.push([q.left + sx, q.top + sy, q.width, q.height]);
      }
    }
    const tag = el.tagName.toLowerCase();
    const info = {id: idOf.get(el), tag: tag, path: path(el), rect: [r.left + sx, r.top + sy, r.width, r.height],
      content_width: contentWidth(el, cs), layout: layoutBox(el, cs),
      style: pick(cs), opacity: effOp(el), visible: visible(el, cs, r, rects),
      text: own.replace(/\s+/g, ' ').trim(), text_rects: rects,
      parent: el.parentElement ? idOf.get(el.parentElement) : null, svg: el instanceof SVGElement,
      role: el.getAttribute('role') || '',
      heading: /^h[1-6]$/.test(tag) || el.getAttribute('role') === 'heading' || matches(el, sel.headings).length > 0,
      label: matches(el, sel.labels).length > 0, code: !!el.closest('code,pre,kbd,samp'),
      measure: matches(el, (sel.measure || []).map(m => m.selector)), button_sel: matches(el, sel.buttons).length > 0,
      in_noscript: !!el.closest('noscript'), pseudo: {}, textpseudo: {}};
    for (const ps of ['::before', '::after']) {
      const pc = getComputedStyle(el, ps); const c = pc.getPropertyValue('content');
      if (c && c !== 'none' && c !== 'normal') info.pseudo[ps] = pick(pc);
    }
    const blockish = ['block', 'list-item', 'inline-block', 'flow-root', 'table-cell', 'table-caption'].includes(cs.display);
    if (own && blockish) {   // ::first-line and ::first-letter repaint a block container's own text
      for (const ps of ['::first-line', '::first-letter']) {
        const pc = getComputedStyle(el, ps);
        const o = {color: pc.color, 'background-color': pc.backgroundColor, '-webkit-text-fill-color': pc.getPropertyValue('-webkit-text-fill-color'),
                   'font-family': pc.fontFamily, 'text-shadow': pc.textShadow};
        const bgSet = o['background-color'] !== 'rgba(0, 0, 0, 0)' && o['background-color'] !== cs.backgroundColor;
        if (o.color !== cs.color || bgSet || o['font-family'] !== cs.fontFamily
            || o['-webkit-text-fill-color'] !== cs.getPropertyValue('-webkit-text-fill-color') || o['text-shadow'] !== cs.textShadow) info.textpseudo[ps] = o;
      }
    }
    if (el.shadowRoot) out.shadow_hosts.push(path(el));
    out.elements.push(info);
  }
  const vis = (el) => { const cs = getComputedStyle(el); return visible(el, cs, el.getBoundingClientRect()); };
  const txt = (el) => (el.textContent || '').replace(/\s+/g, ' ').trim();
  const push = (el, entry) => out.structure.push({entry: entry, visible: vis(el), id: idOf.get(el)});
  const abs = (v) => { try { return new URL(String(v), document.baseURI).href; } catch (e) { return String(v); } };
  const rel = (u) => { u = String(u || ''); return u.startsWith(location.origin) ? u.slice(location.origin.length) : u; };   // no random port
  const hrefOf = (a) => abs(a.getAttribute('href') ?? a.getAttribute('xlink:href') ?? '');
  for (const a of document.querySelectorAll('a[href], a[*|href]')) push(a, 'link|' + rel(hrefOf(a)) + '|' + txt(a));
  // a form's fields by form ownership (AST-M16, R2-M09): every listed element (input, button, select, textarea, output,
  // fieldset, object) is credited once, to its owner: the form its form property names (read through the prototype, so
  // nothing on the element can clobber it), whether inside that form's subtree or not, <input type="image"> included;
  // a listed element with no owner is listed as such
  const formOf = (x) => {
    for (let p = Object.getPrototypeOf(x); p; p = Object.getPrototypeOf(p)) {
      const d = Object.getOwnPropertyDescriptor(p, 'form');
      if (d && d.get) { try { return d.get.call(x); } catch (e) { return null; } }
    }
    return null;
  };
  const actionOf = (f) => (f.getAttribute('action') === null ? '' : rel(abs(f.getAttribute('action'))));
  const fieldOf = (x) => (x.getAttribute('name') || '') + '|' + (x.getAttribute('type') || x.tagName.toLowerCase());
  for (const f of document.querySelectorAll('form')) push(f, 'form|' + actionOf(f) + '|' + (f.getAttribute('method') || 'get').toLowerCase());
  for (const x of document.querySelectorAll('input,button,select,textarea,output,fieldset,object')) {
    const owner = formOf(x);
    push(x, owner ? 'field|' + actionOf(owner) + '|' + fieldOf(x) : 'field-unowned|' + fieldOf(x));
  }
  for (const b of document.querySelectorAll('button')) push(b, 'button|' + txt(b));
  for (const s of document.querySelectorAll('summary')) push(s, 'summary|' + txt(s));
  for (const s of document.querySelectorAll('select')) push(s, 'select|' + (s.getAttribute('name') || ''));
  for (const s of document.querySelectorAll('textarea')) push(s, 'textarea|' + (s.getAttribute('name') || ''));
  for (const s of document.querySelectorAll('[role=button]')) push(s, 'role-button|' + txt(s));
  for (const el of all) for (const at of el.getAttributeNames()) if (/^on/i.test(at)) push(el, 'handler|' + el.tagName.toLowerCase() + '|' + at.toLowerCase() + '=' + el.getAttribute(at));
  for (const h of document.querySelectorAll('h1,h2,h3,h4,h5,h6')) push(h, 'heading|' + h.tagName[1] + '|' + txt(h));
  const lm = {header: 'banner', nav: 'navigation', main: 'main', footer: 'contentinfo', aside: 'complementary'};
  for (const el of document.querySelectorAll('header,nav,main,footer,aside,[role=banner],[role=navigation],[role=main],[role=contentinfo],[role=complementary],[role=region],[role=search]')) {
    push(el, 'landmark|' + (el.getAttribute('role') || lm[el.tagName.toLowerCase()]) + '|' + (el.getAttribute('aria-label') || ''));
  }
  return out;
}
"""

FONTS_READY = r"""
(ms) => Promise.race([document.fonts.ready.then(() => 'ready'), new Promise(r => setTimeout(() => r('timeout'), ms))])
"""

# [[feature, value], ...] -> [true|false, ...]: whether '(feature: value)' matches in this document (W1); a feature the
# browser does not know never matches, so an emulation that did not take effect is never taken as evidence.
MEDIA = r"""
(feats) => feats.map(([f, v]) => window.matchMedia('(' + f + ': ' + v + ')').matches)
"""

AXE_RUN = r"""
async (args) => {
  if (typeof axe === 'undefined') return {error: 'axe not loaded'};
  const options = Object.assign({}, args.options, {elementRef: true});   // each node's element, no DOM marker (R2-H02)
  const res = await axe.run(document, options);
  const idOf = new Map();
  Array.from(document.querySelectorAll('*')).forEach((el, i) => idOf.set(el, args.frame + ':' + i));
""" + _INSIDE_FN + r"""
  const map = (nodes) => nodes.map(n => {
    const el = n.element || null;
    const chk = (n.any && n.any[0]) || (n.all && n.all[0]) || (n.none && n.none[0]) || {};
    return {id: el && idOf.has(el) ? idOf.get(el) : null, target: n.target, data: chk.data || null,
            message: chk.message || '', impact: n.impact, inside: el ? insideView(el) : false};
  });
  const pack = (list) => list.map(r => ({id: r.id, impact: r.impact, tags: r.tags, nodes: map(r.nodes)}));
  return {version: axe.version, passes: pack(res.passes), violations: pack(res.violations),
          incomplete: pack(res.incomplete), inapplicable: res.inapplicable.map(r => r.id)};
}
"""

# The rules axe-core runs for these tags (R2-M08): axe.getRules(tags) less the rules carrying a tag axe excludes by
# default (experimental, deprecated) unless that tag is selected, as axe's own ruleShouldRun decides for a tag run.
AXE_RULES = r"""
(tags) => {
  if (typeof axe === 'undefined') return null;
  const ex = (axe._audit && axe._audit.tagExclude) || [];
  return axe.getRules(tags).filter((r) => !r.tags.some((t) => ex.includes(t) && !tags.includes(t))).map((r) => r.ruleId);
}
"""

INSIDE = r"""
(args) => {
  const all = Array.from(document.querySelectorAll('*'));
""" + _INSIDE_FN + r"""
  const out = [];
  for (const id of args.ids) {
    const el = all[parseInt(id.split(':')[1], 10)];
    if (el && insideView(el)) out.push(id);
  }
  return out;
}
"""

SCROLL = r"""
async (y) => {
  window.scrollTo({top: y, left: 0, behavior: 'instant'});   // instant: a smooth-scrolling page is never mid-way
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));   // scroll-driven styles update
  return [window.scrollX, window.scrollY];
}
"""

OVERLAP = r"""
(args) => {
  const all = Array.from(document.querySelectorAll('*'));
  const idOf = new Map();
  all.forEach((el, i) => idOf.set(el, args.frame + ':' + i));
  const name = (s) => idOf.get(s) || s.tagName;
  // elementsFromPoint skips elements with pointer-events: none; nothing is forced on (R2-H02): such an element whose
  // box holds the point counts as overlapping unless it is the text's element, one of its ancestors, or a descendant
  // that paints nothing
  const peNone = [];
  for (const s of all) {
    const cs = getComputedStyle(s);
    if (cs.pointerEvents === 'none' && cs.visibility !== 'hidden' && cs.display !== 'none') {
      const rs = Array.from(s.getClientRects()).filter((q) => q.width > 0 && q.height > 0);
      if (rs.length) peNone.push([s, rs]);
    }
  }
  // a descendant of the text's element at the text's point overlaps only when it paints (a background, border, box
  // shadow or image of its own, or a replaced element); plain inline children do not (AUD-F01(1))
  const REPLACED = new Set(['img', 'video', 'canvas', 'iframe', 'object', 'embed', 'svg', 'input', 'textarea', 'select', 'meter', 'progress']);
  const paints = (s) => {
    if (REPLACED.has((s.localName || '').toLowerCase())) return true;
    const cs = getComputedStyle(s);
    if (cs.backgroundColor && cs.backgroundColor !== 'transparent' && !/,\s*0\)$/.test(cs.backgroundColor)) return true;
    if (cs.backgroundImage && cs.backgroundImage !== 'none') return true;
    if (cs.boxShadow && cs.boxShadow !== 'none') return true;
    for (const side of ['Top', 'Right', 'Bottom', 'Left']) {
      if (parseFloat(cs['border' + side + 'Width']) > 0 && !['none', 'hidden'].includes(cs['border' + side + 'Style'])) return true;
    }
    return false;
  };
  const out = {};
  for (const id of args.ids) {
    const el = all[parseInt(id.split(':')[1], 10)];
    if (!el) continue;
    const res = [];
    for (const n of el.childNodes) {
      if (n.nodeType !== 3 || !n.textContent.trim()) continue;
      const rg = document.createRange(); rg.selectNodeContents(n);
      for (const q of rg.getClientRects()) {
        if (q.width <= 0 || q.height <= 0) continue;
        const pts = [[q.left + q.width / 2, q.top + q.height / 2], [q.left + 1, q.top + 1], [q.right - 1, q.top + 1],
                     [q.left + 1, q.bottom - 1], [q.right - 1, q.bottom - 1]];
        for (const [x, y] of pts) {
          if (y < 0 || y >= innerHeight || x < 0 || x >= innerWidth) { res.push('offscreen'); continue; }
          let verdict = 'none';
          for (const s of document.elementsFromPoint(x, y)) {
            if (s === el) continue;
            if (el.contains(s)) {
              if (paints(s)) { verdict = 'overlap:' + name(s); break; }
              continue;
            }
            if (s.contains(el)) { verdict = 'ok'; break; }
            verdict = 'overlap:' + name(s); break;
          }
          if (!verdict.startsWith('overlap')) {
            for (const [s, rs] of peNone) {
              if (s === el || s.contains(el) || (el.contains(s) && !paints(s))) continue;
              if (rs.some((q2) => x >= q2.left && x < q2.right && y >= q2.top && y < q2.bottom)) { verdict = 'overlap:' + name(s) + ' (pointer-events: none)'; break; }
            }
          }
          res.push(verdict);
        }
      }
    }
    out[id] = res;
  }
  return out;
}
"""
