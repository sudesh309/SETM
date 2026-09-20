// Canvas graph view: force-directed layout, pan/zoom, selection and hover.
//
// Written from scratch rather than pulling in a graph library so the tool stays
// a single offline-capable download with no CDN and no build step. Repulsion
// uses a spatial grid instead of the naive all-pairs loop, which keeps the
// layout interactive into the low thousands of elements.

const REPULSION = 14000;
const SPRING = 0.028;
const SPRING_LENGTH = 165;
const DAMPING = 0.84;
const CENTRE_PULL = 0.0014;
const MIN_ALPHA = 0.008;
//: Repulsion only reaches neighbouring cells, so this is effectively the force's
//: cut-off radius. It has to exceed SPRING_LENGTH or clusters collapse inward.
const GRID_CELL = 280;
//: Iterations run before the first paint, so the graph appears settled rather
//: than exploding outward while the user watches.
const WARMUP_STEPS = 220;
//: Relation line width multiplier per weight.
const WEIGHT_WIDTH = { high: 1.5, medium: 1, low: 0.6 };

export class GraphView {
  constructor(canvas, { onSelect, onHover, onBackground } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.onSelect = onSelect || (() => {});
    this.onHover = onHover || (() => {});
    this.onBackground = onBackground || (() => {});

    this.nodes = [];
    this.edges = [];
    this.byId = new Map();
    this.selectedId = null;
    this.hoverId = null;
    this.showLabels = true;
    this.adjacency = new Map();

    this.scale = 1;
    this.offsetX = 0;
    this.offsetY = 0;
    this.alpha = 1;
    this.running = false;
    this.pinned = new Set();

    this._bindEvents();
    this._resize();
    window.addEventListener('resize', () => this._resize());
  }

  // ---------------------------------------------------------------- data
  setData(nodes, edges, { keepPositions = true } = {}) {
    const previous = keepPositions ? this.byId : new Map();
    const width = this.canvas.clientWidth || 900;
    const height = this.canvas.clientHeight || 600;

    this.nodes = nodes.map((node, index) => {
      const old = previous.get(node.id);
      if (old) return Object.assign(old, node, { vx: old.vx, vy: old.vy });
      // Seed on a spiral: better starting spread than pure random, so the
      // layout settles in fewer iterations.
      const angle = index * 2.399;
      const radius = 24 * Math.sqrt(index + 1);
      return {
        ...node,
        x: width / 2 + radius * Math.cos(angle),
        y: height / 2 + radius * Math.sin(angle),
        vx: 0,
        vy: 0,
      };
    });

    this.byId = new Map(this.nodes.map((n) => [n.id, n]));
    this.edges = edges.filter((e) => this.byId.has(e.source) && this.byId.has(e.target));

    this.adjacency = new Map();
    for (const edge of this.edges) {
      if (!this.adjacency.has(edge.source)) this.adjacency.set(edge.source, new Set());
      if (!this.adjacency.has(edge.target)) this.adjacency.set(edge.target, new Set());
      this.adjacency.get(edge.source).add(edge.target);
      this.adjacency.get(edge.target).add(edge.source);
    }

    this.alpha = 1;
    this._warmup();
    this._start();
  }

  /** Settle the layout off-screen before the first paint. */
  _warmup() {
    const budget = this.nodes.length > 1200 ? 60 : WARMUP_STEPS;
    for (let i = 0; i < budget; i += 1) this._step();
    this.alpha = 0.22;
  }

  select(id) {
    this.selectedId = id;
    this._draw();
  }

  setShowLabels(value) {
    this.showLabels = value;
    this._draw();
  }

  relayout() {
    this.pinned.clear();
    const width = this.canvas.clientWidth || 900;
    const height = this.canvas.clientHeight || 600;
    this.nodes.forEach((node, index) => {
      const angle = index * 2.399;
      const radius = 24 * Math.sqrt(index + 1);
      node.x = width / 2 + radius * Math.cos(angle);
      node.y = height / 2 + radius * Math.sin(angle);
      node.vx = node.vy = 0;
    });
    this.alpha = 1;
    this._start();
  }

  // ------------------------------------------------------------- physics
  _step() {
    const alpha = this.alpha;

    // Repulsion, limited to neighbouring grid cells.
    const grid = new Map();
    for (const node of this.nodes) {
      const key = `${Math.floor(node.x / GRID_CELL)}:${Math.floor(node.y / GRID_CELL)}`;
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push(node);
    }
    for (const node of this.nodes) {
      const cellX = Math.floor(node.x / GRID_CELL);
      const cellY = Math.floor(node.y / GRID_CELL);
      for (let dx = -1; dx <= 1; dx += 1) {
        for (let dy = -1; dy <= 1; dy += 1) {
          const bucket = grid.get(`${cellX + dx}:${cellY + dy}`);
          if (!bucket) continue;
          for (const other of bucket) {
            if (other === node) continue;
            let deltaX = node.x - other.x;
            let deltaY = node.y - other.y;
            let distanceSquared = deltaX * deltaX + deltaY * deltaY;
            if (distanceSquared < 0.01) {
              // Identical positions would divide by zero; nudge them apart.
              deltaX = (Math.random() - 0.5) * 2;
              deltaY = (Math.random() - 0.5) * 2;
              distanceSquared = 1;
            }
            if (distanceSquared > GRID_CELL * GRID_CELL * 4) continue;
            const force = (REPULSION * alpha) / distanceSquared;
            const distance = Math.sqrt(distanceSquared);
            node.vx += (deltaX / distance) * force;
            node.vy += (deltaY / distance) * force;
          }
        }
      }
    }

    // Springs.
    for (const edge of this.edges) {
      const a = this.byId.get(edge.source);
      const b = this.byId.get(edge.target);
      const deltaX = b.x - a.x;
      const deltaY = b.y - a.y;
      const distance = Math.hypot(deltaX, deltaY) || 1;
      const force = (distance - SPRING_LENGTH) * SPRING * alpha;
      const fx = (deltaX / distance) * force;
      const fy = (deltaY / distance) * force;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }

    // Gentle pull to the middle keeps disconnected clusters on screen.
    const centreX = (this.canvas.clientWidth || 900) / 2;
    const centreY = (this.canvas.clientHeight || 600) / 2;
    for (const node of this.nodes) {
      if (this.pinned.has(node.id) || node === this.dragNode) { node.vx = node.vy = 0; continue; }
      node.vx += (centreX - node.x) * CENTRE_PULL * alpha;
      node.vy += (centreY - node.y) * CENTRE_PULL * alpha;
      node.vx *= DAMPING;
      node.vy *= DAMPING;
      node.x += Math.max(-30, Math.min(30, node.vx));
      node.y += Math.max(-30, Math.min(30, node.vy));
    }

    this.alpha *= 0.972;
  }

  _start() {
    if (this.running) return;
    this.running = true;
    const tick = () => {
      if (this.alpha > MIN_ALPHA) {
        this._step();
        this._draw();
        requestAnimationFrame(tick);
      } else {
        this.running = false;
        this._draw();
      }
    };
    requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------ rendering
  _resize() {
    const ratio = window.devicePixelRatio || 1;
    const width = this.canvas.clientWidth;
    const height = this.canvas.clientHeight;
    this.canvas.width = Math.max(1, Math.floor(width * ratio));
    this.canvas.height = Math.max(1, Math.floor(height * ratio));
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    this._draw();
  }

  _styles() {
    const styles = getComputedStyle(document.documentElement);
    return {
      text: styles.getPropertyValue('--text').trim(),
      dim: styles.getPropertyValue('--text-faint').trim(),
      border: styles.getPropertyValue('--border-strong').trim(),
      accent: styles.getPropertyValue('--accent').trim(),
      panel: styles.getPropertyValue('--bg-raised').trim(),
    };
  }

  _draw() {
    const ctx = this.ctx;
    const width = this.canvas.clientWidth;
    const height = this.canvas.clientHeight;
    const theme = this._styles();
    ctx.clearRect(0, 0, width, height);
    ctx.save();
    ctx.translate(this.offsetX, this.offsetY);
    ctx.scale(this.scale, this.scale);

    const focusSet = this._focusSet();

    for (const edge of this.edges) {
      const a = this.byId.get(edge.source);
      const b = this.byId.get(edge.target);
      const active = !focusSet || (focusSet.has(edge.source) && focusSet.has(edge.target));
      ctx.globalAlpha = active ? 0.75 : 0.1;
      ctx.strokeStyle = edge.color || theme.border;
      // Weight reads as line thickness: the heavy links stand out at a glance
      // without needing the legend.
      ctx.lineWidth = (active && focusSet ? 1.9 : 1.2) * (WEIGHT_WIDTH[edge.weight] ?? 1);
      ctx.setLineDash(edge.style === 'dashed' ? [5, 4] : []);
      this._drawArrow(a, b, this._radius(b));
    }
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;

    for (const node of this.nodes) {
      const active = !focusSet || focusSet.has(node.id);
      const radius = this._radius(node);
      ctx.globalAlpha = active ? 1 : 0.16;
      ctx.beginPath();
      this._shapePath(node, radius);
      ctx.fillStyle = node.color || '#6b7fd7';
      ctx.fill();

      if (node.id === this.selectedId || node.id === this.hoverId) {
        ctx.lineWidth = node.id === this.selectedId ? 3 : 2;
        ctx.strokeStyle = node.id === this.selectedId ? theme.text : theme.accent;
        ctx.stroke();
      }
    }

    if (this.showLabels) this._drawLabels(theme, focusSet);

    ctx.globalAlpha = 1;
    ctx.restore();
  }

  /** Draw as many labels as fit without overlapping, most important first.
   *
   *  A dense engineering graph has far more labels than legible space. Rather
   *  than shrink them all into illegibility, place them greedily -- selection,
   *  hover and the best-connected elements win -- and drop any that would
   *  collide with one already placed. Zooming in frees space and reveals more.
   */
  _drawLabels(theme, focusSet) {
    const ctx = this.ctx;
    const fontSize = 11 / Math.max(0.55, Math.min(1.5, this.scale));
    ctx.font = `${fontSize}px system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';

    const priority = (node) => {
      if (node.id === this.selectedId) return 1e9;
      if (node.id === this.hoverId) return 1e8;
      return (this.adjacency.get(node.id) || new Set()).size;
    };
    const ordered = [...this.nodes]
      .filter((node) => !focusSet || focusSet.has(node.id))
      .sort((a, b) => priority(b) - priority(a));

    const placed = [];
    const padding = 3;
    for (const node of ordered) {
      const always = node.id === this.selectedId || node.id === this.hoverId;
      const text = node.label.length > 24 ? `${node.label.slice(0, 23)}…` : node.label;
      const width = ctx.measureText(text).width;
      const height = fontSize + 3;
      const radius = this._radius(node);
      const box = {
        left: node.x - width / 2 - padding,
        right: node.x + width / 2 + padding,
        top: node.y + radius + 3,
        bottom: node.y + radius + 3 + height,
      };
      const collides = placed.some(
        (other) => box.left < other.right && box.right > other.left
          && box.top < other.bottom && box.bottom > other.top,
      );
      if (collides && !always) continue;
      placed.push(box);

      ctx.globalAlpha = 0.86;
      ctx.fillStyle = theme.panel;
      ctx.fillRect(box.left, box.top, box.right - box.left, height);
      ctx.globalAlpha = 1;
      ctx.fillStyle = always ? theme.accent : theme.text;
      ctx.fillText(text, node.x, box.top + 1);
    }
  }

  _focusSet() {
    if (!this.selectedId || !this.focusMode) return null;
    const set = new Set([this.selectedId]);
    let frontier = new Set([this.selectedId]);
    for (let depth = 0; depth < (this.focusDepth || 1); depth += 1) {
      const next = new Set();
      for (const id of frontier) {
        for (const neighbour of this.adjacency.get(id) || []) {
          if (!set.has(neighbour)) { set.add(neighbour); next.add(neighbour); }
        }
      }
      frontier = next;
    }
    return set;
  }

  _radius(node) {
    const degree = (this.adjacency.get(node.id) || new Set()).size;
    return 7 + Math.min(9, Math.sqrt(degree) * 2.6);
  }

  _shapePath(node, radius) {
    const ctx = this.ctx;
    const { x, y } = node;
    switch (node.shape) {
      case 'rectangle':
        ctx.rect(x - radius * 1.25, y - radius * 0.82, radius * 2.5, radius * 1.64);
        break;
      case 'diamond':
        ctx.moveTo(x, y - radius * 1.25);
        ctx.lineTo(x + radius * 1.25, y);
        ctx.lineTo(x, y + radius * 1.25);
        ctx.lineTo(x - radius * 1.25, y);
        ctx.closePath();
        break;
      case 'hexagon': {
        for (let i = 0; i < 6; i += 1) {
          const angle = (Math.PI / 3) * i - Math.PI / 6;
          const px = x + radius * 1.15 * Math.cos(angle);
          const py = y + radius * 1.15 * Math.sin(angle);
          if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
        }
        ctx.closePath();
        break;
      }
      default:
        ctx.arc(x, y, radius, 0, Math.PI * 2);
    }
  }

  _drawArrow(a, b, targetRadius) {
    const ctx = this.ctx;
    const angle = Math.atan2(b.y - a.y, b.x - a.x);
    const endX = b.x - Math.cos(angle) * (targetRadius + 3);
    const endY = b.y - Math.sin(angle) * (targetRadius + 3);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(endX, endY);
    ctx.stroke();

    const head = 7;
    ctx.beginPath();
    ctx.moveTo(endX, endY);
    ctx.lineTo(endX - head * Math.cos(angle - 0.4), endY - head * Math.sin(angle - 0.4));
    ctx.lineTo(endX - head * Math.cos(angle + 0.4), endY - head * Math.sin(angle + 0.4));
    ctx.closePath();
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fill();
  }

  // ---------------------------------------------------------- interaction
  _toWorld(clientX, clientY) {
    const rect = this.canvas.getBoundingClientRect();
    return {
      x: (clientX - rect.left - this.offsetX) / this.scale,
      y: (clientY - rect.top - this.offsetY) / this.scale,
    };
  }

  _nodeAt(clientX, clientY) {
    const point = this._toWorld(clientX, clientY);
    for (let i = this.nodes.length - 1; i >= 0; i -= 1) {
      const node = this.nodes[i];
      const radius = this._radius(node) + 4;
      if (Math.hypot(node.x - point.x, node.y - point.y) <= radius) return node;
    }
    return null;
  }

  _bindEvents() {
    let panning = false;
    let startX = 0;
    let startY = 0;
    let moved = false;

    this.canvas.addEventListener('mousedown', (event) => {
      const node = this._nodeAt(event.clientX, event.clientY);
      moved = false;
      if (node) {
        this.dragNode = node;
        this.pinned.add(node.id);
      } else {
        panning = true;
        startX = event.clientX - this.offsetX;
        startY = event.clientY - this.offsetY;
        this.canvas.classList.add('dragging');
      }
    });

    window.addEventListener('mousemove', (event) => {
      if (this.dragNode) {
        const point = this._toWorld(event.clientX, event.clientY);
        this.dragNode.x = point.x;
        this.dragNode.y = point.y;
        this.dragNode.vx = this.dragNode.vy = 0;
        moved = true;
        this.alpha = Math.max(this.alpha, 0.14);
        this._start();
        return;
      }
      if (panning) {
        this.offsetX = event.clientX - startX;
        this.offsetY = event.clientY - startY;
        moved = true;
        this._draw();
        return;
      }
      const node = this._nodeAt(event.clientX, event.clientY);
      const id = node ? node.id : null;
      if (id !== this.hoverId) {
        this.hoverId = id;
        this.canvas.style.cursor = node ? 'pointer' : 'grab';
        this._draw();
        this.onHover(node, event);
      } else if (node) {
        this.onHover(node, event);
      }
    });

    window.addEventListener('mouseup', (event) => {
      if (this.dragNode && !moved) this.onSelect(this.dragNode);
      else if (panning && !moved) this.onBackground();
      this.dragNode = null;
      panning = false;
      this.canvas.classList.remove('dragging');
    });

    this.canvas.addEventListener('wheel', (event) => {
      event.preventDefault();
      const rect = this.canvas.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      const mouseY = event.clientY - rect.top;
      const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
      this.zoomAt(mouseX, mouseY, factor);
    }, { passive: false });

    this.canvas.addEventListener('dblclick', (event) => {
      const node = this._nodeAt(event.clientX, event.clientY);
      if (node) { this.pinned.delete(node.id); this.alpha = 0.4; this._start(); }
    });
  }

  zoomAt(x, y, factor) {
    const next = Math.max(0.15, Math.min(4, this.scale * factor));
    const ratio = next / this.scale;
    this.offsetX = x - (x - this.offsetX) * ratio;
    this.offsetY = y - (y - this.offsetY) * ratio;
    this.scale = next;
    this._draw();
  }

  zoom(factor) {
    this.zoomAt(this.canvas.clientWidth / 2, this.canvas.clientHeight / 2, factor);
  }

  fit(padding = 60) {
    if (!this.nodes.length) return;
    const xs = this.nodes.map((n) => n.x);
    const ys = this.nodes.map((n) => n.y);
    const minX = Math.min(...xs); const maxX = Math.max(...xs);
    const minY = Math.min(...ys); const maxY = Math.max(...ys);
    const width = this.canvas.clientWidth - padding * 2;
    const height = this.canvas.clientHeight - padding * 2;
    this.scale = Math.max(0.15, Math.min(2.2, Math.min(width / (maxX - minX || 1), height / (maxY - minY || 1))));
    this.offsetX = padding + (width - (maxX - minX) * this.scale) / 2 - minX * this.scale;
    this.offsetY = padding + (height - (maxY - minY) * this.scale) / 2 - minY * this.scale;
    this._draw();
  }

  centreOn(id) {
    const node = this.byId.get(id);
    if (!node) return;
    this.offsetX = this.canvas.clientWidth / 2 - node.x * this.scale;
    this.offsetY = this.canvas.clientHeight / 2 - node.y * this.scale;
    this._draw();
  }
}
