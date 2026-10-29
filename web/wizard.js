'use strict';
// Domain wizard. Uses $, node, button, call, write, toast and load from app.js.

function draftLabel(record) {
  if (record.status === 'approved') return 'draft, human-reviewed';
  if (record.status === 'rejected') return 'rejected';
  return record.report && record.report.ok ? 'ready for review' : 'checks failed';
}

async function loadDomainDrafts() {
  try {
    const records = await call('/api/domains/drafts');
    const list = $('domainDraftList');
    list.replaceChildren();
    $('domainDraftCount').textContent = records.length;
    if (!records.length) {
      list.append(node('p', 'muted', 'No domain drafts yet.'));
      return;
    }
    records.forEach(record => {
      const card = node('article', 'scenario-card');
      const head = node('div', 'scenario-head');
      head.append(node('b', '', (record.report && record.report.title) || 'Domain draft'));
      head.append(node('span', `pill ${record.status === 'approved' ? 'passed' : record.status === 'rejected' ? 'failed' : 'neutral'}`, draftLabel(record)));
      card.append(head);
      card.append(node('p', '', record.explanation || record.text));
      if (record.report && record.report.errors && record.report.errors.length) {
        card.append(node('p', 'result-note', record.report.errors[0]));
      }
      if (record.status === 'proposed') {
        const acts = node('div', 'scenario-actions');
        acts.append(button('Approve domain', () => reviewDomainDraft(record.id, true), 'tiny-btn callout'));
        acts.append(button('Reject', () => reviewDomainDraft(record.id, false)));
        card.append(acts);
      }
      list.append(card);
    });
  } catch (err) {
    toast(err.message);
  }
}

async function draftDomain() {
  const text = $('domainBrief').value.trim();
  if (text.length < 12) return toast('Describe the business in at least 12 characters.');
  const mode = $('domainMode').value;
  const body = { text, mode };
  if (mode === 'muse') {
    if (!confirm('Ask Meta Muse to draft this domain? This uses API credits.')) return;
  } else {
    body.yaml = $('domainYaml').value;
    if (body.yaml.trim().length < 20) return toast('Paste the domain YAML first.');
  }
  $('domainDraftBtn').disabled = true;
  try {
    const record = await write('/api/domains/draft', body);
    toast(record.report.ok ? 'Draft passes the quality bar. It is not installed until you approve it.' : 'Draft saved. The checks failed.');
    await loadDomainDrafts();
  } catch (err) {
    toast(err.message);
  } finally {
    $('domainDraftBtn').disabled = false;
  }
}

async function reviewDomainDraft(id, approved) {
  try {
    const record = await write(`/api/domains/drafts/${encodeURIComponent(id)}/review`, { approved });
    toast(approved ? `${record.report.name} is installed. Its scenarios still need approval before a run.` : 'Draft rejected.');
    if (approved && typeof load === 'function') await load();
    await loadDomainDrafts();
  } catch (err) {
    toast(err.message);
    loadDomainDrafts();
  }
}

$('domainMode').onchange = event => {
  const manual = event.target.value === 'manual';
  $('domainYaml').hidden = !manual;
  $('domainYaml').previousElementSibling.hidden = !manual;
};
$('domainDraftBtn').onclick = draftDomain;
loadDomainDrafts();
