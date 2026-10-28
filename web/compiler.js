'use strict';
// Policy compiler panel. Uses $, node, button, call, write, toast, load and currentDomain from app.js.

let compilerDomain = null;
let openPolicy = null;
let domainTools = [];

function examplesTemplate(record) {
  const draft = record.draft;
  if (draft.should_pass.length || draft.should_fail.length) {
    return { should_pass: draft.should_pass, should_fail: draft.should_fail };
  }
  const tool = record.report.tool || domainTools[0] || 'tool_name';
  const blank = () => ({ description: '', actions: [{ tool, args: {} }] });
  return { should_pass: [blank(), blank()], should_fail: [blank(), blank()] };
}

async function loadPolicies(domain) {
  compilerDomain = domain;
  try {
    const [listing, config] = await Promise.all([
      call(`/api/domains/${encodeURIComponent(domain)}/policies`),
      call(`/api/config?domain=${encodeURIComponent(domain)}`),
    ]);
    // A slower response for a domain the user has already left must not overwrite the current one.
    if (domain !== compilerDomain) return;
    domainTools = config.tool_catalog.map(t => t.name);
    renderPolicyList(listing.compiled);
    if (openPolicy && openPolicy.domain !== domain) closeDraft();
  } catch (err) {
    toast(err.message);
  }
}

function renderPolicyList(records) {
  const list = $('policyList');
  list.replaceChildren();
  $('policyCount').textContent = records.filter(r => r.status === 'proposed').length;
  if (!records.length) {
    list.append(node('p', 'muted', 'No compiled policies for this domain yet.'));
    return;
  }
  for (const r of records) {
    const card = node('article', 'scenario-card');
    const head = node('div', 'scenario-head');
    head.append(node('b', '', `${r.policy_id} · ${r.draft.invariant}`), node('span', `pill ${r.status}`, r.status));
    card.append(head, node('p', '', r.draft.text), node('code', 'rule-code', r.draft.rule));
    const tags = node('div', 'scenario-tags');
    tags.append(node('span', `pill ${r.report.ok ? 'passed' : 'failed'}`, r.report.ok ? 'checks pass' : 'checks fail'));
    tags.append(node('span', 'pill neutral', r.source === 'muse' ? 'Muse drafted' : 'Written by hand'));
    card.append(tags);
    const actions = node('div', 'scenario-actions');
    actions.append(button(r.status === 'approved' ? 'View' : 'Review', () => showDraft(r), 'tiny-btn callout'));
    card.append(actions);
    list.append(card);
  }
}

function closeDraft() {
  openPolicy = null;
  $('draftPanel').hidden = true;
}

function showDraft(record) {
  openPolicy = record;
  $('draftPanel').hidden = false;
  $('draftTitle').textContent = `${record.policy_id} · ${record.id}`;
  const cost = record.source === 'muse' ? ` · est. $${Number(record.estimated_model_cost_usd || 0).toFixed(5)}` : '';
  $('draftMeta').textContent = `${record.source === 'muse' ? 'Drafted by Meta Muse' : 'Written by hand'}${cost} · ${new Date(record.created_at).toLocaleString()}`;
  $('draftPill').className = `pill ${record.status}`;
  $('draftPill').textContent = record.status.toUpperCase();
  $('draftText').textContent = `Policy: ${record.draft.text}${record.draft.explanation ? ` — ${record.draft.explanation}` : ''}`;
  $('draftRule').value = record.draft.rule;
  $('draftInvariant').value = record.draft.invariant;
  $('draftExamples').value = JSON.stringify(examplesTemplate(record), null, 2);
  renderReport(record.report, record.status);
  $('draftPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderReport(report, status) {
  const box = $('draftReport');
  box.replaceChildren();
  const passed = status === 'approved' ? 'Every check passed. This rule is approved and applies to every run in this domain.'
    : 'Every check passed. This rule can be approved.';
  box.append(node('div', `evaluation-summary ${report.ok ? '' : 'failed'}`,
    report.ok ? passed : 'Not ready: fix the problems below, then re-check.'));
  if (report.errors.length) {
    const errors = node('ul', 'check-list');
    report.errors.forEach(e => errors.append(node('li', 'bad', e)));
    box.append(node('div', 'trace-title', 'RULE PROBLEMS'), errors);
  }
  for (const [key, label] of [['should_fail', 'MUST DENY'], ['should_pass', 'MUST ALLOW']]) {
    if (!report[key].length) continue;
    box.append(node('div', 'trace-title', label));
    report[key].forEach((ex, i) => {
      const row = node('div', 'event');
      row.append(node('span', 'event-num', i + 1));
      const detail = node('div');
      detail.append(node('b', '', ex.description || `Example ${i + 1}`));
      ex.trace.forEach(step => detail.append(node('code', '', `${step.tool} ${JSON.stringify(step.args)} → ${JSON.stringify(step.result)}`)));
      ex.problems.forEach(p => detail.append(node('small', 'bad', p)));
      row.append(detail, node('div', `event-status ${ex.ok ? '' : 'bad'}`, ex.ok ? (ex.matched ? 'DENIED ✓' : 'ALLOWED ✓') : 'WRONG'));
      box.append(row);
    });
  }
  if (report.safe_controls.length) {
    const controls = node('ul', 'check-list');
    report.safe_controls.forEach(c => controls.append(node('li', c.ok ? 'good' : 'bad', `${c.name}: ${c.ok ? 'not flagged' : c.problems.join('; ')}`)));
    box.append(node('div', 'trace-title', 'SAFE CONTROLS'), controls);
  }
  if (report.fixtures_flagged && report.fixtures_flagged.length) {
    box.append(node('p', 'result-note', `Also flags these scenario fixtures: ${report.fixtures_flagged.join(', ')}`));
  }
}

function draftEdits() {
  let examples;
  try {
    examples = JSON.parse($('draftExamples').value);
  } catch {
    throw Error('Examples are not valid JSON.');
  }
  return {
    rule: $('draftRule').value.trim(),
    invariant: $('draftInvariant').value.trim(),
    should_pass: examples.should_pass || [],
    should_fail: examples.should_fail || [],
  };
}

async function compilePolicy() {
  const text = $('policyText').value.trim();
  if (text.length < 5) return toast('Write the policy first (at least 5 characters).');
  const mode = $('policyMode').value;
  const body = { text, mode };
  if (mode === 'manual') {
    body.rule = $('manualRule').value.trim();
    body.invariant = $('manualInvariant').value.trim();
    if (!body.rule || !body.invariant) return toast('Manual mode needs a rule and an invariant name.');
  } else if (!confirm('Ask Meta Muse to draft this rule? This uses API credits.')) {
    return;
  }
  $('compileBtn').disabled = true;
  const domain = compilerDomain;
  try {
    const record = await write(`/api/domains/${encodeURIComponent(domain)}/policies/compile`, body);
    toast(record.report.ok ? 'Draft passes every check. Review it before approving.' : 'Draft saved. Some checks fail; see the report.');
    if (domain !== compilerDomain) return;
    await loadPolicies(domain);
    showDraft(record);
    if (mode === 'muse') load();
  } catch (err) {
    toast(err.message);
  } finally {
    $('compileBtn').disabled = false;
  }
}

async function recheck() {
  if (!openPolicy) return;
  try {
    const record = await write(`/api/policies/${encodeURIComponent(openPolicy.id)}/check`, draftEdits());
    toast(record.report.ok ? 'All checks pass.' : 'Checks still fail; see the report.');
    showDraft(record);
    loadPolicies(compilerDomain);
  } catch (err) {
    toast(err.message);
  }
}

async function reviewPolicy(approved) {
  if (!openPolicy) return;
  try {
    const record = await write(`/api/policies/${encodeURIComponent(openPolicy.id)}/review`, { approved, ...draftEdits() });
    toast(approved ? `${record.policy_id} approved. It now applies to every run in this domain.` : `${record.policy_id} rejected.`);
    showDraft(record);
  } catch (err) {
    toast(err.message);
    const fresh = await call(`/api/domains/${encodeURIComponent(compilerDomain)}/policies`).catch(() => null);
    const updated = fresh && fresh.compiled.find(r => r.id === openPolicy.id);
    if (updated) showDraft(updated);
  }
  loadPolicies(compilerDomain);
}

$('policyMode').onchange = e => { $('manualFields').hidden = e.target.value !== 'manual'; };
$('policyText').addEventListener('input', e => { $('policyCharCount').textContent = `${e.target.value.length} / 500`; });
$('compileBtn').onclick = compilePolicy;
$('recheckBtn').onclick = recheck;
$('approvePolicyBtn').onclick = () => reviewPolicy(true);
$('rejectPolicyBtn').onclick = () => reviewPolicy(false);
document.addEventListener('goalfault:domain', e => { if (e.detail !== compilerDomain) loadPolicies(e.detail); });
