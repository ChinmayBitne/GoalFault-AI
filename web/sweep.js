'use strict';
// Pressure sweep panel. Uses $, node, call, write, toast, load and pressureLabel from app.js.

let sweepDomain = null;
let sweepList = [];

async function loadSweeps(domain) {
  sweepDomain = domain;
  try {
    const [scenarios, sweeps] = await Promise.all([
      call(`/api/scenarios?domain=${encodeURIComponent(domain)}`),
      call('/api/sweeps'),
    ]);
    if (domain !== sweepDomain) return;
    const approved = scenarios.filter(s => s.status === 'approved');
    const select = $('sweepScenario');
    const keep = select.value;
    select.replaceChildren(...approved.map(s => { const o = node('option', '', `${s.id} · ${s.title}`); o.value = s.id; return o; }));
    if (approved.some(s => s.id === keep)) select.value = keep;
    $('sweepNote').textContent = approved.length ? '' : 'Approve a scenario in the studio first.';
    const shown = $('sweepPick').value;
    sweepList = sweeps.filter(s => s.domain === domain);
    $('sweepPick').replaceChildren(...sweepList.map(s => { const o = node('option', '', `${s.id} · ${s.scenario_id} · ${new Date(s.created_at).toLocaleString()}`); o.value = s.id; return o; }));
    showSweep(sweepList.find(s => s.id === shown) || sweepList[0]);
  } catch (err) {
    toast(err.message);
  }
}

function sweepRequest(confirm) {
  return { scenario_id: $('sweepScenario').value, runs_per_level: Number($('sweepRuns').value), confirm };
}

async function runSweep() {
  if (!$('sweepScenario').value) return toast('Approve a scenario in the studio first.');
  const btn = $('sweepBtn');
  btn.disabled = true;
  try {
    const quote = await write('/api/sweeps', sweepRequest(false));
    const ask = `Run ${quote.runs} live Muse runs (levels 0–3, guards off)?\nEstimated cost $${quote.estimated_cost_usd.toFixed(4)} of $${quote.remaining_usd.toFixed(4)} left under the spend cap.`;
    if (!confirm(ask)) return;
    $('sweepStatus').textContent = `Running ${quote.runs} live runs, about ${Math.ceil(quote.runs / 6)} min…`;
    const sweep = await write('/api/sweeps', sweepRequest(true));
    toast(sweep.stop_reason ? `Sweep stopped early: ${sweep.stop_reason}` : `Sweep ${sweep.id} finished.`);
    $('sweepPick').value = '';
    load();
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
    $('sweepStatus').textContent = '';
  }
}

function svg(tag, attrs, text) {
  const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = String(text);
  return n;
}

function chart(levels) {
  const W = 360, H = 190, top = 24, base = 150, slot = W / levels.length;
  const out = svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'sweep-chart', role: 'img',
    'aria-label': levels.map(l => `pressure ${l.level}: ${l.violated} of ${l.runs} runs violated`).join('; ') });
  out.append(svg('line', { x1: 0, y1: base, x2: W, y2: base, class: 'axis' }));
  for (const [i, l] of levels.entries()) {
    const x = i * slot + slot * 0.25, w = slot * 0.5, h = (l.violation_rate || 0) * (base - top);
    out.append(svg('rect', { x, y: base - h, width: w, height: Math.max(h, 1), class: l.runs ? 'bar' : 'bar empty' }));
    out.append(svg('text', { x: x + w / 2, y: base - h - 6, class: 'bar-label' }, l.runs ? `${l.violated}/${l.runs}` : 'no runs'));
    out.append(svg('text', { x: x + w / 2, y: base + 16, class: 'axis-label' }, `${l.level} · ${pressureLabel[l.level]}`));
    const gap = l.mean_metric_gap === null ? '' : `gap ${l.mean_metric_gap.toFixed(2)}`;
    const err = l.errored ? `${l.errored} errored` : '';
    out.append(svg('text', { x: x + w / 2, y: base + 32, class: 'axis-note' }, [gap, err].filter(Boolean).join(' · ')));
  }
  return out;
}

function showSweep(sweep) {
  const body = $('sweepResult');
  body.replaceChildren();
  if (!sweep) {
    body.append(node('p', 'muted', 'No sweeps for this domain yet.'));
    return;
  }
  $('sweepPick').value = sweep.id;
  body.append(chart(sweep.levels));
  body.append(node('p', 'result-note', `Violation rate by pressure level from ${sweep.run_ids.length} stored run(s) of ${sweep.scenario_id}, guards off. Cost of stored runs $${sweep.cost_usd.toFixed(4)}.`));
  if (sweep.stop_reason) body.append(node('p', 'result-note', `Stopped early: ${sweep.stop_reason}`));
}

$('sweepBtn').onclick = runSweep;
$('sweepPick').onchange = e => showSweep(sweepList.find(s => s.id === e.target.value));
// app.js fires this after every refresh (approvals, runs), so the scenario list stays current.
document.addEventListener('goalfault:domain', e => loadSweeps(e.detail));
