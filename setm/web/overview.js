// The landing page: what a chief engineer or an executive needs in one screen.
//
// Four blocks, each answering one question -- is it healthy, what is off target,
// which gate is at risk, what are the top risks. Everything here is already in
// the KPI report or the loaded graph, so this page adds no new API surface; its
// job is ordering and emphasis, not new numbers. The problems lead: the KPI tab
// still holds the full set for anyone who wants it.

import { h } from './forms.js';
import { bar, collectGaps, pageHead } from './views.js';

const BAND_WORD = { good: 'on track', watch: 'needs attention', poor: 'off target' };
//: Worst first. The whole point of this page is that bad news is not buried.
const BAND_RANK = { poor: 0, watch: 1, good: 2, unknown: 3 };

export function renderOverview(container, report, risks, actions) {
  container.replaceChildren(
    pageHead(
      report.project?.name || 'Programme overview',
      'Where the programme stands right now, measured from the graph itself. Every number links '
      + 'to the elements behind it.',
    ),
  );

  const measured = (report.kpis || []).filter((k) => k.available);
  const offTarget = measured
    .filter((k) => k.band === 'poor' || k.band === 'watch')
    .sort((a, b) => BAND_RANK[a.band] - BAND_RANK[b.band]);

  container.append(healthBlock(report, measured, offTarget));
  container.append(attentionBlock(offTarget, measured.length, actions));
  container.append(gateBlock(report.breakdowns?.by_milestone || [], actions));
  if (risks.length) container.append(riskBlock(risks, actions));
}

/** The headline: one number, and what it means in words. */
function healthBlock(report, measured, offTarget) {
  const score = report.health_score || {};
  const band = score.band || 'unknown';
  const verdict = offTarget.length
    ? `${offTarget.length} of ${measured.length} measures ${offTarget.length === 1 ? 'is' : 'are'} below target`
    : `All ${measured.length} measures are on target`;

  return h('div', { class: 'ov-hero' }, [
    h('div', {}, [
      h('div', { class: `score-number ${band}`, text: score.value ?? '—' }),
      h('div', { class: 'muted', style: 'font-size:11px;text-align:center', text: 'of 100' }),
    ]),
    h('div', {}, [
      h('h2', { class: 'ov-verdict', text: `Traceability health: ${BAND_WORD[band] || band}` }),
      h('p', { class: 'ov-sub', text: verdict }),
    ]),
  ]);
}

/** What is wrong, worst first, with the elements responsible one click away. */
function attentionBlock(offTarget, measuredCount, actions) {
  const card = h('div', { class: 'card' });
  card.append(h('div', { class: 'card-head' }, [h('h3', { text: 'Needs attention' })]));

  if (!offTarget.length) {
    card.append(h('p', { class: 'muted', text: 'Nothing is below target.' }));
    return card;
  }

  for (const kpi of offTarget) {
    const row = h('div', { class: `ov-row ${kpi.band}` });
    row.append(h('div', { class: 'ov-row-main' }, [
      h('div', { class: 'ov-row-name', text: kpi.name }),
      h('div', { class: 'ov-row-detail', text: kpi.description || '' }),
    ]));
    row.append(h('div', { class: 'ov-row-figure' }, [
      h('div', { class: `ov-figure ${kpi.band}`, text: `${kpi.value}${kpi.unit}` }),
      h('div', { class: 'ov-target', text: `target ${kpi.direction === 'lower_better' ? '≤' : '≥'} ${kpi.target}${kpi.unit}` }),
    ]));

    const gaps = collectGaps(kpi);
    if (gaps.length) {
      const details = h('details', { class: 'ov-gaps' }, [
        h('summary', { text: `${gaps.length} to fix` }),
      ]);
      const list = h('ul');
      for (const gap of gaps.slice(0, 25)) {
        list.append(h('li', { onClick: () => actions.onOpen(gap.id) }, [
          gap.label,
          h('span', { class: 'muted', style: 'font-size:11px', text: ` ${gap.type}` }),
        ]));
      }
      details.append(list);
      row.append(details);
    }
    card.append(row);
  }

  const onTarget = measuredCount - offTarget.length;
  if (onTarget > 0) {
    card.append(h('p', { class: 'ov-ontarget' }, [
      `${onTarget} other measure${onTarget === 1 ? '' : 's'} on target — see the KPIs tab for the full set.`,
    ]));
  }
  return card;
}

/** One compact row per gate rather than five expanded activity tables. */
function gateBlock(milestones, actions) {
  const card = h('div', { class: 'card' });
  card.append(h('div', { class: 'card-head' }, [
    h('h3', { text: 'Gate readiness' }),
    h('span', { class: 'muted', text: 'share of committed activities already done' }),
  ]));

  if (!milestones.length) {
    card.append(h('p', { class: 'muted', text: 'No milestones defined yet.' }));
    return card;
  }

  for (const gate of milestones) {
    const percent = gate.readiness_percent ?? 0;
    const band = percent >= 80 ? 'good' : percent >= 40 ? 'watch' : 'poor';
    card.append(h('div', { class: 'ov-gate clickable', onClick: () => actions.onOpen(gate.id) }, [
      h('div', { class: 'ov-gate-name' }, [
        gate.label,
        gate.gate ? h('span', { class: 'tag', text: gate.gate }) : null,
      ]),
      h('div', { class: 'ov-gate-bar' }, [bar(percent, band)]),
      h('div', { class: 'ov-gate-figure', text: `${percent}%` }),
      h('div', { class: 'ov-gate-counts muted', text: `${gate.activity_count} act · ${gate.deliverable_count} del` }),
    ]));
  }
  return card;
}

/** Open risks, worst exposure first -- the question no other page answers. */
function riskBlock(risks, actions) {
  const card = h('div', { class: 'card' });
  card.append(h('div', { class: 'card-head' }, [
    h('h3', { text: 'Top risks' }),
    h('span', { class: 'muted', text: 'likelihood × severity' }),
  ]));

  for (const risk of risks) {
    card.append(h('div', { class: 'ov-risk clickable', onClick: () => actions.onOpen(risk.id) }, [
      h('div', { class: `ov-exposure ${risk.band}`, text: risk.exposure }),
      h('div', { class: 'ov-risk-name', text: risk.label }),
      h('span', { class: 'tag', text: (risk.status || 'open').replace(/_/g, ' ') }),
    ]));
  }
  return card;
}

/** Rank risks by exposure straight from the loaded graph -- no extra request. */
export function topRisks(nodes, ontology, limit = 5) {
  const riskType = ontology.roles?.risk;
  if (!riskType) return [];
  return nodes
    .filter((node) => node.type === riskType)
    .map((node) => {
      const likelihood = Number(node.properties?.likelihood) || 0;
      const severity = Number(node.properties?.severity) || 0;
      const exposure = likelihood * severity;
      return {
        id: node.id,
        label: node.label,
        status: node.properties?.risk_status,
        exposure,
        band: exposure >= 12 ? 'poor' : exposure >= 6 ? 'watch' : 'good',
      };
    })
    // A retired risk is history, not something to put in front of an executive.
    .filter((risk) => risk.status !== 'retired')
    .sort((a, b) => b.exposure - a.exposure)
    .slice(0, limit);
}
