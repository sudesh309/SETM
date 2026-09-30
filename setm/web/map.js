// The Dashboard map: a clear, structured view of the project.
//
// Instead of a force-directed network (everything connected to everything,
// labels piled on top of each other), elements sit in five fixed columns --
// Why, What, How, Who, When -- as readable cards. With nothing focused there
// are no lines at all; hovering a card draws just its own links. Clicking a
// card focuses the map on it: only it and its neighbours (depth 1 or 2) stay,
// with the relations between them drawn, and each neighbour card saying which
// relation links it in.

import { h } from './forms.js';

const LANES = ['Why', 'What', 'How', 'Who', 'When'];
const SVG = 'http://www.w3.org/2000/svg';

export class MapView {
  /**
   * @param container  element to render into
   * @param callbacks  {onSelect(id), onClear()}
   */
  constructor(container, { onSelect, onClear } = {}) {
    this.container = container;
    this.onSelect = onSelect || (() => {});
    this.onClear = onClear || (() => {});
    this.nodes = [];
    this.edges = [];
    this.totalNodes = 0;
    this.focusId = null;
    this.depth = 1;
    this.history = [];
    this.hoverId = null;

    this.bar = h('div', { class: 'map-bar' });
    this.grid = h('div', { class: 'map-grid' });
    this.svg = document.createElementNS(SVG, 'svg');
    this.svg.setAttribute('class', 'map-links');
    this.scroller = h('div', { class: 'map-scroll' }, [this.grid]);
    this.grid.append(this.svg);
    container.replaceChildren(this.bar, this.scroller);

    this._resizeObserver = new ResizeObserver(() => this._drawLinks());
    this._resizeObserver.observe(this.scroller);
  }

  /** nodes: [{id, label, type, type_label, color, category, status}], edges: [{id, source, target, label, color}] */
  setData(nodes, edges, totalNodes = nodes.length) {
    this.nodes = nodes;
    this.edges = edges;
    this.totalNodes = totalNodes;
    this.byId = new Map(nodes.map((n) => [n.id, n]));
    if (this.focusId && !this.byId.has(this.focusId)) this.focusId = null;
    this.render();
  }

  /** Focus on an element (and remember where we came from, for Back). */
  focus(id, { remember = true } = {}) {
    if (!id || !this.byId?.has(id)) return;
    if (remember && this.focusId && this.focusId !== id) this.history.push(this.focusId);
    this.focusId = id;
    this.render();
    this._scrollIntoView(id);
  }

  clearFocus() {
    this.focusId = null;
    this.history = [];
    this.render();
    this.onClear();
  }

  back() {
    const previous = this.history.pop();
    if (previous) {
      this.focus(previous, { remember: false });
      this.onSelect(previous);
    } else {
      this.clearFocus();
    }
  }

  setDepth(depth) {
    this.depth = depth;
    this.render();
  }

  // ------------------------------------------------------------------ model
  _neighbourhood() {
    if (!this.focusId) return null;
    const distance = new Map([[this.focusId, 0]]);
    // How each neighbour was reached: the relation and the element on the other end.
    this.via = new Map();
    let frontier = [this.focusId];
    for (let step = 1; step <= this.depth; step += 1) {
      const next = [];
      for (const edge of this.edges) {
        for (const [from, to] of [[edge.source, edge.target], [edge.target, edge.source]]) {
          if (frontier.includes(from) && !distance.has(to) && this.byId.has(to)) {
            distance.set(to, step);
            this.via.set(to, { edge, from });
            next.push(to);
          }
        }
      }
      frontier = next;
    }
    return distance;
  }

  // ----------------------------------------------------------------- render
  render() {
    const distance = this._neighbourhood();
    const visible = distance ? this.nodes.filter((n) => distance.has(n.id)) : this.nodes;
    this.visibleIds = new Set(visible.map((n) => n.id));
    this._renderBar(visible.length);

    const lanes = [...LANES];
    if (visible.some((n) => !LANES.includes(n.category))) lanes.push('Other');
    this.grid.style.setProperty('--lanes', lanes.length);
    this.cards = new Map();
    const columns = lanes.map((lane) => {
      const members = visible
        .filter((n) => (LANES.includes(n.category) ? n.category : 'Other') === lane)
        .sort((a, b) => (distance ? distance.get(a.id) - distance.get(b.id) : 0)
          || a.type_label.localeCompare(b.type_label) || a.label.localeCompare(b.label));
      const body = h('div', { class: 'lane-body' });
      for (const node of members) body.append(this._card(node, distance));
      if (!members.length) body.append(h('div', { class: 'lane-empty', text: distance ? '—' : 'Nothing here yet' }));
      return h('section', { class: `lane lane-${lane.toLowerCase()}` }, [
        h('header', { class: 'lane-head' }, [
          h('span', { class: 'lane-name', text: lane }),
          h('span', { class: 'lane-count', text: members.length }),
        ]),
        body,
      ]);
    });
    this.grid.replaceChildren(this.svg, ...columns);
    requestAnimationFrame(() => this._drawLinks());
  }

  _renderBar(shown) {
    const focused = this.focusId ? this.byId.get(this.focusId) : null;
    const depthButtons = [1, 2].map((d) => h('button', {
      class: `seg${this.depth === d ? ' on' : ''}`,
      'data-depth': d,
      text: d === 1 ? 'Direct links' : '2 steps',
      onClick: () => this.setDepth(d),
    }));
    this.bar.replaceChildren(
      focused
        ? h('div', { class: 'map-status' }, [
          h('button', { class: 'btn btn-small', id: 'map-back', text: '◀ Back', onClick: () => this.back() }),
          h('span', {}, ['Focused on ', h('strong', { text: focused.label })]),
          h('span', { class: 'muted', id: 'map-shown', text: `showing ${shown} of ${this.totalNodes}` }),
          h('button', { class: 'btn btn-small', id: 'map-show-all', text: 'Show all ✕', onClick: () => this.clearFocus() }),
        ])
        : h('div', { class: 'map-status' }, [
          h('span', { id: 'map-shown', text: `${shown} of ${this.totalNodes} elements` }),
          h('span', { class: 'muted', text: 'Click an element to focus on it and its links · hover to preview' }),
        ]),
      h('div', { class: 'seg-group', title: 'How far from the focused element to show' }, depthButtons),
    );
  }

  _card(node, distance) {
    const card = h('button', {
      class: `map-card${node.id === this.focusId ? ' focused' : ''}${distance && distance.get(node.id) === 2 ? ' far' : ''}`,
      'data-id': node.id,
      style: `--card-colour:${node.color}`,
      title: `${node.type_label}: ${node.label}${node.status ? ` (${node.status})` : ''}\nClick to focus · double-click to open`,
      onClick: () => {
        this.focus(node.id);
        this.onSelect(node.id);
      },
      onMouseenter: () => { this.hoverId = node.id; this._drawLinks(); },
      onMouseleave: () => { this.hoverId = null; this._drawLinks(); },
    }, [
      this._viaTag(node, distance),
      h('span', { class: 'map-card-label', text: node.label }),
      h('span', { class: 'map-card-meta' }, [
        h('span', { text: node.type_label }),
        node.status ? h('span', { class: 'map-card-status', text: node.status.replace(/_/g, ' ') }) : null,
      ]),
    ]);
    this.cards.set(node.id, card);
    return card;
  }

  /** In focus mode, the relation that links a card to the element it was reached from. */
  _viaTag(node, distance) {
    const via = distance && this.via?.get(node.id);
    if (!via) return null;
    const other = this.byId.get(via.from);
    const outgoing = via.edge.source === node.id;
    const [subject, object] = outgoing ? [node, other] : [other, node];
    // Next to the focused element its name goes without saying; two steps out it does not.
    const name = via.from === this.focusId ? '' : ` ${other.label}`;
    return h('span', {
      class: 'map-card-via',
      title: `${subject.label} ${via.edge.label} ${object.label}`,
      text: outgoing ? `${via.edge.label}\u00a0→${name}` : `←${name}\u00a0${via.edge.label}`,
    });
  }

  _scrollIntoView(id) {
    requestAnimationFrame(() => this.cards?.get(id)?.scrollIntoView({ block: 'nearest', inline: 'nearest' }));
  }

  // ------------------------------------------------------------------ links
  _drawLinks() {
    if (!this.cards) return;
    const svg = this.svg;
    while (svg.firstChild) svg.firstChild.remove();
    for (const card of this.cards.values()) card.classList.remove('linked', 'dim');

    // Without focus, draw only the hovered card's links: never a tangle.
    const anchor = this.focusId || this.hoverId;
    if (!anchor) return;
    const edges = this.edges.filter((e) => this.visibleIds.has(e.source) && this.visibleIds.has(e.target)
      && (this.focusId ? true : (e.source === anchor || e.target === anchor)));
    if (!this.focusId) {
      const linked = new Set(edges.flatMap((e) => [e.source, e.target]));
      for (const [id, card] of this.cards) {
        card.classList.toggle('linked', linked.has(id) && id !== anchor);
        card.classList.toggle('dim', !linked.has(id) && id !== anchor);
      }
    }

    const origin = this.grid.getBoundingClientRect();
    svg.setAttribute('width', this.grid.scrollWidth);
    svg.setAttribute('height', this.grid.scrollHeight);
    const box = (id) => {
      const r = this.cards.get(id)?.getBoundingClientRect();
      return r && { left: r.left - origin.left, right: r.right - origin.left, top: r.top - origin.top, mid: r.top - origin.top + r.height / 2 };
    };
    for (const edge of edges) {
      const a = box(edge.source);
      const b = box(edge.target);
      if (!a || !b) continue;
      let d;
      if (Math.abs(a.left - b.left) < 4) {
        // Same column: an arc bowing out to the right.
        const x = a.right;
        const bow = 26 + Math.min(60, Math.abs(a.mid - b.mid) / 6);
        d = `M${x},${a.mid} C${x + bow},${a.mid} ${x + bow},${b.mid} ${x},${b.mid}`;
      } else {
        const [from, to] = a.left < b.left ? [a, b] : [b, a];
        const x1 = from.right;
        const x2 = to.left;
        const y1 = from === a ? a.mid : b.mid;
        const y2 = to === b ? b.mid : a.mid;
        const dx = Math.max(30, (x2 - x1) / 2);
        d = `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
      }
      const path = document.createElementNS(SVG, 'path');
      path.setAttribute('d', d);
      path.setAttribute('class', 'map-link');
      path.style.stroke = edge.color || 'var(--text-faint)';
      const title = document.createElementNS(SVG, 'title');
      title.textContent = edge.label;
      path.append(title);
      svg.append(path);
    }
  }
}
