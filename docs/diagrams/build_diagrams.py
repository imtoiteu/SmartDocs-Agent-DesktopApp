#!/usr/bin/env python3
"""
Generator for SmartDocs-Agent architecture diagrams.

Single source of layout -> emits BOTH:
  * <name>.drawio  (editable mxGraph source: real containers/swimlanes/grouped cells)
  * <name>.svg      (publication-ready fallback render)

This is a bespoke redesign of the diagrams in docs/ARCHITECTURE-DIAGRAMS.md
(grounded in docs/ARCHITECTURE.md) — NOT a Mermaid auto-conversion.

If the Draw.io desktop CLI is available, export_svgs.sh re-exports authoritative
SVGs from the .drawio files; this generator's SVG is the offline fallback.
"""
import os, math, html

OUT = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- palette
P = {
    'fe':    ('#DAE8FC', '#6C8EBF'),  # frontend  - blue
    'be':    ('#D4E1F5', '#3F61A8'),  # backend   - indigo
    'ocr':   ('#B0E3E6', '#0E8088'),  # ocr       - teal
    'ai':    ('#FFE6CC', '#D79B00'),  # ai svc    - orange
    'rag':   ('#D5E8D4', '#82B366'),  # rag       - green
    'agent': ('#E1D5E7', '#9673A6'),  # agent     - purple
    'llm':   ('#FFF2CC', '#D6B656'),  # providers - yellow
    'db':    ('#EDEDED', '#5A5A5A'),  # database  - gray
    'sec':   ('#F8CECC', '#B85450'),  # security  - red
    'ext':   ('#F5F5F5', '#999999'),  # external  - light gray
    'note':  ('#FFF2CC', '#D6B656'),
}

def tint(hx, t):
    r = int(hx[1:3], 16); g = int(hx[3:5], 16); b = int(hx[5:7], 16)
    r = int(r + (255 - r) * t); g = int(g + (255 - g) * t); b = int(b + (255 - b) * t)
    return '#%02X%02X%02X' % (r, g, b)

def esc(s):
    return html.escape(str(s), quote=True)

# ---------------------------------------------------------------- model
class Diagram:
    def __init__(self, name, title, w, h):
        self.name = name; self.title = title; self.w = w; self.h = h
        self.containers = []   # dict: id,x,y,w,h,title,fill,stroke,header,bodyfill,kind
        self.nodes = []        # dict: id,x,y,w,h,label,fill,stroke,shape,parent,fontsize,bold,fontcolor
        self.tables = []       # dict: id,x,y,w,title,rows,fill,stroke,rowh,header
        self.edges = []        # dict: src,dst,label,dashed,color,waypoints,srcside,dstside,arrow
        self.lifelines = []    # sequence: id,x,label,fill,stroke,hy,hh,hw,bottom
        self.messages = []     # sequence: frm,to,y,label,dashed,color,kind
        self.fragments = []    # sequence: x1,x2,y1,y2,label
        self.byid = {}
        self._llx = {}

    def container(self, id, x, y, w, h, title, key, header=34):
        fill, stroke = P[key]
        c = dict(id=id, x=x, y=y, w=w, h=h, title=title, fill=fill, stroke=stroke,
                 header=header, bodyfill=tint(fill, 0.62), kind='container')
        self.containers.append(c); self.byid[id] = c; return c

    def node(self, id, x, y, w, h, label, key, shape='round', parent=None,
             fontsize=12.5, bold=False, fontcolor='#15202B'):
        fill, stroke = P[key]
        n = dict(id=id, x=x, y=y, w=w, h=h, label=label, fill=fill, stroke=stroke,
                 shape=shape, parent=parent, fontsize=fontsize, bold=bold,
                 fontcolor=fontcolor, kind='node')
        self.nodes.append(n); self.byid[id] = n; return n

    def table(self, id, x, y, w, title, rows, key, rowh=21, header=28):
        fill, stroke = P[key]
        h = header + rowh * len(rows) + 6
        t = dict(id=id, x=x, y=y, w=w, h=h, title=title, rows=rows, fill=fill,
                 stroke=stroke, rowh=rowh, header=header, kind='table')
        self.tables.append(t); self.byid[id] = t; return t

    def edge(self, src, dst, label='', dashed=False, color='#445', waypoints=None,
             srcside=None, dstside=None, arrow='end'):
        self.edges.append(dict(src=src, dst=dst, label=label, dashed=dashed, color=color,
                               waypoints=waypoints or [], srcside=srcside, dstside=dstside,
                               arrow=arrow))

    # ---- sequence-diagram primitives (UML) ----
    def lifeline(self, id, x, label, key, hy=66, hh=46, hw=160, bottom=None):
        fill, stroke = P[key]
        self.lifelines.append(dict(id=id, x=x, label=label, fill=fill, stroke=stroke,
                                   hy=hy, hh=hh, hw=hw, bottom=bottom))
        self._llx[id] = x
        self.byid[id] = dict(x=x - hw / 2, y=hy, w=hw, h=hh)
        return id

    def message(self, frm, to, y, label='', dashed=False, color='#33475B', kind='call'):
        self.messages.append(dict(frm=frm, to=to, y=y, label=label, dashed=dashed,
                                  color=color, kind=kind))

    def fragment(self, x1, y1, x2, y2, label):
        self.fragments.append(dict(x1=x1, y1=y1, x2=x2, y2=y2, label=label))

# ---------------------------------------------------------------- geometry
def cell_rect(c):
    return c['x'], c['y'], c['w'], c['h']

def side_point(c, side, frac=0.5):
    x, y, w, h = cell_rect(c)
    if side == 'top':    return x + w * frac, y
    if side == 'bottom': return x + w * frac, y + h
    if side == 'left':   return x, y + h * frac
    if side == 'right':  return x + w, y + h * frac
    return x + w / 2, y + h / 2

def border_toward(c, px, py):
    x, y, w, h = cell_rect(c)
    cx, cy = x + w / 2, y + h / 2
    dx, dy = px - cx, py - cy
    if dx == 0 and dy == 0: return cx, cy
    sx = (w / 2) / abs(dx) if dx else 1e9
    sy = (h / 2) / abs(dy) if dy else 1e9
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s

def poly_midpoint(pts):
    if len(pts) == 1: return pts[0]
    seg = []; total = 0
    for i in range(len(pts) - 1):
        d = math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1])
        seg.append(d); total += d
    half = total / 2; acc = 0
    for i, d in enumerate(seg):
        if acc + d >= half:
            t = (half - acc) / d if d else 0
            return (pts[i][0] + (pts[i+1][0]-pts[i][0]) * t,
                    pts[i][1] + (pts[i+1][1]-pts[i][1]) * t)
        acc += d
    return pts[-1]

def edge_points(d, e):
    s = d.byid[e['src']]; t = d.byid[e['dst']]
    wps = e['waypoints']
    # start
    if e['srcside']:
        sp = side_point(s, e['srcside'])
    else:
        aim = wps[0] if wps else (t['x'] + t['w'] / 2, t['y'] + t['h'] / 2)
        sp = border_toward(s, aim[0], aim[1])
    # end
    if e['dstside']:
        ep = side_point(t, e['dstside'])
    else:
        aim = wps[-1] if wps else (s['x'] + s['w'] / 2, s['y'] + s['h'] / 2)
        ep = border_toward(t, aim[0], aim[1])
    return [sp] + list(wps) + [ep]

def wrap_text(label, w, fontsize):
    maxchars = max(6, int((w - 14) / (fontsize * 0.55)))
    lines = []
    for part in str(label).split('\n'):
        words = part.split(' '); cur = ''
        for wd in words:
            if cur == '': cur = wd
            elif len(cur) + 1 + len(wd) <= maxchars: cur += ' ' + wd
            else: lines.append(cur); cur = wd
        lines.append(cur)
    return lines

# ---------------------------------------------------------------- SVG render
def render_svg(d):
    out = []
    out.append('<?xml version="1.0" encoding="UTF-8"?>')
    out.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
               'viewBox="0 0 %d %d" font-family="Helvetica, Arial, sans-serif">'
               % (d.w, d.h, d.w, d.h))
    # markers
    colors = sorted({e['color'] for e in d.edges} | {m['color'] for m in d.messages} | {'#445'})
    out.append('<defs>')
    for col in colors:
        mid = 'arr_' + col.replace('#', '')
        out.append('<marker id="%s" markerWidth="11" markerHeight="11" refX="8.5" refY="3.2" '
                   'orient="auto" markerUnits="userSpaceOnUse">'
                   '<path d="M0,0 L9,3.2 L0,6.4 Z" fill="%s"/></marker>' % (mid, col))
    out.append('</defs>')
    out.append('<rect x="0" y="0" width="%d" height="%d" fill="#FFFFFF"/>' % (d.w, d.h))
    # title
    out.append('<text x="%d" y="40" font-size="22" font-weight="700" fill="#10202E">%s</text>'
               % (40, esc(d.title)))
    out.append('<line x1="40" y1="50" x2="%d" y2="50" stroke="#10202E" stroke-width="1.5"/>'
               % (d.w - 40))

    # sequence: fragments (back)
    for fr in d.fragments:
        x1, y1, x2, y2 = fr['x1'], fr['y1'], fr['x2'], fr['y2']
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="none" '
                   'stroke="#5B6B7B" stroke-width="1.3"/>' % (x1, y1, x2 - x1, y2 - y1))
        tw = 22 + len(fr['label']) * 5.6
        out.append('<path d="M%.1f,%.1f h%.1f l-8,9 h-%.1f z" fill="#E8EEF5" stroke="#5B6B7B" '
                   'stroke-width="1.0"/>' % (x1, y1, tw, tw - 8))
        out.append('<text x="%.1f" y="%.1f" font-size="10.5" font-weight="700" fill="#243B4A">%s</text>'
                   % (x1 + 6, y1 + 13, esc(fr['label'])))

    # sequence: lifelines
    for ll in d.lifelines:
        x, hw, hy, hh = ll['x'], ll['hw'], ll['hy'], ll['hh']
        bot = ll['bottom'] if ll['bottom'] else d.h - 30
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.3" '
                   'stroke-dasharray="5 5"/>' % (x, hy + hh, x, bot, ll['stroke']))
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="9" fill="%s" stroke="%s" '
                   'stroke-width="1.6"/>' % (x - hw / 2, hy, hw, hh, ll['fill'], ll['stroke']))
        llines = wrap_text(ll['label'], hw, 12)
        lh = 12 * 1.2; y0 = hy + hh / 2 - (len(llines) * lh) / 2 + 12 * 0.9
        for i, ln in enumerate(llines):
            out.append('<text x="%.1f" y="%.1f" font-size="12" font-weight="700" fill="#15202B" '
                       'text-anchor="middle">%s</text>' % (x, y0 + i * lh, esc(ln)))

    # sequence: messages (front)
    for m in d.messages:
        mk = 'arr_' + m['color'].replace('#', '')
        dash = ' stroke-dasharray="6 4"' if m['dashed'] else ''
        if m['kind'] == 'self':
            x = d._llx[m['frm']]; y = m['y']
            out.append('<path d="M%.1f,%.1f h26 v18 h-26" fill="none" stroke="%s" stroke-width="1.6"%s '
                       'marker-end="url(#%s)"/>' % (x, y, m['color'], dash, mk))
            for i, ln in enumerate(wrap_text(m['label'], 260, 10)):
                out.append('<text x="%.1f" y="%.1f" font-size="10.5" fill="#243B4A">%s</text>'
                           % (x + 34, y + 1 + i * 12, esc(ln)))
        else:
            x1 = d._llx[m['frm']]; x2 = d._llx[m['to']]; y = m['y']
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.6"%s '
                       'marker-end="url(#%s)"/>' % (x1, y, x2, y, m['color'], dash, mk))
            lx = (x1 + x2) / 2
            mlines = wrap_text(m['label'], max(abs(x2 - x1), 150), 10)
            for i, ln in enumerate(mlines):
                yy = y - 6 - (len(mlines) - 1 - i) * 12
                out.append('<text x="%.1f" y="%.1f" font-size="10.5" fill="#243B4A" '
                           'text-anchor="middle">%s</text>' % (lx, yy, esc(ln)))

    # containers (back)
    for c in d.containers:
        x, y, w, h = cell_rect(c)
        hd = c['header']
        out.append('<rect x="%d" y="%d" width="%d" height="%d" rx="11" fill="%s" stroke="%s" '
                   'stroke-width="1.6"/>' % (x, y, w, h, c['bodyfill'], c['stroke']))
        out.append('<path d="M%.1f,%.1f L%.1f,%.1f A11,11 0 0 1 %.1f,%.1f L%.1f,%.1f '
                   'A11,11 0 0 1 %.1f,%.1f L%.1f,%.1f Z" fill="%s" stroke="%s" stroke-width="1.6"/>'
                   % (x, y + hd, x, y + 11, x + 11, y, x + w - 11, y, x + w, y + 11,
                      x + w, y + hd, c['fill'], c['stroke']))
        out.append('<text x="%.1f" y="%.1f" font-size="14.5" font-weight="700" fill="#10202E">%s</text>'
                   % (x + 14, y + hd - 10, esc(c['title'])))

    # edges (under nodes)
    for e in d.edges:
        pts = edge_points(d, e)
        path = 'M%.1f,%.1f ' % (pts[0][0], pts[0][1]) + ' '.join('L%.1f,%.1f' % (p[0], p[1]) for p in pts[1:])
        dash = ' stroke-dasharray="6 5"' if e['dashed'] else ''
        mid = 'arr_' + e['color'].replace('#', '')
        end = ' marker-end="url(#%s)"' % mid if e['arrow'] in ('end', 'both') else ''
        start = ' marker-start="url(#%s)"' % mid if e['arrow'] == 'both' else ''
        out.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.7"%s%s%s/>'
                   % (path, e['color'], dash, end, start))
        if e['label']:
            mx, my = poly_midpoint(pts)
            lab = esc(e['label']); ww = max(len(e['label']) * 6.0 + 8, 16)
            out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="16" rx="3" fill="#FFFFFF" '
                       'stroke="%s" stroke-width="0.8" opacity="0.95"/>'
                       % (mx - ww / 2, my - 9, ww, e['color']))
            out.append('<text x="%.1f" y="%.1f" font-size="10.5" fill="#243B4A" '
                       'text-anchor="middle">%s</text>' % (mx, my + 2.5, lab))

    # nodes
    for n in d.nodes:
        x, y, w, h = cell_rect(n); cx, cy = x + w / 2, y + h / 2
        if n['shape'] == 'cyl':
            ry = 9
            out.append('<path d="M%.1f,%.1f a%.1f,%.1f 0 0 0 %.1f,0 v%.1f a%.1f,%.1f 0 0 1 -%.1f,0 z" '
                       'fill="%s" stroke="%s" stroke-width="1.6"/>'
                       % (x, y + ry, w/2, ry, w, h - 2*ry, w/2, ry, w, n['fill'], n['stroke']))
            out.append('<ellipse cx="%.1f" cy="%.1f" rx="%.1f" ry="%.1f" fill="%s" stroke="%s" '
                       'stroke-width="1.6"/>' % (cx, y + ry, w/2, ry, tint(n['fill'], .2), n['stroke']))
            tcy = cy + ry/2
        elif n['shape'] == 'diamond':
            out.append('<polygon points="%.1f,%.1f %.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="%s" '
                       'stroke="%s" stroke-width="1.6"/>'
                       % (cx, y, x + w, cy, cx, y + h, x, cy, n['fill'], n['stroke']))
            tcy = cy
        elif n['shape'] == 'ellipse':
            out.append('<ellipse cx="%.1f" cy="%.1f" rx="%.1f" ry="%.1f" fill="%s" stroke="%s" '
                       'stroke-width="1.6"/>' % (cx, cy, w / 2, h / 2, n['fill'], n['stroke']))
            tcy = cy
        elif n['shape'] == 'actor':
            hx = cx; hcy = y + 13; r = 8
            out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="%s" stroke-width="1.6"/>'
                       % (hx, hcy, r, n['fill'], n['stroke']))
            bt = hcy + r; bb = bt + 18
            for (xa, ya, xb, yb) in [(hx, bt, hx, bb), (hx - 12, bt + 6, hx + 12, bt + 6),
                                     (hx, bb, hx - 10, bb + 12), (hx, bb, hx + 10, bb + 12)]:
                out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.6"/>'
                           % (xa, ya, xb, yb, n['stroke']))
            for i, ln in enumerate(wrap_text(n['label'], w + 50, n['fontsize'])):
                out.append('<text x="%.1f" y="%.1f" font-size="%.1f" font-weight="700" fill="%s" '
                           'text-anchor="middle">%s</text>'
                           % (cx, bb + 26 + i * (n['fontsize'] * 1.15), n['fontsize'], n['fontcolor'], esc(ln)))
            continue
        else:
            rx = 9 if n['shape'] == 'round' else 0
            out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%d" fill="%s" '
                       'stroke="%s" stroke-width="1.6"/>' % (x, y, w, h, rx, n['fill'], n['stroke']))
            tcy = cy
        lines = wrap_text(n['label'], w, n['fontsize'])
        lh = n['fontsize'] * 1.22
        y0 = tcy - (len(lines) * lh) / 2 + n['fontsize'] * 0.92
        fw = '700' if n['bold'] else '400'
        for i, ln in enumerate(lines):
            out.append('<text x="%.1f" y="%.1f" font-size="%.1f" font-weight="%s" fill="%s" '
                       'text-anchor="middle">%s</text>'
                       % (cx, y0 + i * lh, n['fontsize'], fw, n['fontcolor'], esc(ln)))

    # tables
    for t in d.tables:
        x, y, w, h = cell_rect(t)
        th = t['header']
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="7" fill="#FFFFFF" '
                   'stroke="%s" stroke-width="1.6"/>' % (x, y, w, h, t['stroke']))
        out.append('<path d="M%.1f,%.1f L%.1f,%.1f A7,7 0 0 1 %.1f,%.1f L%.1f,%.1f '
                   'A7,7 0 0 1 %.1f,%.1f L%.1f,%.1f Z" fill="%s" stroke="%s" stroke-width="1.6"/>'
                   % (x, y + th, x, y + 7, x + 7, y, x + w - 7, y, x + w, y + 7,
                      x + w, y + th, t['fill'], t['stroke']))
        out.append('<text x="%.1f" y="%.1f" font-size="13" font-weight="700" fill="#10202E" '
                   'text-anchor="middle">%s</text>' % (x + w/2, y + t['header'] - 9, esc(t['title'])))
        ry = y + t['header']
        for (txt, tag) in t['rows']:
            out.append('<text x="%.1f" y="%.1f" font-size="11" fill="#243B4A">%s</text>'
                       % (x + 9, ry + t['rowh'] - 6, esc(txt)))
            if tag:
                out.append('<text x="%.1f" y="%.1f" font-size="9.5" font-weight="700" fill="%s" '
                           'text-anchor="end">%s</text>' % (x + w - 8, ry + t['rowh'] - 6, t['stroke'], esc(tag)))
            ry += t['rowh']
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="0.5" '
                       'opacity="0.5"/>' % (x + 4, ry, x + w - 4, ry, t['stroke']))
    out.append('</svg>')
    return '\n'.join(out)

# ---------------------------------------------------------------- drawio render
def style_node(n):
    base = 'whiteSpace=wrap;html=1;fontSize=%g;fillColor=%s;strokeColor=%s;fontColor=%s;' % (
        n['fontsize'], n['fill'], n['stroke'], n['fontcolor'])
    if n['bold']: base += 'fontStyle=1;'
    if n['shape'] == 'cyl':   return 'shape=cylinder3;backgroundOutline=1;' + base
    if n['shape'] == 'diamond': return 'rhombus;' + base
    if n['shape'] == 'ellipse': return 'ellipse;' + base
    if n['shape'] == 'actor':
        return 'shape=umlActor;verticalLabelPosition=bottom;labelPosition=center;verticalAlign=top;outlineConnect=0;' + base
    if n['shape'] == 'round': return 'rounded=1;arcSize=12;' + base
    return 'rounded=0;' + base

def render_drawio(d):
    cells = []
    cells.append('<mxCell id="0"/>')
    cells.append('<mxCell id="1" parent="0"/>')
    # title
    cells.append('<mxCell id="title" value="%s" style="text;html=1;fontSize=20;fontStyle=1;'
                 'verticalAlign=middle;align=left;fontColor=#10202E;" vertex="1" parent="1">'
                 '<mxGeometry x="40" y="14" width="%d" height="32" as="geometry"/></mxCell>'
                 % (esc(d.title), d.w - 80))
    # containers (swimlane)
    for c in d.containers:
        st = ('swimlane;rounded=1;arcSize=4;startSize=%d;html=1;whiteSpace=wrap;fontSize=14;'
              'fontStyle=1;fillColor=%s;strokeColor=%s;swimlaneFillColor=%s;fontColor=#10202E;'
              'verticalAlign=middle;align=left;spacingLeft=8;'
              % (c['header'], c['fill'], c['stroke'], c['bodyfill']))
        cells.append('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
                     '<mxGeometry x="%d" y="%d" width="%d" height="%d" as="geometry"/></mxCell>'
                     % (c['id'], esc(c['title']), st, c['x'], c['y'], c['w'], c['h']))
    # nodes
    for n in d.nodes:
        val = '&lt;br&gt;'.join(esc(p) for p in str(n['label']).split('\n'))
        parent = n['parent'] if n['parent'] else '1'
        gx, gy = n['x'], n['y']
        if n['parent']:
            pc = d.byid[n['parent']]; gx -= pc['x']; gy -= pc['y']
        cells.append('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="%s">'
                     '<mxGeometry x="%d" y="%d" width="%d" height="%d" as="geometry"/></mxCell>'
                     % (n['id'], val, style_node(n), parent, gx, gy, n['w'], n['h']))
    # tables (swimlane + row children)
    for t in d.tables:
        st = ('swimlane;rounded=1;arcSize=6;startSize=%d;html=1;fontSize=13;fontStyle=1;'
              'fillColor=%s;strokeColor=%s;swimlaneFillColor=#FFFFFF;fontColor=#10202E;align=center;'
              % (t['header'], t['fill'], t['stroke']))
        cells.append('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
                     '<mxGeometry x="%d" y="%d" width="%d" height="%d" as="geometry"/></mxCell>'
                     % (t['id'], esc(t['title']), st, t['x'], t['y'], t['w'], t['h']))
        for i, (txt, tag) in enumerate(t['rows']):
            label = esc(txt) + ('  &lt;b&gt;%s&lt;/b&gt;' % esc(tag) if tag else '')
            rst = ('text;html=1;align=left;verticalAlign=middle;spacingLeft=8;fontSize=11;'
                   'strokeColor=none;fillColor=none;fontColor=#243B4A;')
            cells.append('<mxCell id="%s_r%d" value="%s" style="%s" vertex="1" parent="%s">'
                         '<mxGeometry x="0" y="%d" width="%d" height="%d" as="geometry"/></mxCell>'
                         % (t['id'], i, label, rst, t['id'], t['header'] + i * t['rowh'], t['w'], t['rowh']))
    # edges
    for k, e in enumerate(d.edges):
        endarr = 'none' if e['arrow'] == 'none' else 'block'
        st = ('edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;fontSize=11;endArrow=%s;'
              'strokeColor=%s;labelBackgroundColor=#FFFFFF;' % (endarr, e['color']))
        if e['dashed']: st += 'dashed=1;'
        if e['arrow'] == 'both': st += 'startArrow=block;'
        if e['srcside']:
            sx = {'top': .5, 'bottom': .5, 'left': 0, 'right': 1}[e['srcside']]
            sy = {'top': 0, 'bottom': 1, 'left': .5, 'right': .5}[e['srcside']]
            st += 'exitX=%g;exitY=%g;exitDx=0;exitDy=0;' % (sx, sy)
        if e['dstside']:
            tx = {'top': .5, 'bottom': .5, 'left': 0, 'right': 1}[e['dstside']]
            ty = {'top': 0, 'bottom': 1, 'left': .5, 'right': .5}[e['dstside']]
            st += 'entryX=%g;entryY=%g;entryDx=0;entryDy=0;' % (tx, ty)
        geo = '<mxGeometry relative="1" as="geometry">'
        if e['waypoints']:
            geo += '<Array as="points">' + ''.join(
                '<mxPoint x="%d" y="%d"/>' % (int(p[0]), int(p[1])) for p in e['waypoints']) + '</Array>'
        geo += '</mxGeometry>'
        cells.append('<mxCell id="e%d" value="%s" style="%s" edge="1" parent="1" source="%s" '
                     'target="%s">%s</mxCell>' % (k, esc(e['label']), st, e['src'], e['dst'], geo))

    # sequence: lifelines (umlLifeline)
    for ll in d.lifelines:
        bot = ll['bottom'] if ll['bottom'] else d.h - 30
        h = int(bot - ll['hy'])
        st = ('shape=umlLifeline;perimeter=lifelinePerimeter;whiteSpace=wrap;html=1;container=0;'
              'fillColor=%s;strokeColor=%s;fontColor=#15202B;fontStyle=1;fontSize=12;size=%d;'
              % (ll['fill'], ll['stroke'], ll['hh']))
        val = '&lt;br&gt;'.join(esc(p) for p in str(ll['label']).split('\n'))
        cells.append('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
                     '<mxGeometry x="%d" y="%d" width="%d" height="%d" as="geometry"/></mxCell>'
                     % (ll['id'], val, st, int(ll['x'] - ll['hw'] / 2), ll['hy'], ll['hw'], h))
    # sequence: fragments (umlFrame)
    for j, fr in enumerate(d.fragments):
        st = ('shape=umlFrame;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#5B6B7B;'
              'fontColor=#243B4A;fontStyle=1;fontSize=11;align=left;verticalAlign=top;width=%d;height=20;'
              % int(max(46, 22 + len(fr['label']) * 5.6)))
        cells.append('<mxCell id="frag%d" value="%s" style="%s" vertex="1" parent="1">'
                     '<mxGeometry x="%d" y="%d" width="%d" height="%d" as="geometry"/></mxCell>'
                     % (j, esc(fr['label']), st, int(fr['x1']), int(fr['y1']),
                        int(fr['x2'] - fr['x1']), int(fr['y2'] - fr['y1'])))
    # sequence: messages (free point edges)
    for k2, m in enumerate(d.messages):
        st = ('html=1;endArrow=block;rounded=0;fontSize=10;strokeColor=%s;'
              'labelBackgroundColor=#FFFFFF;align=center;verticalAlign=bottom;' % m['color'])
        if m['dashed']: st += 'dashed=1;'
        if m['kind'] == 'self':
            x = d._llx[m['frm']]; y = m['y']
            st += 'edgeStyle=orthogonalEdgeStyle;'
            geo = ('<mxGeometry relative="1" as="geometry">'
                   '<mxPoint x="%d" y="%d" as="sourcePoint"/><mxPoint x="%d" y="%d" as="targetPoint"/>'
                   '<Array as="points"><mxPoint x="%d" y="%d"/><mxPoint x="%d" y="%d"/></Array>'
                   '</mxGeometry>' % (int(x), int(y), int(x), int(y + 18),
                                      int(x + 26), int(y), int(x + 26), int(y + 18)))
        else:
            x1 = d._llx[m['frm']]; x2 = d._llx[m['to']]; y = m['y']
            geo = ('<mxGeometry relative="1" as="geometry">'
                   '<mxPoint x="%d" y="%d" as="sourcePoint"/><mxPoint x="%d" y="%d" as="targetPoint"/>'
                   '</mxGeometry>' % (int(x1), int(y), int(x2), int(y)))
        cells.append('<mxCell id="msg%d" value="%s" style="%s" edge="1" parent="1">%s</mxCell>'
                     % (k2, esc(m['label']), st, geo))

    body = ('<mxGraphModel dx="900" dy="600" grid="1" gridSize="10" guides="1" tooltips="1" '
            'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="%d" pageHeight="%d" '
            'math="0" shadow="0"><root>%s</root></mxGraphModel>'
            % (d.w, d.h, ''.join(cells)))
    return ('<mxfile host="app.diagrams.net" type="device">'
            '<diagram name="%s" id="%s">%s</diagram></mxfile>' % (esc(d.title), d.name, body))

def write(d):
    with open(os.path.join(OUT, d.name + '.drawio'), 'w') as f:
        f.write(render_drawio(d))
    with open(os.path.join(OUT, d.name + '.svg'), 'w') as f:
        f.write(render_svg(d))
    print('wrote', d.name + '.drawio', '+', d.name + '.svg', '(%dx%d)' % (d.w, d.h))

def row_x(x0, x1, n, w):
    if n == 1: return [(x0 + x1 - w) / 2]
    gap = ((x1 - x0) - n * w) / (n - 1)
    return [x0 + i * (w + gap) for i in range(n)]

# ================================================================ DIAGRAMS

def d_overall():
    d = Diagram('overall-system-architecture', '1 · Overall System Architecture', 1340, 800)
    # Frontend band
    d.container('FE', 40, 64, 1260, 92, 'Frontend  —  vanilla JS, no build step', 'fe')
    fx = row_x(64, 1276, 3, [540, 330, 300][0]) if False else None
    d.node('spa', 70, 100, 540, 46, 'Main SPA\nindex.html · app.js · chat.js · ocr-canvas.js · i18n.js', 'fe', parent='FE')
    d.node('agui', 636, 100, 360, 46, 'Agent workspace\nagent.html · agent.js', 'fe', parent='FE')
    d.node('admui', 1020, 100, 256, 46, 'Admin console\ntemplates/admin/* (Jinja)', 'fe', parent='FE')
    # Backend band
    d.container('BE', 40, 178, 1260, 96, 'Flask backend  —  single process (app.py)', 'be')
    bx = row_x(70, 1276, 5, 224)
    blbl = [('authbp', 'auth_bp\n/login · /api/auth/me'), ('admbp', 'admin_bp\n/admin/*'),
            ('approutes', 'app.py routes\n/api/upload · /api/ocr/* · /api/documents/*'),
            ('chatbp', 'chat_bp\n/api/chat/*'), ('agbp', 'agent_bp\n/api/agent/*')]
    for (i, (nid, lab)) in enumerate(blbl):
        d.node(nid, int(bx[i]), 216, 224, 48, lab, 'be', parent='BE')
    # OCR
    d.container('OCR', 40, 300, 372, 322, 'OCR pipeline (services/)', 'ocr')
    d.node('sos', 64, 340, 324, 40, 'smart_ocr_service / ocr_service', 'ocr', parent='OCR')
    d.node('router', 132, 392, 188, 36, 'router', 'ocr', parent='OCR')
    d.node('e1', 64, 442, 150, 38, 'Legacy PaddleOCR\n(PP-OCRv5)', 'ocr', parent='OCR', fontsize=10.5)
    d.node('e2', 238, 442, 150, 38, 'PaddleOCR Modern\n(PP-StructureV3)', 'ocr', parent='OCR', fontsize=10.5)
    d.node('e3', 64, 492, 150, 38, 'VietOCR\n(images only)', 'ocr', parent='OCR', fontsize=10.5)
    d.node('e4', 238, 492, 150, 38, 'GLM-OCR\n(subprocess)', 'ocr', parent='OCR', fontsize=10.5)
    d.node('geo', 64, 548, 324, 38, 'layout / geometry / markdown_normalize', 'ocr', parent='OCR', fontsize=11)
    d.edge('sos', 'router'); d.edge('router', 'e1'); d.edge('router', 'e2'); d.edge('router', 'e3'); d.edge('router', 'e4')
    # AI services
    d.container('AI', 428, 300, 252, 322, 'AI services (services/)', 'ai')
    d.node('corr', 452, 344, 204, 44, 'correction_service', 'ai', parent='AI')
    d.node('tran', 452, 400, 204, 44, 'translate_service\n(Google / Argos)', 'ai', parent='AI', fontsize=11)
    d.node('summ', 452, 456, 204, 44, 'summary_service\n(TF-IDF / PhoBERT / AI-rewrite)', 'ai', parent='AI', fontsize=10)
    d.node('rew', 452, 512, 204, 44, 'ai_rewrite_service\n(local Qwen)', 'ai', parent='AI', fontsize=11)
    # RAG
    d.container('RAG', 696, 300, 252, 322, 'Chat / RAG (chat_service.py)', 'rag')
    d.node('cs', 720, 344, 204, 42, 'chat_service.chat()', 'rag', parent='RAG')
    d.node('ee', 720, 398, 204, 44, 'EmbeddingEngine\nSBERT → Hashing', 'rag', parent='RAG', fontsize=11)
    d.node('idx', 720, 454, 204, 44, 'In-memory index / file_id\nFAISS IndexFlatIP', 'rag', parent='RAG', fontsize=10.5)
    d.node('qwen', 720, 510, 204, 44, 'Qwen chat model (local)', 'rag', parent='RAG', fontsize=11)
    d.edge('cs', 'ee'); d.edge('ee', 'idx'); d.edge('cs', 'qwen')
    # Agent
    d.container('AG', 964, 300, 336, 322, 'Agent (agent/)', 'agent')
    d.node('ac', 988, 344, 288, 42, 'AgentCore — reasoning loop', 'agent', parent='AG', bold=True)
    d.node('treg', 988, 398, 288, 50, 'Tool registry (safe set)\nchat · knowledge_search · summarize · translate · correct', 'agent', parent='AG', fontsize=10)
    d.node('kn', 988, 460, 138, 44, 'Knowledge\nDocumentKnowledge', 'agent', parent='AG', fontsize=10.5)
    d.node('mem', 1138, 460, 138, 44, 'Memory\nConversationMemory', 'agent', parent='AG', fontsize=10.5)
    d.node('agnote', 988, 516, 288, 40, 'OcrTool exists but is EXCLUDED from the safe set', 'sec', parent='AG', fontsize=10.5)
    d.edge('ac', 'treg'); d.edge('treg', 'kn'); d.edge('ac', 'mem')
    # bottom row
    d.node('mlx', 70, 650, 300, 64, 'GLM MLX server\nlocalhost:8080  (external subprocess)', 'ext', shape='round', fontsize=11)
    d.node('db', 470, 648, 250, 80, 'SQLite\npaddleocr.db (models.py)', 'db', shape='cyl', bold=True)
    d.container('LLM', 964, 638, 336, 92, 'Agent LLM providers (FallbackProvider)', 'llm')
    px = row_x(988, 1276, 3, 88)
    d.node('groq', int(px[0]), 678, 88, 40, 'Groq', 'llm', parent='LLM')
    d.node('gem', int(px[1]), 678, 88, 40, 'Gemini', 'llm', parent='LLM')
    d.node('lq', int(px[2]), 678, 88, 40, 'Local Qwen', 'llm', parent='LLM')
    d.edge('groq', 'gem', label='fallback'); d.edge('gem', 'lq', label='fallback')
    # cross edges
    d.edge('spa', 'authbp', color='#6C8EBF', srcside='bottom', dstside='top')
    d.edge('spa', 'approutes', color='#6C8EBF', srcside='bottom', dstside='top')
    d.edge('spa', 'chatbp', color='#6C8EBF', srcside='bottom', dstside='top')
    d.edge('agui', 'agbp', color='#6C8EBF', srcside='bottom', dstside='top')
    d.edge('admui', 'admbp', color='#6C8EBF', srcside='bottom', dstside='top')
    d.edge('approutes', 'OCR', color='#0E8088', srcside='bottom', dstside='top')
    d.edge('approutes', 'AI', color='#D79B00', srcside='bottom', dstside='top')
    d.edge('chatbp', 'RAG', color='#82B366', srcside='bottom', dstside='top')
    d.edge('agbp', 'AG', color='#9673A6', srcside='bottom', dstside='top')
    d.edge('e4', 'mlx', color='#0E8088', label='subprocess', dashed=True, dstside='top')
    d.edge('treg', 'cs', color='#82B366', label='chat / knowledge_search', waypoints=[(960, 470)], srcside='left', dstside='right')
    d.edge('treg', 'summ', color='#D79B00', label='summarize/translate/correct', srcside='left', dstside='right', waypoints=[(692, 478)])
    d.edge('AG', 'LLM', color='#D6B656', label='provider chain', srcside='bottom', dstside='top')
    d.edge('RAG', 'db', color='#5A5A5A', srcside='bottom', dstside='top')
    d.edge('approutes', 'db', color='#5A5A5A', label='save_artifact', dashed=True, waypoints=[(420, 288), (420, 688)], srcside='bottom', dstside='left')
    d.edge('mem', 'db', color='#5A5A5A', dashed=True, waypoints=[(1180, 612), (700, 612)], srcside='bottom', dstside='right')
    return d

def d_ocr():
    d = Diagram('ocr-pipeline', '2 · OCR Processing Pipeline', 1320, 560)
    y1 = 110; h = 60
    d.node('up', 50, y1, 200, h, 'POST /api/upload\nUUID filename · ext allowlist', 'fe', fontsize=11)
    d.node('doc', 300, y1, 175, h, 'Document row\nstatus = uploaded', 'db')
    d.node('req', 525, y1, 195, h, 'POST /api/ocr/all\nor /api/ocr/page', 'be', fontsize=11)
    d.node('own', 770, y1, 195, h, '_resolve_owned_file\nownership / IDOR guard', 'sec', fontsize=11)
    d.node('eng', 1015, y1, 255, h, 'Engine OCR via router\nLegacy / Modern / VietOCR / GLM', 'ocr', fontsize=10.5)
    d.edge('up', 'doc'); d.edge('doc', 'req'); d.edge('req', 'own'); d.edge('own', 'eng')
    y2 = 250
    d.node('nat', 1090, y2, 140, 80, 'layout_native?', 'note', shape='diamond', fontsize=11)
    d.node('geo', 820, y2 + 2, 215, 70, 'geometry / layout\nreading-order reconstruction\n(Legacy, VietOCR)', 'ocr', fontsize=10.5)
    d.node('ai', 600, y2, 130, 80, 'apply_ai?', 'note', shape='diamond', fontsize=11)
    d.node('clean', 330, y2 + 8, 215, 64, 'Qwen line cleanup\n(smart mode · safety-gated · text only)', 'ocr', fontsize=10)
    d.edge('eng', 'nat', srcside='bottom', dstside='top')
    d.edge('nat', 'geo', label='no', srcside='left')
    d.edge('geo', 'ai', dstside='right', srcside='left')
    d.edge('nat', 'ai', label='yes (Modern, GLM)', dashed=True, waypoints=[(1160, 360), (665, 360)], srcside='bottom', dstside='bottom')
    d.edge('ai', 'clean', label='yes', srcside='left')
    y3 = 410;
    d.node('store', 330, y3, 470, 78, 'save_artifact (document_artifacts)\nocr · ocr_layout · ocr_markdown/html/tables/blocks/json/images', 'db', fontsize=10.5)
    d.node('idx', 60, y3, 230, 66, 'index_document_async\ncanonical "ocr" text', 'rag', fontsize=11)
    d.node('ridx', 60, y3 - 96, 230, 56, 'In-memory RAG index', 'rag', fontsize=11)
    d.node('lib', 850, y3, 410, 66, 'Document Library\nGET /api/documents (artifact_kinds badges)', 'fe', fontsize=10.5)
    d.edge('clean', 'store', label='yes', srcside='bottom', dstside='top', waypoints=[(437, 380)])
    d.edge('ai', 'store', label='no', srcside='bottom', dstside='top', waypoints=[(665, 470), (660, 470)])
    d.edge('store', 'idx', srcside='left', dstside='right')
    d.edge('idx', 'ridx', srcside='top', dstside='bottom')
    d.edge('store', 'lib', srcside='right', dstside='left')
    return d

def d_lifecycle():
    d = Diagram('document-lifecycle', '3 · Document Lifecycle', 1180, 700)
    d.node('up', 60, 110, 180, 56, 'Upload', 'fe', bold=True)
    d.node('doc', 60, 230, 180, 60, 'Document\nstatus = uploaded', 'db')
    d.edge('up', 'doc')
    d.node('ocr', 320, 130, 200, 56, 'OCR\nstatus = ocr_done', 'ocr')
    d.node('read', 320, 230, 200, 56, 'read-text\nTXT / DOCX / PDF', 'ocr', fontsize=11)
    d.edge('doc', 'ocr', dstside='left'); d.edge('doc', 'read', dstside='left')
    # artifacts container
    d.container('ST', 600, 100, 540, 470, 'document_artifacts  —  one row per (document_id, kind)', 'db')
    d.node('a_ocr', 630, 150, 230, 58, 'kind: ocr\n(+ ocr_layout + structured)', 'ocr', parent='ST', fontsize=11)
    d.node('a_text', 880, 150, 230, 58, 'kind: text', 'ocr', parent='ST', fontsize=11)
    d.node('a_tr', 630, 360, 230, 64, 'kind: translation\n(only if file_id · NOT indexed)', 'ai', parent='ST', fontsize=10)
    d.node('a_su', 880, 360, 230, 58, 'kind: summary', 'ai', parent='ST', fontsize=11)
    d.node('ragi', 880, 470, 230, 56, 'In-memory RAG index', 'rag', parent='ST', fontsize=11)
    d.edge('ocr', 'a_ocr', dstside='left'); d.edge('read', 'a_text', dstside='left', waypoints=[(560, 258), (560, 179)])
    d.edge('a_ocr', 'ragi', color='#82B366', label='indexed', dashed=True, waypoints=[(745, 470)])
    d.edge('a_text', 'ragi', color='#82B366', label='indexed', dashed=True)
    # transforms
    d.node('corr', 320, 360, 200, 56, 'Correction\nPOST /api/correct', 'ai', fontsize=11)
    d.node('corrx', 320, 470, 200, 56, 'returned to UI only', 'sec', fontsize=11)
    d.edge('a_ocr', 'corr', srcside='left', dstside='right', waypoints=[(560, 179), (560, 388)])
    d.edge('corr', 'corrx', label='transient — NOT an artifact', color='#B85450', dashed=True)
    d.node('trn', 320, 580, 200, 50, 'Translate\nPOST /api/translate', 'ai', fontsize=11)
    d.node('smz', 630, 580, 230, 50, 'Summarize\nPOST /api/summarize', 'ai', fontsize=11)
    d.edge('a_ocr', 'trn', color='#D79B00', srcside='bottom', dstside='top', waypoints=[(745, 320), (420, 320)])
    d.edge('trn', 'a_tr', color='#D79B00', srcside='top', dstside='bottom')
    d.edge('a_ocr', 'smz', color='#D79B00', srcside='bottom', dstside='top', waypoints=[(745, 340)])
    d.edge('smz', 'a_su', color='#D79B00', srcside='top', dstside='bottom', waypoints=[(995, 540)])
    return d

def d_rag():
    d = Diagram('rag-architecture', '4 · RAG Architecture', 1180, 800)
    d.node('q', 430, 90, 320, 56, 'User question\n/api/chat/send  or  knowledge_search tool', 'fe', fontsize=11)
    d.node('mode', 470, 180, 240, 70, 'mode == general?', 'note', shape='diamond', fontsize=12)
    d.edge('q', 'mode')
    # left RAG branch
    d.node('ret', 110, 290, 320, 52, 'retrieve_chunks(query, file_id?, allowed_file_ids)', 'rag', fontsize=10.5)
    d.node('emb', 110, 372, 320, 56, 'EmbeddingEngine.embed(query)\nSBERT → Hashing fallback · L2-normalized', 'rag', fontsize=10.5)
    d.node('sel', 110, 458, 320, 56, 'Select target indexes\nsingle file_id OR all owned ∩ allowed_file_ids', 'rag', fontsize=10)
    d.node('srch', 110, 544, 320, 52, 'Per-index search\nFAISS IndexFlatIP (inner product = cosine)', 'rag', fontsize=10)
    d.node('rank', 110, 626, 320, 56, 'Union + sort by score + top_k = 5\nNO threshold · NO reranker', 'sec', fontsize=10.5)
    d.edge('mode', 'ret', label='no', srcside='left', waypoints=[(270, 215)])
    d.edge('ret', 'emb'); d.edge('emb', 'sel'); d.edge('sel', 'srch'); d.edge('srch', 'rank')
    # right no-rag
    d.node('norag', 760, 300, 300, 52, 'No retrieval (plain assistant prompt)', 'be', fontsize=11)
    d.edge('mode', 'norag', label='yes', srcside='right', waypoints=[(900, 215)])
    # assembly
    d.node('ctx', 500, 470, 300, 64, 'Context assembly · _build_chat_prompt\nMAX_CTX_CHARS = 3000 + token-budget fit', 'rag', fontsize=10)
    d.edge('rank', 'ctx', srcside='right', dstside='left', waypoints=[(465, 654)])
    d.edge('norag', 'ctx', srcside='bottom', dstside='top', waypoints=[(910, 502), (800, 502)])
    d.node('gen', 540, 580, 240, 56, 'Qwen chat model\n_run_inference', 'rag', fontsize=11)
    d.edge('ctx', 'gen')
    d.node('ans', 540, 672, 240, 48, 'Answer', 'fe', bold=True)
    d.edge('gen', 'ans')
    d.node('cite', 870, 470, 280, 64, 'Sources / citations\n{file_id, score, excerpt}', 'agent', fontsize=11)
    d.edge('rank', 'cite', color='#9673A6', label='from retrieved chunks', srcside='bottom', dstside='bottom', waypoints=[(270, 758), (1018, 758)])
    return d

def d_agent():
    d = Diagram('agent-architecture', '5 · Agent Architecture  (tool orchestration — no skill layer)', 1340, 800)
    d.node('user', 60, 110, 180, 54, 'User · /agent', 'fe', bold=True)
    d.node('abp', 60, 210, 300, 78, 'agent_bp.agent_run\nownership · lazy session · load history ·\ninject scoped doc context · set allowed_file_ids', 'be', fontsize=10)
    d.edge('user', 'abp', label='POST /api/agent/run')
    # core loop container
    d.container('CORE', 400, 96, 600, 470, 'AgentCore.run()  —  reasoning loop', 'agent')
    d.node('plan', 430, 140, 240, 50, 'Planning pass (optional)\n1–3 sentence advisory plan', 'agent', parent='CORE', fontsize=10.5)
    d.node('prov', 430, 220, 240, 46, 'Provider.complete(messages)', 'agent', parent='CORE', fontsize=11)
    d.node('parse', 430, 300, 240, 46, '_extract_json(raw)\none JSON action', 'agent', parent='CORE', fontsize=10.5)
    d.node('disp', 700, 296, 170, 70, 'action type', 'note', shape='diamond', parent='CORE', fontsize=11)
    d.node('obs', 430, 392, 240, 46, 'Append tool observation\nas user turn', 'agent', parent='CORE', fontsize=10.5)
    d.node('fin', 720, 430, 250, 56, 'Final answer + citations (≤5)', 'agent', parent='CORE', bold=True, fontsize=11)
    d.node('syn', 720, 200, 250, 50, 'Synthesis pass\n(on step exhaustion)', 'agent', parent='CORE', fontsize=10.5)
    d.edge('plan', 'prov'); d.edge('prov', 'parse'); d.edge('parse', 'disp')
    d.edge('disp', 'fin', label='{final} / non-JSON', srcside='bottom', dstside='top')
    d.edge('disp', 'obs', label='{tool, arguments}', srcside='left', dstside='right')
    d.edge('obs', 'prov', label='loop ≤ max_steps (1–6, default 4)', srcside='left', dstside='left', waypoints=[(410, 415), (410, 243)])
    d.edge('obs', 'syn', dashed=True, label='steps exhausted', srcside='right', dstside='bottom', waypoints=[(690, 415), (845, 415)])
    d.edge('syn', 'fin', srcside='bottom', dstside='top', waypoints=[(845, 415)])
    d.edge('abp', 'plan', dstside='left')
    # tools
    d.container('TOOLS', 400, 590, 600, 180, 'Reachable tools — _SAFE_TOOL_NAMES  (no skill-selection layer)', 'agent')
    tlbl = [('t_chat', 'chat → chat_service.chat (RAG)'), ('t_kn', 'knowledge_search →\nDocumentKnowledge → retrieve_chunks'),
            ('t_sum', 'summarize → summary_service'), ('t_tr', 'translate → translate_service'),
            ('t_co', 'correct → correction_service')]
    tx = row_x(424, 976, 3, 168);
    coords = [(424, 632), (612, 632), (800, 632), (424, 700), (612, 700)]
    for (i, (nid, lab)) in enumerate(tlbl):
        x, y = coords[i]
        d.node(nid, x, y, 168, 56, lab, 'agent', parent='TOOLS', fontsize=9.5)
    d.edge('disp', 'TOOLS', color='#9673A6', label='dispatch via ToolRegistry.run()', dashed=True, srcside='bottom', dstside='top', waypoints=[(785, 580)])
    # providers
    d.container('PROV', 1030, 96, 270, 180, 'FallbackProvider (priority order)', 'llm')
    d.node('groq', 1054, 140, 222, 36, 'Groq', 'llm', parent='PROV')
    d.node('gem', 1054, 186, 222, 36, 'Gemini', 'llm', parent='PROV')
    d.node('lq', 1054, 232, 222, 36, 'Local Qwen', 'llm', parent='PROV')
    d.edge('groq', 'gem'); d.edge('gem', 'lq')
    d.edge('prov', 'PROV', color='#D6B656', label='via', srcside='right', dstside='left', waypoints=[(1010, 243)])
    # tenancy scope
    d.node('scope', 1030, 320, 270, 70, 'Tenancy scope\nallowed_file_ids injected by server\n(LLM never chooses it)', 'sec', fontsize=10.5)
    d.edge('t_chat', 'scope', color='#B85450', dashed=True, srcside='right', dstside='bottom', waypoints=[(1165, 660)])
    d.edge('t_kn', 'scope', color='#B85450', dashed=True, srcside='top', dstside='bottom', waypoints=[(696, 600), (1165, 600)])
    # OCR excluded
    d.container('OCRX', 1030, 430, 270, 170, 'OCR is NOT an agent LLM tool', 'sec')
    d.node('o1', 1054, 472, 222, 56, 'OcrTool exists in the full registry\nbut is EXCLUDED from the safe set', 'sec', parent='OCRX', fontsize=10)
    d.node('o2', 1054, 536, 222, 56, 'OCR runs via agent upload →\n/api/ocr/all → /api/agent/ingest\n(recorded as a session turn)', 'sec', parent='OCRX', fontsize=9.5)
    d.edge('abp', 'OCRX', color='#B85450', dashed=True, label='upload path, NOT the loop', srcside='bottom', dstside='left', waypoints=[(210, 640), (210, 760), (1015, 515)])
    # deeplinks
    d.node('dest', 720, 600, 250, 0, '', 'agent')  # placeholder removed
    d.nodes.pop(); del d.byid['dest']
    d.node('dest', 1030, 640, 270, 56, 'results.py → deep-links\n#ocr / #summarize / #chat', 'fe', fontsize=10.5)
    d.edge('fin', 'dest', srcside='bottom', dstside='left', waypoints=[(845, 540)])
    return d

def d_erd():
    d = Diagram('database-erd', '6 · Database ER Diagram (SQLite · paddleocr.db)', 1400, 980)
    d.table('users', 600, 80, 250, 'users', [
        ('id', 'PK'), ('username', 'UK'), ('email', 'UK'), ('password_hash', ''),
        ('role  (admin|user)', ''), ('is_active', '')], 'fe')
    d.table('documents', 320, 320, 250, 'documents', [
        ('id', 'PK'), ('user_id', 'FK'), ('file_id (UUID)', 'UK'), ('filename', ''),
        ('file_type', ''), ('page_count', ''), ('status', '')], 'ocr')
    d.table('docart', 60, 620, 250, 'document_artifacts', [
        ('id', 'PK'), ('document_id', 'FK'), ('kind  (uq doc+kind)', ''),
        ('content', ''), ('meta', '')], 'ocr')
    d.table('chatconv', 620, 380, 260, 'chat_conversations', [
        ('id', 'PK'), ('user_id', 'FK'), ('document_id (null)', 'FK'),
        ('title', ''), ('last_mode', '')], 'rag')
    d.table('chatmsg', 620, 640, 270, 'chat_messages', [
        ('id', 'PK'), ('conversation_id', 'FK'), ('role', ''), ('content', ''),
        ('sources (JSON)', ''), ('mode', ''), ('engine_used', '')], 'rag')
    d.table('agconv', 980, 360, 250, 'agent_conversations', [
        ('id', 'PK'), ('user_id', 'FK'), ('title', '')], 'agent')
    d.table('agmsg', 980, 540, 270, 'agent_messages', [
        ('id', 'PK'), ('conversation_id', 'FK'), ('role', ''), ('content', ''),
        ('tool_calls (JSON)', ''), ('provider', '')], 'agent')
    d.table('agart', 1120, 760, 270, 'agent_artifacts', [
        ('id', 'PK'), ('conversation_id', 'FK'), ('message_id (null)', 'FK'),
        ('kind (source|result)', ''), ('module', ''), ('route (SPA hash)', ''),
        ('file_id', ''), ('label', '')], 'agent')
    d.table('actlog', 200, 80, 250, 'activity_logs', [
        ('id', 'PK'), ('user_id (null)', 'FK'), ('action', ''),
        ('detail', ''), ('ip_address', '')], 'db')
    d.edge('users', 'documents', label='owns 1→*', color='#3F61A8', srcside='bottom', dstside='top')
    d.edge('users', 'chatconv', label='owns · CASCADE', color='#3F61A8', srcside='bottom', dstside='top')
    d.edge('users', 'agconv', label='owns · CASCADE', color='#3F61A8', srcside='right', dstside='top', waypoints=[(1100, 200)])
    d.edge('users', 'actlog', label='SET NULL', color='#3F61A8', srcside='left', dstside='right')
    d.edge('documents', 'docart', label='has · CASCADE', color='#0E8088', srcside='bottom', dstside='top')
    d.edge('documents', 'chatconv', label='scopes · SET NULL', color='#0E8088', srcside='right', dstside='left')
    d.edge('chatconv', 'chatmsg', label='CASCADE', color='#82B366', srcside='bottom', dstside='top')
    d.edge('agconv', 'agmsg', label='CASCADE', color='#9673A6', srcside='bottom', dstside='top')
    d.edge('agconv', 'agart', label='CASCADE', color='#9673A6', srcside='bottom', dstside='top', waypoints=[(1300, 700)])
    d.edge('agmsg', 'agart', label='CASCADE', color='#9673A6', srcside='bottom', dstside='top')
    return d

def d_security():
    d = Diagram('security-architecture', '7 · Security Architecture (layered enforcement)', 1120, 920)
    d.node('req', 430, 70, 260, 46, 'Incoming HTTP request', 'fe', bold=True)
    lanes = [
        ('L1', '1 · Authentication — Flask-Login',
         '@login_required (session cookie) · Werkzeug password hashing · 401 JSON or redirect /login on failure', 'be'),
        ('L2', '2 · Authorization',
         'role = admin | user · @admin_required on /admin/* and admin API', 'be'),
        ('L3', '3 · Ownership validation',
         '_resolve_owned_file(file_id): file_id → Document → owner-or-admin check · glob disk by STORED UUID (no path traversal)', 'sec'),
        ('L4', '4 · Document access control',
         'lists + artifacts scoped to current_user · admins see all', 'ocr'),
        ('L5', '5 · Retrieval scope enforcement',
         'allowed_file_ids → retrieve_chunks (None = admin) · Agent injects scope server-side (LLM never picks it) · chat/knowledge tools drop unowned file_id', 'rag'),
    ]
    y = 140
    prev = 'req'
    for (lid, title, body, key) in lanes:
        d.container(lid, 120, y, 880, 110, title, key)
        d.node(lid + '_b', 150, y + 48, 820, 50, body, key, parent=lid, fontsize=11)
        d.edge(prev, lid, color='#445', srcside='bottom', dstside='top')
        prev = lid + '_b' if False else lid
        y += 140
    d.node('svc', 400, y, 320, 50, 'Service / data access', 'db', bold=True)
    d.edge('L5', 'svc', srcside='bottom', dstside='top')
    return d

def d_chatmodes():
    d = Diagram('chat-modes', '8 · Chat Modes Architecture', 1280, 760)
    # three swimlanes
    d.container('G', 60, 80, 360, 360, 'General Chat', 'be')
    d.node('g1', 90, 130, 300, 50, 'chat_bp · /api/chat/send\n(mode = general)', 'be', parent='G', fontsize=11)
    d.node('g2', 90, 230, 300, 50, 'chat_service.chat()\nNO retrieval', 'rag', parent='G', fontsize=11)
    d.node('g3', 90, 330, 300, 50, 'Qwen chat model', 'rag', parent='G', fontsize=11)
    d.edge('g1', 'g2'); d.edge('g2', 'g3')
    d.container('DC', 460, 80, 360, 440, 'Document Chat', 'rag')
    d.node('d1', 490, 130, 300, 56, 'chat_bp · /api/chat/send\n(mode = doc_current / doc_all)', 'be', parent='DC', fontsize=10.5)
    d.node('d2', 490, 220, 300, 56, 'retrieve_chunks()\nRAG, scoped to owned file_ids', 'rag', parent='DC', fontsize=10.5)
    d.node('d3', 490, 312, 300, 56, 'chat_service.chat()\ncontext-grounded prompt', 'rag', parent='DC', fontsize=10.5)
    d.node('d4', 490, 404, 300, 50, 'Qwen chat model', 'rag', parent='DC', fontsize=11)
    d.edge('d1', 'd2'); d.edge('d2', 'd3'); d.edge('d3', 'd4')
    d.container('AGC', 860, 80, 360, 440, 'Agent', 'agent')
    d.node('a1', 890, 130, 300, 46, 'agent_bp · /api/agent/run', 'be', parent='AGC', fontsize=11)
    d.node('a2', 890, 210, 300, 50, 'AgentCore loop\n(plan + tools)', 'agent', parent='AGC', fontsize=11)
    d.node('a3', 890, 300, 300, 50, 'Providers:\nGroq → Gemini → Local Qwen', 'llm', parent='AGC', fontsize=11)
    d.node('a4', 890, 392, 300, 64, 'tools: chat (RAG) · knowledge_search ·\nsummarize · translate · correct', 'agent', parent='AGC', fontsize=10)
    d.edge('a1', 'a2'); d.edge('a2', 'a3', srcside='bottom', dstside='top'); d.edge('a2', 'a4', srcside='bottom', dstside='top', waypoints=[(1100, 360)])
    # shared + db
    d.node('shared', 360, 580, 420, 60, 'Shared: chat_service · EmbeddingEngine ·\nin-memory FAISS index', 'rag', fontsize=10.5)
    d.edge('d2', 'shared', color='#82B366', srcside='bottom', dstside='top', waypoints=[(640, 560)])
    d.edge('a4', 'shared', color='#82B366', dashed=True, label='chat tool reuses RAG', srcside='bottom', dstside='right', waypoints=[(1040, 540), (800, 610)])
    d.node('cmsg', 220, 680, 300, 56, 'chat_messages\n(+ sources JSON)', 'db', shape='cyl', fontsize=11)
    d.node('amsg', 880, 680, 320, 56, 'agent_messages + agent_artifacts', 'db', shape='cyl', fontsize=10.5)
    d.edge('g3', 'cmsg', srcside='bottom', dstside='top', waypoints=[(240, 600), (300, 600)])
    d.edge('d4', 'cmsg', srcside='bottom', dstside='top', waypoints=[(640, 540), (380, 660)])
    d.edge('a2', 'amsg', color='#9673A6', srcside='right', dstside='top', waypoints=[(1240, 235), (1240, 660), (1000, 660)])
    return d

def d_appendix():
    d = Diagram('full-component-architecture',
                'Appendix · Full Component Architecture (file & module level)', 1860, 1180)
    # Frontend
    d.container('FE', 40, 70, 560, 250, 'Frontend (static/, templates/)  —  vanilla JS, no build', 'fe')
    d.node('fe_spa', 64, 116, 250, 92,
           'Main SPA (index.html)\n• app.js — Router, OCRView, DocumentsView\n• chat.js — ChatModule\n• ocr-canvas.js — OCRCanvas\n• i18n.js — I18n (vi/en)\n• vendor: marked, katex', 'fe', parent='FE', fontsize=9.5)
    d.node('fe_ag', 332, 116, 244, 56, 'Agent workspace (agent.html)\n• agent.js — runAgent, runSkill,\n  loadSessions, renderTranscript', 'fe', parent='FE', fontsize=9.5)
    d.node('fe_adm', 332, 184, 244, 56, 'Admin (templates/admin/*.html)\n• base · dashboard · users · logs · files', 'fe', parent='FE', fontsize=9.5)
    d.node('fe_login', 64, 232, 250, 56, 'login.html · 403.html\n(server-rendered Jinja)', 'fe', parent='FE', fontsize=9.5)
    d.node('fe_routes', 332, 252, 244, 56, 'hash routes: #ocr/<id> · #translate/<id>\n#summarize/<id> · #chat/<id>', 'fe', parent='FE', fontsize=9)

    # Backend blueprints
    d.container('BE', 40, 340, 560, 470, 'Flask backend (app.py — global app, 4 blueprints)', 'be')
    d.node('be_app', 64, 384, 512, 92,
           'app.py — OCR/upload/document routes\n/api/upload · /api/read-text · /api/ocr/page · /api/ocr/all\n/api/ocr/reconstruct-region · /api/correct · /api/translate\n/api/summarize · /api/documents[/<id>/text|ocr-images|download]\nhelpers: _resolve_owned_file · _persist_ocr_structured · _safe_basename', 'be', parent='BE', fontsize=9)
    d.node('be_auth', 64, 488, 250, 70, 'auth.py (auth_bp)\n/login · /logout · /api/auth/me\n/api/set-lang (no auth) · admin_required', 'be', parent='BE', fontsize=9)
    d.node('be_adm', 332, 488, 244, 70, 'admin_bp.py (/admin)\ndashboard · users CRUD · reset/toggle/delete\nlogs · files · admin_required', 'be', parent='BE', fontsize=9)
    d.node('be_chat', 64, 570, 250, 92, 'chat_bp.py\n/api/chat/status · /index · /index/<id>\n/cancel · /send · /conversations[CRUD]\n_owned_conversation/document/file_ids', 'be', parent='BE', fontsize=9)
    d.node('be_agent', 332, 570, 244, 92, 'agent_bp.py\n/api/agent/run · /ingest · /skill/<name>\n/tools · /ocr-engine · /index-status\n/ensure-indexed · /skills · /conversations[CRUD]', 'be', parent='BE', fontsize=8.5)
    d.node('be_cfg', 64, 678, 512, 56, 'config.py — _Config (dirs, devices, model paths, OFFLINE) · auth.py login_manager · @after_request _no_cache_static', 'be', parent='BE', fontsize=9)
    d.node('be_safe', 64, 744, 512, 50, 'agent_bp: _SAFE_TOOL_NAMES (5 tools, no ocr) · _AGENT_SKILL_NAMES = () · _HTTP_SKILLS = {summarize, translate, correct} · max_steps∈[1,6]', 'sec', parent='BE', fontsize=8.5)

    # OCR services
    d.container('OCR', 630, 70, 560, 360, 'OCR pipeline (services/ + services/ocr_engines/)', 'ocr')
    d.node('o_smart', 654, 116, 512, 50, 'smart_ocr_service.py — run_ocr_pipeline · _apply_ai_enhancement (Qwen line cleanup, safety-gated)', 'ocr', parent='OCR', fontsize=9)
    d.node('o_svc', 654, 176, 250, 50, 'ocr_service.py — run_ocr ·\npdf_page_to_pil · pdf_page_count', 'ocr', parent='OCR', fontsize=9)
    d.node('o_router', 922, 176, 244, 50, 'ocr_engines/router.py — get_engine ·\nrun_ocr · normalize_engine_name', 'ocr', parent='OCR', fontsize=9)
    d.node('o_e1', 654, 240, 122, 50, 'PaddleOCREngine\nPP-OCRv5', 'ocr', parent='OCR', fontsize=8.5)
    d.node('o_e2', 786, 240, 122, 50, 'PaddleOCRModern\nPP-StructureV3', 'ocr', parent='OCR', fontsize=8.5)
    d.node('o_e3', 918, 240, 122, 50, 'VietOCREngine\n(images only)', 'ocr', parent='OCR', fontsize=8.5)
    d.node('o_e4', 1050, 240, 116, 50, 'GLMOCREngine\nsubprocess', 'ocr', parent='OCR', fontsize=8.5)
    d.node('o_geo', 654, 304, 250, 50, 'geometry_service.py ·\nlayout_service.py (LayoutParser opt)', 'ocr', parent='OCR', fontsize=9)
    d.node('o_md', 922, 304, 244, 50, 'markdown_normalize.py ·\nactivity_registry · cpu_threads', 'ocr', parent='OCR', fontsize=9)
    d.node('o_mlx', 654, 368, 512, 46, 'GLM-OCR subprocess (own venv) → MLX server localhost:8080  [external]', 'ext', parent='OCR', fontsize=9)
    d.edge('o_e4', 'o_mlx', dashed=True, color='#0E8088', srcside='bottom', dstside='top')

    # AI services
    d.container('AI', 630, 450, 270, 360, 'AI services (services/)', 'ai')
    d.node('ai_corr', 654, 496, 222, 54, 'correction_service.py\ncorrect() — regex + autocorrect', 'ai', parent='AI', fontsize=9)
    d.node('ai_tr', 654, 560, 222, 64, 'translate_service.py\nGoogle (online) / Argos (offline)\ntranslate() · get_engine_status', 'ai', parent='AI', fontsize=8.5)
    d.node('ai_sum', 654, 634, 222, 64, 'summary_service.py\nTF-IDF/TextRank · PhoBERT · MMR\nsummarize() · ai_rewrite path', 'ai', parent='AI', fontsize=8.5)
    d.node('ai_rew', 654, 708, 222, 64, 'ai_rewrite_service.py\nlocal Qwen · run_local_messages\nprewarm · API fallback', 'ai', parent='AI', fontsize=8.5)
    d.node('ai_txt', 654, 782, 222, 22, 'text_service.py — read_file', 'ai', parent='AI', fontsize=9)

    # RAG
    d.container('RAG', 920, 450, 270, 360, 'Chat / RAG (services/chat_service.py)', 'rag')
    d.node('r_chat', 944, 496, 222, 50, 'chat() · retrieve_chunks ·\nchunk_text (400/80)', 'rag', parent='RAG', fontsize=9)
    d.node('r_emb', 944, 560, 222, 54, 'EmbeddingEngine\nSBERT → HashingVectorizer\n(16384-dim, L2-norm)', 'rag', parent='RAG', fontsize=8.5)
    d.node('r_idx', 944, 626, 222, 54, 'DocumentIndex · _index_cache\nFAISS IndexFlatIP (cosine)\nin-memory per file_id', 'rag', parent='RAG', fontsize=8.5)
    d.node('r_gen', 944, 692, 222, 54, '_run_inference — Qwen chat model\nCHAT_MODEL 1.5B default (3B opt-in)\ncancellable · MPS→CPU fallback', 'rag', parent='RAG', fontsize=8.5)
    d.node('r_rebuild', 944, 758, 222, 44, 'rebuild_indexes_from_db\nllm_registry (shared weights)', 'rag', parent='RAG', fontsize=9)

    # Agent
    d.container('AG', 1220, 70, 600, 470, 'Agent (agent/)', 'agent')
    d.node('ag_core', 1244, 116, 300, 70, 'core/agent.py — AgentCore.run()\nReAct loop · _extract_json · _make_plan\nAgentResult · AgentStep', 'agent', parent='AG', fontsize=9)
    d.node('ag_prov', 1560, 116, 236, 70, 'core/provider.py\nLLMProvider · Groq · Gemini\nLocalQwen · FallbackProvider', 'llm', parent='AG', fontsize=9)
    d.node('ag_tools', 1244, 200, 300, 92, 'tools/ — Tool · ToolRegistry · ToolResult\nOcrTool* · TranslateTool · SummarizeTool\nChatTool · KnowledgeSearchTool · CorrectionTool\n(*excluded from agent safe set)', 'agent', parent='AG', fontsize=8.5)
    d.node('ag_skills', 1560, 200, 236, 92, 'skills/ — Skill · SkillRegistry\nSkillContext · SkillResult\nOcrDigest · Research · DocQa\nSummarizeTranslate · …  [dormant in loop]', 'agent', parent='AG', fontsize=8)
    d.node('ag_kn', 1244, 306, 300, 70, 'knowledge/ — KnowledgeSource\nDocumentKnowledge · CompositeKnowledge\nKnowledgeRegistry · Citation · merge_citations', 'agent', parent='AG', fontsize=8.5)
    d.node('ag_mem', 1560, 306, 236, 70, 'memory/ — AgentMemory\nConversationMemory\nInMemoryAgentMemory', 'agent', parent='AG', fontsize=9)
    d.node('ag_route', 1244, 390, 300, 64, 'ocr_routing.py — select_ocr_engine\n(GLM default · vi→VietOCR · explicit wins)', 'agent', parent='AG', fontsize=9)
    d.node('ag_res', 1560, 390, 236, 64, 'results.py\ndestination deep-links\n(dedupe_destinations)', 'agent', parent='AG', fontsize=9)
    d.node('ag_note', 1244, 468, 552, 56, 'No skill-selection layer in the live HTTP agent: AgentCore is built with an EMPTY skill registry → orchestrates the 5 safe tools directly', 'sec', parent='AG', fontsize=9.5)
    d.edge('ag_core', 'ag_tools', srcside='bottom', dstside='top')
    d.edge('ag_core', 'ag_prov', srcside='right', dstside='top')
    d.edge('ag_tools', 'ag_kn', srcside='bottom', dstside='top')

    # DB + providers
    d.container('DB', 1220, 560, 600, 250, 'Persistence (models.py · SQLite paddleocr.db)', 'db')
    d.node('db_u', 1244, 606, 175, 50, 'users · documents', 'db', parent='DB', fontsize=10)
    d.node('db_art', 1432, 606, 175, 50, 'document_artifacts\n(one row per kind)', 'db', parent='DB', fontsize=9.5)
    d.node('db_chat', 1620, 606, 175, 50, 'chat_conversations\nchat_messages', 'db', parent='DB', fontsize=9.5)
    d.node('db_ag', 1244, 672, 175, 50, 'agent_conversations\nagent_messages', 'db', parent='DB', fontsize=9.5)
    d.node('db_agart', 1432, 672, 175, 50, 'agent_artifacts\n(reference rows)', 'db', parent='DB', fontsize=9.5)
    d.node('db_log', 1620, 672, 175, 50, 'activity_logs', 'db', parent='DB', fontsize=10)
    d.node('db_help', 1244, 740, 551, 50, 'helpers: save_artifact · get_or_create_conversation · add_message · add_agent_message · add_agent_artifacts · seed_admin · log_activity', 'db', parent='DB', fontsize=8.5)

    # cross-system edges
    d.edge('FE', 'BE', color='#6C8EBF', label='HTTP / JSON (cookie session)', srcside='bottom', dstside='top')
    d.edge('be_app', 'OCR', color='#0E8088', srcside='right', dstside='left', waypoints=[(612, 410)])
    d.edge('be_app', 'AI', color='#D79B00', srcside='right', dstside='left', waypoints=[(610, 600)])
    d.edge('be_chat', 'RAG', color='#82B366', srcside='right', dstside='left', waypoints=[(905, 616)])
    d.edge('be_agent', 'AG', color='#9673A6', srcside='right', dstside='left', waypoints=[(1205, 300)])
    d.edge('AG', 'RAG', color='#82B366', label='chat / knowledge tools', dashed=True, srcside='bottom', dstside='top', waypoints=[(1190, 440)])
    d.edge('AI', 'RAG', color='#999999', arrow='none', dashed=True)
    d.edge('RAG', 'DB', color='#5A5A5A', srcside='bottom', dstside='top', waypoints=[(1055, 830), (1300, 700)])
    d.edge('AI', 'DB', color='#5A5A5A', dashed=True, srcside='bottom', dstside='top', waypoints=[(765, 880), (1300, 830)])
    d.edge('AG', 'DB', color='#5A5A5A', srcside='bottom', dstside='top')
    d.edge('OCR', 'DB', color='#5A5A5A', dashed=True, label='save_artifact', srcside='bottom', dstside='top', waypoints=[(900, 440), (1500, 555)])
    return d

def d_usecase():
    d = Diagram('use-case-diagram', '9 · Use Case Diagram', 1460, 760)
    d.container('SYS', 300, 80, 820, 620, 'SmartDocs-Agent', 'ext')
    # use cases (ellipses), domain-coloured, parented to the system boundary
    uc = [('uc_login', 365, 102, 'Log in', 'be'),
          ('uc_docs', 365, 184, 'Upload & Manage Documents', 'be'),
          ('uc_ocr', 365, 266, 'Run OCR', 'ocr'),
          ('uc_correct', 365, 348, 'Correct Text', 'ai'),
          ('uc_translate', 365, 430, 'Translate', 'ai'),
          ('uc_summarize', 365, 512, 'Summarize', 'ai'),
          ('uc_genchat', 795, 184, 'General Chat', 'rag'),
          ('uc_docchat', 795, 266, 'Document Chat', 'rag'),
          ('uc_agent', 795, 348, 'Run Agent', 'agent'),
          ('uc_admin', 795, 506, 'Administer System\n(users · logs · files)', 'be')]
    for (i, (cid, x, y, lab, key)) in enumerate(uc):
        h = 60 if '\n' in lab else 56
        d.node(cid, x, y, 210, h, lab, key, shape='ellipse', parent='SYS', fontsize=11.5)
    # actors
    d.node('user', 72, 250, 96, 86, 'User', 'fe', shape='actor', bold=True)
    d.node('admin', 72, 506, 96, 86, 'Admin', 'be', shape='actor', bold=True)
    d.node('groqA', 1300, 110, 120, 86, 'Groq API', 'llm', shape='actor')
    d.node('gemA', 1300, 250, 120, 86, 'Gemini API', 'llm', shape='actor')
    d.node('glmA', 1300, 396, 120, 86, 'GLM-OCR MLX server', 'ocr', shape='actor')
    d.node('trA', 1300, 548, 120, 86, 'Online Translation (Google)', 'ai', shape='actor')
    A = '#9AA7B5'
    for c in ['uc_login', 'uc_docs', 'uc_ocr', 'uc_correct', 'uc_translate', 'uc_summarize',
              'uc_genchat', 'uc_docchat', 'uc_agent']:
        d.edge('user', c, color=A, arrow='none')
    d.edge('admin', 'uc_login', color=A, arrow='none')
    d.edge('admin', 'uc_admin', color=A, arrow='none')
    d.edge('admin', 'user', color='#B85450', dashed=True, arrow='none', label='also has all User use cases')
    d.edge('uc_agent', 'groqA', color=A, arrow='none')
    d.edge('uc_agent', 'gemA', color=A, arrow='none')
    d.edge('uc_ocr', 'glmA', color=A, arrow='none')
    d.edge('uc_translate', 'trA', color=A, arrow='none')
    return d

def d_funcdecomp():
    d = Diagram('functional-decomposition', '10 · Functional Decomposition', 1760, 710)
    d.node('root', 710, 56, 340, 52, 'SmartDocs-Agent\nFunctional Decomposition', 'be', bold=True)
    xs = [int(v) for v in row_x(30, 1730, 5, 330)]
    areas = [
        ('Document Processing', 'ocr', ['Upload', 'OCR Execution', 'Structured Extraction',
                                        'Artifact Storage', 'Document Library',
                                        'Engines: Legacy · Modern · VietOCR · GLM']),
        ('AI Services', 'ai', ['Correction', 'Translation', 'Summarization', 'AI Rewrite',
                               'Text Extraction']),
        ('Knowledge / RAG', 'rag', ['Indexing', 'Embedding', 'Retrieval', 'Ranking', 'Citations']),
        ('Agent', 'agent', ['AgentCore (reasoning loop)', 'Tool Registry', 'Providers (Groq/Gemini/Local)',
                            'Knowledge', 'Memory', 'OCR routing', 'Results',
                            'Tools: chat · knowledge_search · summarize · translate · correct']),
        ('Platform / Admin', 'be', ['Authentication', 'User Management', 'Activity Logs',
                                    'File Oversight', 'Document Management']),
    ]
    for (i, (title, key, kids)) in enumerate(areas):
        cx = xs[i]
        d.container('A%d' % i, cx, 150, 330, 500, title, key)
        for (j, k) in enumerate(kids):
            d.node('A%d_%d' % (i, j), cx + 12, 194 + j * 50, 306, 42, k, key, parent='A%d' % i, fontsize=10.5)
        d.edge('root', 'A%d' % i, color=P[key][1], srcside='bottom', dstside='top')
    return d

def d_deployment():
    d = Diagram('deployment-diagram', '11 · Deployment Diagram (production)', 1500, 620)
    d.container('CLIENT', 40, 90, 300, 170, '«device» Client', 'fe')
    d.node('cli', 64, 140, 252, 96, 'Web Browser\nSPA + Agent page\n(static assets)', 'fe', parent='CLIENT', fontsize=11)
    d.container('SERVER', 400, 80, 620, 400, '«device» Application Server (Linux)', 'be')
    d.node('nginx', 424, 138, 572, 50, '«execution env» nginx — reverse proxy · TLS (:443)', 'be', parent='SERVER', fontsize=10.5)
    d.node('gunicorn', 424, 204, 572, 92,
           '«execution env» gunicorn (1 worker · threads) → wsgi:app\nFlask app: app.py + blueprints · OCR engines · AI services ·\nAgent · RAG (in-memory index) · loaded models', 'be', parent='SERVER', fontsize=9.5)
    d.node('sqlite', 424, 318, 178, 70, '«artifact»\nSQLite paddleocr.db', 'db', shape='cyl', parent='SERVER', fontsize=10)
    d.node('uploads', 620, 318, 178, 70, '«artifact»\nuploads/', 'db', parent='SERVER', fontsize=10)
    d.node('models', 818, 318, 178, 70, '«artifact»\nmodels/ (MODEL_DIR)', 'db', parent='SERVER', fontsize=10)
    d.node('devnote', 424, 410, 572, 42, 'Development: python app.py (Flask dev server) — no nginx / gunicorn', 'note', parent='SERVER', fontsize=10)
    d.container('PROV', 1080, 90, 380, 250, '«device» External LLM providers (cloud)', 'llm')
    d.node('groq', 1104, 140, 332, 44, 'Groq API', 'llm', parent='PROV', fontsize=11)
    d.node('gemini', 1104, 192, 332, 44, 'Gemini API', 'llm', parent='PROV', fontsize=11)
    d.node('openai', 1104, 244, 332, 50, 'OpenAI / OpenRouter\n(optional AI-rewrite fallback)', 'llm', parent='PROV', fontsize=10)
    d.container('GLM', 1080, 380, 380, 150, '«device» GLM-OCR host (Apple Silicon · optional)', 'ext')
    d.node('glm', 1104, 430, 332, 72, 'MLX server :8080\nmlx_vlm.server', 'ext', parent='GLM', fontsize=11)
    d.edge('cli', 'nginx', color='#3F61A8', label='HTTPS :443', srcside='right', dstside='left')
    d.edge('nginx', 'gunicorn', color='#3F61A8', label='proxy_pass 127.0.0.1:5001', srcside='bottom', dstside='top')
    d.edge('gunicorn', 'sqlite', color='#5A5A5A', label='file I/O', srcside='bottom', dstside='top')
    d.edge('gunicorn', 'uploads', color='#5A5A5A', label='file I/O', srcside='bottom', dstside='top')
    d.edge('gunicorn', 'models', color='#5A5A5A', label='load', srcside='bottom', dstside='top')
    d.edge('gunicorn', 'groq', color='#D6B656', label='HTTPS (agent)', srcside='right', dstside='left')
    d.edge('gunicorn', 'gemini', color='#D6B656', label='HTTPS (agent)', srcside='right', dstside='left')
    d.edge('gunicorn', 'glm', color='#0E8088', label='HTTP :8080 (subprocess · optional)', dashed=True, srcside='right', dstside='left')
    return d

def d_docchat_seq():
    d = Diagram('document-chat-sequence', '12 · Document Chat — Sequence', 1400, 770)
    LL = [('user', 'User (SPA)', 'fe', 120), ('cbp', 'chat_bp.py', 'be', 360),
          ('cs', 'chat_service.py', 'rag', 620), ('idx', 'In-memory index', 'rag', 850),
          ('qwen', 'Qwen chat model', 'rag', 1060), ('db', 'chat_messages (DB)', 'db', 1280)]
    for (cid, lab, key, x) in LL:
        d.lifeline(cid, x, lab, key)
    CALL, RET, DBC = '#33475B', '#8A98A8', '#5A5A5A'
    d.fragment(560, 332, 915, 442, 'alt  [mode != general]')
    d.message('user', 'cbp', 150, 'POST /api/chat/send\n{query, file_id, mode, conversation_id}', color=CALL)
    d.message('cbp', 'cbp', 196, 'ownership checks · load server history', kind='self', color=CALL)
    d.message('cbp', 'db', 250, 'add_message(user turn) — persisted first', color=DBC)
    d.message('cbp', 'cs', 300, 'chat(query, file_id, mode, history, allowed_file_ids)', color=CALL)
    d.message('cs', 'idx', 378, 'retrieve_chunks (cosine/IP · top_k=5 · scoped)', color=CALL)
    d.message('idx', 'cs', 420, 'ranked (score, chunk, file_id)', dashed=True, color=RET)
    d.message('cs', 'cs', 458, 'build context-grounded prompt + token-budget fit', kind='self', color=CALL)
    d.message('cs', 'qwen', 512, 'generate (cancellable · MPS→CPU fallback)', color=CALL)
    d.message('qwen', 'cs', 558, 'answer', dashed=True, color=RET)
    d.message('cs', 'cbp', 608, '{answer, sources, engine_used}', dashed=True, color=RET)
    d.message('cbp', 'db', 654, 'add_message(assistant turn + sources JSON)', color=DBC)
    d.message('cbp', 'user', 702, '{answer, sources, conversation_id}', dashed=True, color=RET)
    return d

def d_agent_seq():
    d = Diagram('agent-execution-sequence', '13 · Agent Execution — Sequence', 1460, 900)
    LL = [('user', 'User (/agent)', 'fe', 120, 150), ('abp', 'agent_bp.py', 'be', 360, 160),
          ('core', 'AgentCore', 'agent', 610, 160), ('prov', 'Provider\n(Groq→Gemini→Local)', 'llm', 860, 190),
          ('treg', 'ToolRegistry', 'agent', 1090, 160), ('db', 'agent_* tables (DB)', 'db', 1300, 170)]
    for (cid, lab, key, x, hw) in LL:
        d.lifeline(cid, x, lab, key, hw=hw)
    CALL, RET, DBC = '#33475B', '#8A98A8', '#5A5A5A'
    d.fragment(300, 224, 452, 286, 'opt  [file_id provided]')
    d.fragment(545, 432, 1180, 700, 'loop  [up to max_steps]')
    d.fragment(560, 584, 1170, 680, 'alt  [action = {tool}]  ·  else → {final} breaks loop')
    d.message('user', 'abp', 150, 'POST /api/agent/run\n{message, file_id?, max_steps}', color=CALL)
    d.message('abp', 'abp', 196, 'ownership · lazy session · load history · scope allowed_file_ids', kind='self', color=CALL)
    d.message('abp', 'abp', 258, 'ensure indexed · inject doc-context turn', kind='self', color=CALL)
    d.message('abp', 'core', 312, 'run(message, history, allowed_file_ids)\n[safe tools · skills off · planning on]', color=CALL)
    d.message('core', 'prov', 362, 'complete (planning pass)', color=CALL)
    d.message('prov', 'core', 406, '1–3 sentence plan', dashed=True, color=RET)
    d.message('core', 'prov', 466, 'complete(messages)', color=CALL)
    d.message('prov', 'core', 510, 'raw text', dashed=True, color=RET)
    d.message('core', 'core', 556, '_extract_json(raw)', kind='self', color=CALL)
    d.message('core', 'treg', 614, 'run(tool, args [+allowed_file_ids])', color=CALL)
    d.message('treg', 'core', 658, 'ToolResult → append observation', dashed=True, color=RET)
    d.message('core', 'abp', 718, 'AgentResult(answer, steps, citations)', dashed=True, color=RET)
    d.message('abp', 'abp', 756, 'results.py → destination deep-links', kind='self', color=CALL)
    d.message('abp', 'db', 800, 'persist turns + artifact refs', color=DBC)
    d.message('abp', 'user', 844, '{answer, results, ocr_engine, steps}', dashed=True, color=RET)
    return d

def d_ocr_engines():
    d = Diagram('ocr-engine-architecture', '14 · OCR Engine Architecture', 1360, 820)
    d.node('entry', 480, 66, 400, 46, 'ocr_service.run_ocr(image_path, engine_name)', 'be', bold=True)
    d.node('abc', 60, 70, 320, 60, 'OCREngine (ABC · base.py)\nrun(image_path) → standard dict', 'ext', fontsize=10.5)
    d.node('router', 430, 140, 500, 56, 'router.run_ocr / get_engine\nselect by explicit name OR cfg.OCR_ENGINE default (paddle→paddleocr) · aliases', 'be', fontsize=9.5)
    d.edge('entry', 'router', srcside='bottom', dstside='top')
    d.edge('abc', 'router', dashed=True, color='#999999', arrow='none', label='implemented by engines')
    xs = [int(v) for v in row_x(40, 1320, 4, 300)]
    eng = [('Legacy PaddleOCR', 'PaddleOCREngine', 'PaddleOCR · PP-OCRv5 (pinned)', 'text + boxes\n(no structure)'),
           ('PaddleOCR Modern', 'PaddleOCRModernEngine', 'PPStructureV3 · PP-OCRv6_medium\norientation + unwarp', 'markdown · html · tables ·\nblocks · images (layout_native)'),
           ('VietOCR', 'VietOCREngine', 'PP-OCRv5 detection +\nVietOCR recognition · images only', 'text + boxes\n(confidence = None)'),
           ('GLM-OCR', 'GLMOCREngine', 'subprocess: glmocr.cli\nparse --mode selfhosted', 'markdown · tables · blocks ·\nimages · raw_json (layout_native)')]
    for (i, (title, cls, tech, out)) in enumerate(eng):
        cx = xs[i]
        d.container('E%d' % i, cx, 230, 300, 198, title, 'ocr')
        d.node('E%d_c' % i, cx + 16, 270, 268, 32, cls, 'ocr', parent='E%d' % i, fontsize=10.5, bold=True)
        d.node('E%d_t' % i, cx + 16, 312, 268, 50, tech, 'ocr', parent='E%d' % i, fontsize=9)
        d.node('E%d_o' % i, cx + 16, 372, 268, 46, out, 'ocr', parent='E%d' % i, fontsize=9)
        d.edge('router', 'E%d' % i, srcside='bottom', dstside='top', color='#0E8088')
    d.node('mlx', xs[3], 452, 300, 54, 'GLM MLX server :8080\n(GLM_OCR_API_URL)', 'ext', fontsize=10)
    d.edge('E3', 'mlx', dashed=True, color='#0E8088', label='HTTP', srcside='bottom', dstside='top')
    d.node('std', 350, 538, 660, 56, 'Standard result dict\nsuccess · results[{text, confidence, box}] · img_w/h · elapsed_ms · ocr_engine · inference_status', 'db', fontsize=9)
    for i in range(4):
        d.edge('E%d' % i, 'std', srcside='bottom', dstside='top', color='#5A5A5A')
    d.node('nat', 600, 634, 160, 76, 'layout_native?', 'note', shape='diamond', fontsize=11)
    d.edge('std', 'nat', srcside='bottom', dstside='top')
    d.node('geo', 90, 640, 300, 64, 'layout_service → geometry_service\nreading-order reconstruction\n(Legacy, VietOCR)', 'ocr', fontsize=9.5)
    d.edge('nat', 'geo', label='no', srcside='left', dstside='right')
    d.node('mdfix', 970, 636, 320, 56, 'markdown_normalize\nrepair_unmatched_display_math', 'ocr', fontsize=10)
    d.edge('nat', 'mdfix', label='yes (Modern, GLM)', srcside='right', dstside='left')
    d.node('ret', 470, 744, 420, 46, 'ocr_service returns dict\n→ OCR Processing Pipeline (persist + index)', 'be', fontsize=9.5)
    d.edge('geo', 'ret', srcside='bottom', dstside='left', color='#0E8088', waypoints=[(240, 760)])
    d.edge('mdfix', 'ret', srcside='bottom', dstside='right', color='#0E8088', waypoints=[(1130, 760)])
    return d

def d_correction():
    d = Diagram('correction-flow', '15 · Correction Flow', 1240, 470)
    d.node('http', 60, 110, 240, 50, 'POST /api/correct', 'be', fontsize=11)
    d.node('tool', 60, 200, 240, 50, 'Agent: correct tool\n(CorrectionTool)', 'agent', fontsize=10.5)
    d.node('svc', 360, 150, 270, 62, 'correction_service.correct(text)\nclassical · rule-based (no LLM)', 'ai', bold=True, fontsize=10)
    d.edge('http', 'svc', srcside='right', dstside='left')
    d.edge('tool', 'svc', srcside='right', dstside='left')
    d.node('clean', 690, 96, 250, 54, '_basic_clean(text)\nwhitespace / punctuation regex', 'ai', fontsize=10)
    d.edge('svc', 'clean', srcside='right', dstside='left', waypoints=[(655, 181), (655, 123)])
    d.node('eng', 720, 200, 150, 76, 'English text?', 'note', shape='diamond', fontsize=10.5)
    d.edge('clean', 'eng', srcside='bottom', dstside='top')
    d.node('spell', 700, 320, 250, 48, 'autocorrect.Speller (en)', 'ai', fontsize=10.5)
    d.edge('eng', 'spell', label='yes', srcside='bottom', dstside='top')
    d.node('res', 990, 150, 200, 64, 'result\n{corrected, changes, elapsed_ms}', 'db', fontsize=9.5)
    d.edge('eng', 'res', label='no', srcside='right', dstside='bottom', waypoints=[(1090, 238)])
    d.edge('spell', 'res', srcside='right', dstside='bottom', waypoints=[(1090, 344)])
    d.node('note', 360, 300, 270, 56, 'Note: OCR "smart mode" line cleanup is a\nseparate Qwen path (ai_rewrite_service)', 'ext', fontsize=9)
    return d

def d_translation():
    d = Diagram('translation-flow', '16 · Translation Flow', 1320, 560)
    d.node('http', 50, 110, 250, 56, 'POST /api/translate\n(+ GET /api/translate/status)', 'be', fontsize=10)
    d.node('tool', 50, 205, 250, 50, 'Agent: translate tool\n(TranslateTool)', 'agent', fontsize=10.5)
    d.node('svc', 350, 150, 290, 60, 'translate_service.translate(\ntext, from_lang, to_lang, engine)', 'ai', bold=True, fontsize=10)
    d.edge('http', 'svc', srcside='right', dstside='left')
    d.edge('tool', 'svc', srcside='right', dstside='left')
    d.node('det', 360, 254, 270, 46, 'detect language (langdetect)\nfrom_lang = auto', 'ai', fontsize=9.5)
    d.edge('svc', 'det', srcside='bottom', dstside='top')
    d.node('eng', 690, 150, 150, 80, 'engine?', 'note', shape='diamond', fontsize=11)
    d.edge('svc', 'eng', srcside='right', dstside='left')
    d.node('rch', 690, 320, 150, 80, 'online\nreachable?', 'note', shape='diamond', fontsize=10)
    d.edge('eng', 'rch', label='auto', srcside='bottom', dstside='top')
    d.node('online', 980, 100, 300, 56, 'Google Translate\n(deep_translator)', 'ai', fontsize=11)
    d.node('offline', 980, 320, 300, 60, 'Argos Translate / CTranslate2\n(offline · Stanza patched)', 'ai', fontsize=9.5)
    d.edge('eng', 'online', label='online', srcside='right', dstside='left', waypoints=[(900, 190), (900, 128)])
    d.edge('eng', 'offline', label='offline', color='#9AA7B5', srcside='right', dstside='left', waypoints=[(880, 190), (880, 350)])
    d.edge('rch', 'online', label='yes', srcside='right', dstside='left', waypoints=[(930, 360), (930, 128)])
    d.edge('rch', 'offline', label='no', srcside='right', dstside='left')
    d.node('res', 980, 460, 300, 50, 'result {translated, to_lang, engine}', 'db', fontsize=10)
    d.edge('online', 'res', srcside='left', dstside='left', waypoints=[(955, 128), (955, 485)])
    d.edge('offline', 'res', srcside='bottom', dstside='top')
    d.node('note', 350, 340, 270, 56, 'engine=auto: try online if reachable,\nelse offline · NO mid-execution fallback', 'ext', fontsize=9)
    return d

def d_summarization():
    d = Diagram('summarization-flow', '17 · Summarization Flow', 1320, 660)
    d.node('http', 60, 110, 250, 56, 'POST /api/summarize\n(+ GET /api/summarize/status)', 'be', fontsize=10)
    d.node('tool', 60, 205, 250, 50, 'Agent: summarize tool\n(SummarizeTool)', 'agent', fontsize=10.5)
    d.node('svc', 360, 150, 300, 60, 'summary_service.summarize(\ntext, mode, engine, summary_mode)', 'ai', bold=True, fontsize=10)
    d.edge('http', 'svc', srcside='right', dstside='left')
    d.edge('tool', 'svc', srcside='right', dstside='left')
    d.node('eng', 440, 252, 150, 78, 'engine?', 'note', shape='diamond', fontsize=11)
    d.edge('svc', 'eng', srcside='bottom', dstside='top')
    d.node('fast', 660, 236, 350, 46, 'fast: TF-IDF + TextRank (PageRank) + MMR', 'ai', fontsize=9.5)
    d.node('smart', 660, 300, 350, 46, 'smart: PhoBERT embeddings + MMR (VI)', 'ai', fontsize=9.5)
    d.edge('eng', 'fast', label='fast', srcside='right', dstside='left')
    d.edge('eng', 'smart', label='smart / auto', color='#9AA7B5', srcside='right', dstside='left', waypoints=[(620, 291), (630, 323)])
    d.node('mode', 660, 368, 350, 44, 'apply mode: short / bullets / executive', 'ai', fontsize=9.5)
    d.edge('fast', 'mode', srcside='bottom', dstside='top', waypoints=[(835, 282)])
    d.edge('smart', 'mode', srcside='bottom', dstside='top')
    d.node('sm', 440, 398, 150, 80, 'summary_mode?', 'note', shape='diamond', fontsize=10)
    d.edge('mode', 'sm', srcside='left', dstside='right', waypoints=[(630, 390), (630, 438)])
    d.node('rewrite', 660, 440, 360, 54, 'ai_rewrite_service · Qwen local / API fallback\n(abstractive rewrite)', 'ai', fontsize=9.5)
    d.edge('sm', 'rewrite', label='ai_rewrite', srcside='right', dstside='left')
    d.node('warm', 660, 518, 360, 40, 'model warming → HTTP 202', 'sec', fontsize=10)
    d.edge('rewrite', 'warm', dashed=True, color='#B85450', srcside='bottom', dstside='top')
    d.node('res', 120, 470, 290, 50, 'result {summary, mode, engine}', 'db', fontsize=10)
    d.edge('sm', 'res', label='fast', srcside='bottom', dstside='top', waypoints=[(515, 560), (265, 560)])
    d.edge('rewrite', 'res', label='on error → extractive', dashed=True, color='#B85450', srcside='bottom', dstside='bottom', waypoints=[(840, 600), (265, 600)])
    return d

def d_rag_runtime():
    d = Diagram('rag-runtime-flow', '18 · RAG Runtime & Index Lifecycle', 1360, 760)
    d.container('TRIG', 40, 92, 330, 244, 'Indexing triggers', 'ocr')
    trg = ['OCR persist → index_document_async', 'read-text persist → index',
           'POST /api/chat/index', 'startup: rebuild_indexes_from_db(app)']
    for (i, t) in enumerate(trg):
        d.node('tr%d' % i, 64, 132 + i * 48, 282, 40, t, 'ocr', parent='TRIG', fontsize=9.5)
    d.node('idxdoc', 430, 110, 330, 44, 'index_document(file_id, text)', 'rag', bold=True, fontsize=10.5)
    d.node('chunk', 430, 168, 330, 44, 'chunk_text (size=400 · overlap=80 · drop ≤20)', 'rag', fontsize=9.5)
    d.node('embed', 430, 226, 330, 52, 'EmbeddingEngine.embed\nSBERT → Hashing fallback · L2-norm', 'rag', fontsize=9.5)
    d.edge('TRIG', 'idxdoc', srcside='right', dstside='left')
    d.edge('idxdoc', 'chunk', srcside='bottom', dstside='top')
    d.edge('chunk', 'embed', srcside='bottom', dstside='top')
    d.node('cache', 460, 330, 440, 70, '_index_cache[file_id] = DocumentIndex\nFAISS IndexFlatIP (cosine) · in-memory · per file_id', 'db', shape='cyl', bold=True, fontsize=9.5)
    d.edge('embed', 'cache', srcside='bottom', dstside='top')
    d.node('vol', 950, 332, 320, 56, 'in-memory — lost on restart\n→ rebuilt from DB artifacts (B4)', 'sec', fontsize=9.5)
    d.edge('cache', 'vol', dashed=True, color='#B85450', srcside='right', dstside='left')
    d.node('help', 950, 120, 320, 50, 'is_indexed(file_id) · remove_document(file_id)', 'rag', fontsize=10)
    d.node('retr', 430, 436, 380, 48, 'retrieve_chunks(query, file_id?, top_k=5, allowed_file_ids)', 'rag', bold=True, fontsize=9)
    d.edge('cache', 'retr', srcside='bottom', dstside='top')
    d.node('targets', 430, 506, 380, 48, 'select targets: single file_id OR\nall owned ∩ allowed_file_ids', 'rag', fontsize=9.5)
    d.edge('retr', 'targets', srcside='bottom', dstside='top')
    d.node('search', 430, 576, 380, 44, 'per-index search · FAISS IndexFlatIP', 'rag', fontsize=10)
    d.edge('targets', 'search', srcside='bottom', dstside='top')
    d.node('rank', 430, 638, 380, 50, 'union + sort by score + top_k\nNO threshold · NO reranker', 'sec', fontsize=9.5)
    d.edge('search', 'rank', srcside='bottom', dstside='top')
    d.node('out', 880, 576, 380, 76, '(score, chunk, file_id) → consumers:\nchat_service.chat (doc_current / doc_all) ·\nKnowledgeSearchTool / DocumentKnowledge', 'agent', fontsize=9)
    d.edge('rank', 'out', srcside='right', dstside='left')
    return d

def d_agent_exec_flow():
    d = Diagram('agent-execution-flow', '19 · Agent Execution Flow (AgentCore.run)', 1180, 940)
    def n(id, y, lab, key='agent', h=46, w=360, x=300, fs=10.5, bold=False):
        d.node(id, x, y, w, h, lab, key, fontsize=fs, bold=bold); return id
    n('start', 70, 'AgentCore.run(user_message, history, allowed_file_ids)', 'be', bold=True)
    n('init', 136, '_initial_messages: system prompt + history + user message')
    n('ctx', 196, 'build run_ctx (inject allowed_file_ids)')
    d.node('plan_q', 300, 256, 150, 74, 'enable_planning?', 'note', shape='diamond', fontsize=10)
    d.edge('start', 'init', srcside='bottom', dstside='top')
    d.edge('init', 'ctx', srcside='bottom', dstside='top')
    d.edge('ctx', 'plan_q', srcside='bottom', dstside='top')
    n('plan', 268, '_make_plan (1 LLM call · advisory)\nappend plan turns', 'agent', h=50, w=320, x=720, fs=9.5)
    d.edge('plan_q', 'plan', label='yes', srcside='right', dstside='left')
    n('complete', 360, 'provider.complete(messages)')
    d.edge('plan_q', 'complete', label='no', srcside='bottom', dstside='top')
    d.edge('plan', 'complete', dashed=True, color='#9AA7B5', srcside='bottom', dstside='right', waypoints=[(880, 383)])
    n('extract', 426, '_extract_json(raw)')
    d.edge('complete', 'extract', srcside='bottom', dstside='top')
    d.node('act_q', 300, 488, 150, 80, 'actionable JSON\n(tool / skill)?', 'note', shape='diamond', fontsize=9.5)
    d.edge('extract', 'act_q', srcside='bottom', dstside='top')
    n('final', 502, 'final answer (action.final or raw text)\nfinalize citations (≤5) → AgentResult(completed=True)', 'db', h=56, w=400, x=700, fs=9)
    d.edge('act_q', 'final', label='no', srcside='right', dstside='left')
    n('resolve', 588, 'resolve tool / skill (lenient reclassify)')
    d.edge('act_q', 'resolve', label='yes', srcside='bottom', dstside='top')
    n('tenancy', 648, 'tenancy tool? → inject allowed_file_ids\n(chat, knowledge_search)', 'sec', h=50, fs=9.5)
    d.edge('resolve', 'tenancy', srcside='bottom', dstside='top')
    n('run', 716, 'registry.run / skills.run → ToolResult / SkillResult')
    d.edge('tenancy', 'run', srcside='bottom', dstside='top')
    n('obs', 776, 'observation = result.to_dict() · collect citations · truncate 1500\nappend assistant(raw) + user(observation)', 'agent', h=54, fs=9)
    d.edge('run', 'obs', srcside='bottom', dstside='top')
    d.node('loop_q', 300, 850, 150, 72, 'step < max_steps?', 'note', shape='diamond', fontsize=9.5)
    d.edge('obs', 'loop_q', srcside='bottom', dstside='top')
    d.edge('loop_q', 'complete', label='yes (loop)', srcside='left', dstside='left', waypoints=[(250, 886), (250, 383)])
    n('synth', 854, 'synthesis pass: "stop calling tools,\ngive best final answer" → AgentResult(completed=False)', 'db', h=56, w=400, x=700, fs=9)
    d.edge('loop_q', 'synth', label='no', srcside='right', dstside='left')
    d.node('note', 60, 72, 200, 116, 'HTTP path:\n· safe tools only\n· skills off\n· planning on\n· max_steps ∈ [1,6] (default 4)', 'ext', fontsize=9.5)
    return d

def d_agent_tools():
    d = Diagram('agent-tool-ecosystem', '20 · Agent Tool Ecosystem', 1340, 760)
    d.node('core', 60, 320, 200, 60, 'AgentCore', 'agent', bold=True)
    d.node('reg', 300, 312, 290, 78, 'ToolRegistry.run(name, **args)\nnever raises · failure → ToolResult.failure\nmeta: tool, elapsed_ms', 'agent', fontsize=9.5)
    d.edge('core', 'reg', srcside='right', dstside='left')
    d.container('SAFE', 640, 88, 360, 472, '_SAFE_TOOL_NAMES — reachable by the LLM', 'agent')
    tools = [('translate', 'translate (TranslateTool)', 'translate_service.translate', 'ai'),
             ('summarize', 'summarize (SummarizeTool)', 'summary_service.summarize', 'ai'),
             ('chat', 'chat (ChatTool)  ·  tenancy', 'chat_service.chat', 'rag'),
             ('know', 'knowledge_search (KnowledgeSearchTool) · tenancy', 'knowledge composite().retrieve\n→ retrieve_chunks', 'rag'),
             ('correct', 'correct (CorrectionTool)', 'correction_service.correct', 'ai')]
    for (i, (tid, lab, svc, skey)) in enumerate(tools):
        y = 128 + i * 84
        d.node('t_' + tid, 664, y, 312, 56, lab, 'agent', parent='SAFE', fontsize=9)
        d.node('s_' + tid, 1040, y, 280, 56, svc, skey, fontsize=9.5)
        d.edge('t_' + tid, 's_' + tid, srcside='right', dstside='left', color='#9673A6')
        d.edge('reg', 't_' + tid, srcside='right', dstside='left', color='#9673A6', waypoints=[(620, y + 28)])
    d.node('t_ocr', 664, 600, 312, 54, 'ocr (OcrTool) → smart_ocr_service.run_ocr_pipeline', 'sec', fontsize=9)
    d.node('excl', 1040, 600, 280, 54, 'EXCLUDED from _SAFE_TOOL_NAMES\n(not reachable by the LLM)', 'sec', fontsize=9.5)
    d.edge('reg', 't_ocr', dashed=True, color='#B85450', srcside='bottom', dstside='left', waypoints=[(440, 627)])
    d.edge('t_ocr', 'excl', srcside='right', dstside='left', color='#B85450')
    d.node('note', 60, 430, 290, 80, 'Tool = ABC (one responsibility) · returns ToolResult.\nTenancy: AgentCore injects allowed_file_ids for\nchat & knowledge_search (LLM never chooses it).', 'ext', fontsize=9)
    return d

def d_provider_chain():
    d = Diagram('provider-fallback-chain', '21 · Provider Fallback Chain', 1240, 700)
    d.node('gdp', 450, 66, 360, 50, 'get_default_provider()\nreads AGENT_LLM_PROVIDER (default: auto)', 'be', bold=True, fontsize=10.5)
    d.node('sel', 550, 150, 160, 80, 'AGENT_LLM_PROVIDER?', 'note', shape='diamond', fontsize=9.5)
    d.edge('gdp', 'sel', srcside='bottom', dstside='top')
    d.node('localonly', 840, 168, 300, 46, 'LocalQwenProvider only', 'llm', fontsize=11)
    d.edge('sel', 'localonly', label='local', srcside='right', dstside='left')
    d.node('build', 300, 270, 300, 50, 'build chain (auto / groq / gemini)', 'be', fontsize=10.5)
    d.edge('sel', 'build', label='auto / groq / gemini', srcside='bottom', dstside='top', waypoints=[(630, 250)])
    d.node('c1', 100, 350, 340, 48, 'if GROQ_API_KEY & choice∈{auto,groq}\n→ append GroqProvider', 'llm', fontsize=9.5)
    d.node('c2', 100, 412, 340, 48, 'if GEMINI_API_KEY & choice∈{auto,gemini}\n→ append GeminiProvider', 'llm', fontsize=9.5)
    d.node('c3', 100, 474, 340, 48, 'always append LocalQwenProvider (last)', 'llm', fontsize=9.5)
    d.edge('build', 'c1', srcside='bottom', dstside='top', waypoints=[(270, 340)])
    d.edge('c1', 'c2', srcside='bottom', dstside='top')
    d.edge('c2', 'c3', srcside='bottom', dstside='top')
    d.container('FB', 560, 350, 620, 196, 'FallbackProvider(chain) — degrade on exception · sticky _start · empty string = success', 'llm')
    d.node('groq', 584, 410, 150, 70, 'GroqProvider\nllama-3.3-70b-versatile', 'llm', parent='FB', fontsize=9.5)
    d.node('gem', 800, 410, 150, 70, 'GeminiProvider\ngemini-2.0-flash', 'llm', parent='FB', fontsize=9.5)
    d.node('local', 1016, 410, 150, 70, 'LocalQwenProvider\n(ai_rewrite_service)', 'llm', parent='FB', fontsize=9.5)
    d.edge('groq', 'gem', label='on fail', color='#B85450', srcside='right', dstside='left')
    d.edge('gem', 'local', label='on fail', color='#B85450', srcside='right', dstside='left')
    d.edge('c3', 'FB', label='≥2 providers', srcside='right', dstside='left')
    d.node('one', 560, 566, 620, 40, 'single provider if chain length 1 · provider.complete(messages, max_tokens, temperature)', 'be', fontsize=9.5)
    d.edge('FB', 'one', srcside='bottom', dstside='top')
    return d

def d_context():
    d = Diagram('context-diagram', 'Context Diagram (Level 0)', 1500, 720)
    d.node('sys', 560, 294, 380, 118, '0\nSmartDocs-Agent Platform', 'be', shape='round', bold=True, fontsize=14)
    d.node('user', 90, 168, 170, 78, 'User', 'fe', shape='rect', bold=True)
    d.node('admin', 90, 470, 170, 78, 'Admin', 'be', shape='rect', bold=True)
    d.node('groq', 1240, 100, 180, 58, 'Groq API', 'llm', shape='rect')
    d.node('gem', 1240, 196, 180, 58, 'Gemini API', 'llm', shape='rect')
    d.node('glm', 1240, 320, 180, 72, 'GLM-OCR\nMLX server :8080', 'ocr', shape='rect', fontsize=10.5)
    d.node('gt', 1240, 470, 180, 72, 'Online Translation\n(Google)', 'ai', shape='rect', fontsize=10.5)
    d.edge('user', 'sys', arrow='both', srcside='right', dstside='left', label='requests & uploads  /  results & answers')
    d.edge('admin', 'sys', arrow='both', srcside='right', dstside='left', label='admin actions  /  users · logs · files')
    d.edge('sys', 'groq', arrow='both', srcside='right', dstside='left', label='agent prompt / completion')
    d.edge('sys', 'gem', arrow='both', srcside='right', dstside='left', label='agent fallback / completion')
    d.edge('sys', 'glm', arrow='both', srcside='right', dstside='left', label='OCR request / structured result')
    d.edge('sys', 'gt', arrow='both', srcside='right', dstside='left', label='text / translation (online)')
    d.node('cap', 90, 600, 560, 62, 'Notation: rounded box = system process (0) · rectangle = external entity.\nLevel-0 context: the platform as a single process with its external interactors.', 'ext', fontsize=9)
    return d

def d_dfd1():
    d = Diagram('dfd-level-1', 'Data Flow Diagram — Level 1', 1660, 1000)
    def P(id, x, y, w, h, lab, key): d.node(id, x, y, w, h, lab, key, shape='round', bold=True, fontsize=10)
    def S(id, x, y, w, lab): d.node(id, x, y, w, 48, lab, 'db', shape='cyl', fontsize=9.5)
    def E(id, x, y, lab, key, h=72): d.node(id, x, y, 150, h, lab, key, shape='rect', bold=True, fontsize=10.5)
    # external entities — services aligned with the process row that uses them
    E('user', 50, 398, 'User', 'fe')
    E('admin', 50, 95, 'Admin', 'be')
    E('glm', 1490, 250, 'GLM-OCR\nMLX :8080', 'ocr')
    E('gt', 1490, 372, 'Online\nTranslation', 'ai')
    E('groq', 1490, 560, 'Groq API', 'llm', h=58)
    E('gem', 1490, 648, 'Gemini API', 'llm', h=58)
    P('p1', 300, 88, 250, 78, '1 · Authenticate\n& Admin', 'be')
    P('p2', 300, 248, 250, 82, '2 · Document Intake\n(upload · read-text · library)', 'be')
    P('p3', 610, 248, 220, 82, '3 · OCR Processing\n(engines → artifacts)', 'ocr')
    P('p4', 890, 248, 250, 82, '4 · AI Services\n(correct · translate · summarize)', 'ai')
    P('p5', 610, 430, 260, 86, '5 · RAG Index &\nRetrieval', 'rag')
    P('p6', 300, 600, 250, 84, '6 · Chat (general / document)\nlocal Qwen chat model', 'rag')
    P('p7', 610, 600, 260, 90, '7 · Agent Orchestration\nproviders + tools', 'agent')
    S('d1', 610, 90, 200, 'D1 · users')
    S('d7', 610, 140, 200, 'D7 · activity_logs')
    S('d8', 300, 360, 250, 'D8 · uploads/')
    S('d2', 300, 442, 250, 'D2 · documents')
    S('d3', 890, 362, 250, 'D3 · document_artifacts')
    S('d4', 910, 448, 250, 'D4 · RAG index (in-memory)')
    S('d5', 300, 712, 250, 'D5 · chat_conversations / messages')
    S('d6', 610, 712, 260, 'D6 · agent_* (conv / msg / artifacts)')
    c = '#33475B'
    # --- Auth & Admin ---
    d.edge('admin', 'p1', arrow='both', color=c, srcside='right', dstside='left', label='admin actions / users·logs·files')
    d.edge('p1', 'd1', arrow='both', color=c, srcside='right', dstside='left', label='users')
    d.edge('p1', 'd7', color=c, srcside='right', dstside='left', label='log', waypoints=[(575, 127), (575, 162)])
    d.edge('user', 'p1', arrow='both', color=c, srcside='top', dstside='left', label='login / session', waypoints=[(128, 150)])
    # --- Document Intake ---
    d.edge('user', 'p2', arrow='both', color=c, srcside='right', dstside='left', label='upload / file_id, list')
    d.edge('p2', 'd8', color=c, srcside='bottom', dstside='top', label='store file')
    d.edge('p2', 'd2', arrow='both', color=c, srcside='left', dstside='left', label='create / read', waypoints=[(272, 310), (272, 466)])
    # --- OCR ---
    d.edge('p2', 'p3', color=c, srcside='right', dstside='left', label='file_id')
    d.edge('d8', 'p3', color=c, srcside='right', dstside='bottom', label='read file', waypoints=[(580, 385), (580, 338)])
    d.edge('user', 'p3', arrow='both', color=c, srcside='top', dstside='top', label='OCR request / result', waypoints=[(128, 226), (710, 226)])
    d.edge('p3', 'glm', arrow='both', color='#0E8088', srcside='right', dstside='left', label='GLM engine (:8080)', waypoints=[(855, 270), (855, 222), (1350, 222)])
    d.edge('p3', 'd3', color=c, srcside='right', dstside='top', label='store artifacts', waypoints=[(1015, 300)])
    d.edge('p3', 'p5', color='#82B366', srcside='bottom', dstside='top', label='index text')
    # --- AI Services ---
    d.edge('user', 'p4', arrow='both', color=c, srcside='top', dstside='top', label='request / result', waypoints=[(128, 200), (1015, 200)])
    d.edge('d3', 'p4', arrow='both', color=c, srcside='top', dstside='bottom', label='OCR text / summary·translation')
    d.edge('p4', 'gt', arrow='both', color='#D79B00', srcside='right', dstside='left', label='online translate', waypoints=[(1340, 289), (1340, 408)])
    # --- RAG ---
    d.edge('p5', 'd4', arrow='both', color='#82B366', srcside='right', dstside='left', label='embed / retrieve')
    # --- Chat ---
    d.edge('user', 'p6', arrow='both', color=c, srcside='bottom', dstside='left', label='chat query / answer + sources', waypoints=[(130, 642)])
    d.edge('p6', 'p5', arrow='both', color='#82B366', srcside='right', dstside='bottom', label='retrieve_chunks / chunks', waypoints=[(578, 642), (578, 520), (660, 520)])
    d.edge('p6', 'd5', arrow='both', color=c, srcside='bottom', dstside='top', label='store / history')
    # --- Agent ---
    d.edge('user', 'p7', arrow='both', color=c, srcside='bottom', dstside='bottom', label='agent message / results', waypoints=[(130, 800), (660, 800)])
    d.edge('p7', 'groq', arrow='both', color='#D6B656', srcside='right', dstside='left', label='prompt / completion', waypoints=[(1380, 620)])
    d.edge('p7', 'gem', arrow='both', color='#D6B656', srcside='right', dstside='left', label='fallback', waypoints=[(1400, 670)])
    d.edge('p7', 'p4', color='#9673A6', srcside='top', dstside='bottom', label='tools: summarize / translate / correct', waypoints=[(885, 560), (885, 360)])
    d.edge('p7', 'p6', color='#9673A6', srcside='left', dstside='right', label='tool: chat')
    d.edge('p7', 'p5', color='#9673A6', srcside='top', dstside='right', label='tool: knowledge_search', waypoints=[(760, 560)])
    d.edge('p7', 'd6', arrow='both', color=c, srcside='bottom', dstside='top', label='store / refs')
    d.node('cap', 1180, 770, 280, 100, 'Notation:\n· rounded = process (n)\n· cylinder = data store (Dn)\n· rectangle = external entity\n(both-headed arrow = request / response)', 'ext', fontsize=8.5)
    return d

def d_backend():
    d = Diagram('backend-architecture', 'Backend Architecture', 1520, 1010)

    # ── top: client ─────────────────────────────────────────────
    d.node('client', 380, 70, 760, 56,
           'Web browser — Main SPA (app.js · chat.js · i18n.js) · Agent workspace (agent.js) '
           '· Admin console (Jinja templates)', 'fe', fontsize=10)

    # ── Flask application core (+ extensions) ────────────────────
    d.container('APP', 40, 168, 1440, 150,
                'Flask application core — global app at app.py:23 (not an app factory)', 'be')
    d.node('app_app', 64, 212, 262, 66, 'Flask(app)\n@ app.py:23 · config → app.config',
           'be', parent='APP', bold=True, fontsize=10)
    d.node('app_cfg', 346, 212, 262, 66, 'config.py · _Config\nSECRET_KEY* · MAX_UPLOAD_MB · OFFLINE · dirs/devices',
           'be', parent='APP', fontsize=8.5)
    d.node('app_sa', 629, 212, 262, 66, 'Flask-SQLAlchemy\ndb.init_app(app)', 'be', parent='APP', fontsize=10)
    d.node('app_login', 911, 212, 262, 66, 'Flask-Login\nlogin_manager · user_loader · unauthorized → 401/redirect',
           'be', parent='APP', fontsize=8.5)
    d.node('app_reg', 1194, 212, 262, 66, 'register_blueprint ×4\nauth · admin · chat · agent',
           'be', parent='APP', fontsize=9.5)

    # ── request lifecycle (cross-cutting) ───────────────────────
    d.container('LC', 40, 346, 1440, 168,
                'Request lifecycle  ·  the only hooks are @login_required (gate) and after_request '
                '— no before_request / teardown', 'be')
    d.node('lc_auth', 64, 392, 310, 70, '① Auth gate\n@login_required → 401 JSON {redirect:"/login"} or HTML redirect',
           'sec', parent='LC', fontsize=9)
    d.node('lc_size', 425, 392, 310, 70, '② Body-size cap\nMAX_CONTENT_LENGTH → 413 RequestEntityTooLarge',
           'be', parent='LC', fontsize=9)
    d.node('lc_handler', 785, 392, 310, 70, '③ Handler (blueprint / app.py)\nownership resolve → service → persist → JSON',
           'be', parent='LC', fontsize=9)
    d.node('lc_after', 1146, 392, 310, 70, '④ after_request\n_no_cache_static ( / · /static · HTML/JS/CSS )',
           'be', parent='LC', fontsize=9)
    d.node('lc_note', 64, 476, 1392, 28,
           'No CSRF protection · no CORS layer · no rate limiter — only mitigation: SameSite=Lax on session / remember cookies',
           'sec', parent='LC', fontsize=9.5)
    d.edge('lc_auth', 'lc_size', color='#3F61A8', srcside='right', dstside='left')
    d.edge('lc_size', 'lc_handler', color='#3F61A8', srcside='right', dstside='left')
    d.edge('lc_handler', 'lc_after', color='#3F61A8', srcside='right', dstside='left')

    # ── blueprints & route groups ───────────────────────────────
    d.container('BP', 40, 542, 1440, 262, 'Blueprints & route groups  (registered at app.py:81-84)', 'be')
    d.table('tbl_auth', 64, 584, 262, 'auth_bp  ·  (root)', [
        ('POST /login · /logout', ''),
        ('GET /api/auth/me', ''),
        ('POST /api/set-lang', 'no auth'),
        ('GET admin users (JSON)', ''),
        ('admin_required decorator', '')], 'be')
    d.table('tbl_admin', 346, 584, 262, 'admin_bp  ·  /admin', [
        ('GET /admin · dashboard', ''),
        ('users: create · reset · toggle · delete', ''),
        ('GET /admin/logs', ''),
        ('GET /admin/files', ''),
        ('@login_required + @admin_required', 'Jinja')], 'be')
    d.table('tbl_app', 629, 584, 262, 'app.py routes  ·  (root)', [
        ('POST /api/upload · /api/read-text', ''),
        ('POST /api/ocr/page · /ocr/all', ''),
        ('POST /api/ocr/reconstruct-region', ''),
        ('POST /api/correct · /translate · /summarize', ''),
        ('GET · DELETE /api/documents[/<id>/…]', ''),
        ('_resolve_owned_file · _safe_basename', '')], 'be')
    d.table('tbl_chat', 911, 584, 262, 'chat_bp  ·  /api/chat/*', [
        ('GET /status', ''),
        ('POST /index · /index/<id>', ''),
        ('POST /send · /cancel', ''),
        ('/conversations [CRUD]', ''),
        ('_owned_conversation / file_ids', '')], 'rag')
    d.table('tbl_agent', 1194, 584, 262, 'agent_bp  ·  /api/agent/*, /agent', [
        ('POST /run · /ingest', ''),
        ('POST /skill/<name>', ''),
        ('GET /tools · /skills · /ocr-engine', ''),
        ('GET /index-status · POST /ensure-indexed', ''),
        ('/conversations [CRUD] · GET /agent', ''),
        ('safe tools (no OCR)', '5'),
        ('chat · knowledge_search · summarize', ''),
        ('translate · correct · max_steps ∈ [1,6]', '()')], 'agent')

    # ── service & persistence layer ─────────────────────────────
    d.container('SVC', 40, 832, 1440, 160,
                'Service & persistence layer  (the backend delegates here; agent/ reuses services through tools)', 'be')
    d.node('svc_ocr', 64, 876, 330, 58, 'services/ — OCR pipeline\nsmart_ocr_service · router · 4 engines',
           'ocr', parent='SVC', fontsize=9.5)
    d.node('svc_ai', 418, 876, 330, 58, 'services/ — AI services\ncorrection · translate · summary · ai_rewrite',
           'ai', parent='SVC', fontsize=9.5)
    d.node('svc_rag', 772, 876, 330, 58, 'services/ — Chat / RAG\nchat_service · EmbeddingEngine · FAISS (in-memory)',
           'rag', parent='SVC', fontsize=9)
    d.node('svc_agent', 1126, 876, 330, 58, 'agent/ — AgentCore · tools · knowledge\nproviders: Groq → Gemini → Local Qwen',
           'agent', parent='SVC', fontsize=9)
    d.node('svc_db', 64, 948, 1392, 40,
           'models.py — ORM + helpers  ·  SQLite paddleocr.db  '
           '(users · documents · document_artifacts · chat_* · agent_* · activity_logs)  ·  save_artifact · log_activity',
           'db', parent='SVC', shape='cyl', fontsize=9)

    # ── spine ───────────────────────────────────────────────────
    d.edge('client', 'APP', color='#6C8EBF', label='HTTP / JSON · cookie session', srcside='bottom', dstside='top')
    d.edge('APP', 'LC', color='#3F61A8', label='every request', srcside='bottom', dstside='top')
    d.edge('LC', 'BP', color='#3F61A8', label='dispatch to handler', srcside='bottom', dstside='top')

    # ── delegation / persistence ────────────────────────────────
    d.edge('tbl_app', 'svc_ocr', color='#0E8088', label='OCR', srcside='left', dstside='top',
           waypoints=[(600, 664), (600, 820), (229, 820)])
    d.edge('tbl_app', 'svc_ai', color='#D79B00', label='correct / translate / summarize',
           srcside='bottom', dstside='top', waypoints=[(760, 806), (583, 806)])
    d.edge('tbl_chat', 'svc_rag', color='#82B366', label='RAG chat', srcside='bottom', dstside='top',
           waypoints=[(1042, 800), (937, 800)])
    d.edge('tbl_agent', 'svc_agent', color='#9673A6', label='agent run', srcside='bottom', dstside='top',
           waypoints=[(1325, 806), (1291, 806)])
    d.edge('tbl_auth', 'svc_db', color='#5A5A5A', dashed=True, label='users · logs',
           srcside='left', dstside='left', waypoints=[(52, 653), (52, 968)])
    d.edge('svc_ocr', 'svc_db', color='#5A5A5A', dashed=True, label='save_artifact', srcside='bottom', dstside='top')
    d.edge('svc_rag', 'svc_db', color='#5A5A5A', dashed=True, srcside='bottom', dstside='top')
    d.edge('svc_agent', 'svc_db', color='#5A5A5A', dashed=True, srcside='bottom', dstside='top')
    return d

ALL = [d_overall, d_ocr, d_lifecycle, d_rag, d_agent, d_erd, d_security, d_chatmodes, d_appendix]
NEW = [d_usecase, d_funcdecomp, d_deployment, d_docchat_seq, d_agent_seq]
NEW2 = [d_ocr_engines, d_correction, d_translation, d_summarization, d_rag_runtime,
        d_agent_exec_flow, d_agent_tools, d_provider_chain]
NEW3 = [d_context, d_dfd1]
NEW4 = [d_backend]

if __name__ == '__main__':
    for fn in ALL + NEW + NEW2 + NEW3 + NEW4:
        write(fn())
    print('done:', len(ALL) + len(NEW) + len(NEW2) + len(NEW3) + len(NEW4), 'diagrams')
