/* OCRCanvas — polygon overlay with hover/click detection */
class OCRCanvas {
  constructor(canvas, img) {
    this.canvas = canvas; this.img = img;
    this.ctx = canvas.getContext('2d');
    this.boxes = []; this.imgW = 1; this.imgH = 1;
    this.hovered = -1; this.selected = -1;
    this.onHover = null; this.onSelect = null;
    this.onRegionSelect = null;

    // Selection mode state
    this.selectionMode = false;
    this.isDragging = false;
    this.startPoint = { x: 0, y: 0 };
    this.currentPoint = { x: 0, y: 0 };

    canvas.addEventListener('mousedown', e => this._down(e));
    canvas.addEventListener('mousemove', e => this._move(e));
    canvas.addEventListener('mouseup', e => this._up(e));
    canvas.addEventListener('mouseleave', () => this._leave());
    canvas.addEventListener('click', e => this._click(e));
  }
  load(boxes, w, h) {
    this.boxes = boxes; this.imgW = w; this.imgH = h;
    this.hovered = -1; this.selected = -1;
    this.resize(); this.draw();
  }
  resize() {
    const r = this.img.getBoundingClientRect();
    this.canvas.width = r.width; this.canvas.height = r.height;
    this.sx = r.width / this.imgW; this.sy = r.height / this.imgH;
  }
  _col(c) {
    if (c >= 0.9) return { s: '#10b981', f: 'rgba(16,185,129,0.15)' };
    if (c >= 0.7) return { s: '#f59e0b', f: 'rgba(245,158,11,0.15)' };
    return { s: '#ef4444', f: 'rgba(239,68,68,0.15)' };
  }
  _drawBox(box, conf, h, s) {
    if (!box) return;
    const pts = box.map(([x, y]) => [x * this.sx, y * this.sy]);
    const col = this._col(conf ?? 0); const ctx = this.ctx;
    ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.closePath();
    ctx.fillStyle = (h || s) ? col.f.replace('0.15', '0.32') : col.f;
    ctx.fill(); ctx.strokeStyle = col.s; ctx.lineWidth = (h || s) ? 2.5 : 1.5; ctx.stroke();
  }
  _drawMarquee() {
    if (!this.isDragging) return;
    const ctx = this.ctx;
    const x = Math.min(this.startPoint.x, this.currentPoint.x);
    const y = Math.min(this.startPoint.y, this.currentPoint.y);
    const w = Math.abs(this.startPoint.x - this.currentPoint.x);
    const h = Math.abs(this.startPoint.y - this.currentPoint.y);

    ctx.setLineDash([5, 5]);
    ctx.strokeStyle = '#3b82f6';
    ctx.lineWidth = 2;
    ctx.strokeRect(x, y, w, h);
    ctx.fillStyle = 'rgba(59, 130, 246, 0.1)';
    ctx.fillRect(x, y, w, h);
    ctx.setLineDash([]);
  }
  draw() {
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    this.boxes.forEach((b, i) => this._drawBox(b.box, b.confidence, i === this.hovered, i === this.selected));
    this._drawMarquee();
  }
  _pip(px, py, box) {
    if (!box) return false;
    const pts = box.map(([x, y]) => [x * this.sx, y * this.sy]);
    let inside = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const [xi, yi] = pts[i], [xj, yj] = pts[j];
      if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  _pos(e) { const r = this.canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
  
  _down(e) {
    if (!this.selectionMode) return;
    this.isDragging = true;
    const [px, py] = this._pos(e);
    this.startPoint = { x: px, y: py };
    this.currentPoint = { x: px, y: py };
  }

  _move(e) {
    const [px, py] = this._pos(e);
    if (this.isDragging) {
      this.currentPoint = { x: px, y: py };
      this.draw();
      return;
    }
    const h = this.boxes.findIndex(b => this._pip(px, py, b.box));
    if (h !== this.hovered) { this.hovered = h; this.draw(); }
    if (this.onHover) this.onHover(h, e);
  }

  _up(e) {
    if (!this.isDragging) return;
    this.isDragging = false;
    
    const x1 = Math.min(this.startPoint.x, this.currentPoint.x) / this.sx;
    const y1 = Math.min(this.startPoint.y, this.currentPoint.y) / this.sy;
    const x2 = Math.max(this.startPoint.x, this.currentPoint.x) / this.sx;
    const y2 = Math.max(this.startPoint.y, this.currentPoint.y) / this.sy;

    this.draw();
    if (this.onRegionSelect && Math.abs(x2 - x1) > 5 && Math.abs(y2 - y1) > 5) {
      this.onRegionSelect({ x1, y1, x2, y2 });
    }
  }

  _leave() { this.isDragging = false; this.hovered = -1; this.draw(); if (this.onHover) this.onHover(-1, null); }
  _click(e) {
    if (this.selectionMode) return;
    const [px, py] = this._pos(e);
    const i = this.boxes.findIndex(b => this._pip(px, py, b.box));
    if (i !== -1) { this.selected = i; this.draw(); if (this.onSelect) this.onSelect(i); }
  }
  setSelectionMode(enabled) {
    this.selectionMode = enabled;
    this.canvas.style.cursor = enabled ? 'crosshair' : 'default';
  }
  selectByIndex(i) { this.selected = i; this.draw(); }
}
