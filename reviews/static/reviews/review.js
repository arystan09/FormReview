(() => {
  const form = document.getElementById('review-form');
  if (!form) return;
  const pages = JSON.parse(document.getElementById('source-pages').textContent);
  const field = (name, suffix) => form.elements[name + '_' + suffix];
  const updateControls = row => {
    const name = row.dataset.field, action = field(name, 'action').value;
    const candidate = field(name, 'candidate');
    candidate.hidden = action !== 'accept';
    form.querySelector('label[for="' + name + '_candidate"]').hidden = candidate.hidden;
    field(name, 'value').closest('label').hidden = action !== 'edit';
    field(name, 'reason').closest('label').hidden = !['edit','missing'].includes(action);
    field(name, 'provenance').closest('label').hidden = action !== 'edit';
    row.querySelector('details').hidden = action !== 'edit';
  };
  form.querySelectorAll('[data-field]').forEach(row => {
    updateControls(row);
    field(row.dataset.field, 'action').addEventListener('change', () => updateControls(row));
  });
  const error = document.getElementById('review-error');
  const status = document.getElementById('save-status');
  let dirty = false, compared = null, generation = 0;
  const changed = () => { dirty = true; generation++; status.textContent = 'Unsaved edits in this tab.'; };
  form.addEventListener('input', changed);
  form.addEventListener('change', changed);
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  const showError = message => { error.textContent = message; error.focus(); };
  document.querySelectorAll('.show-evidence').forEach(button => button.addEventListener('click', () => {
    pages.forEach((text, index) => { document.getElementById('source-page-' + (index + 1)).textContent = text; });
    const page = Number(button.dataset.page), start = Number(button.dataset.start), end = Number(button.dataset.end);
    const text = Array.from(pages[page - 1]);
    const target = document.getElementById('source-page-' + page);
    const mark = document.createElement('mark');
    mark.textContent = text.slice(start, end).join('');
    target.replaceChildren(document.createTextNode(text.slice(0, start).join('')), mark, document.createTextNode(text.slice(end).join('')));
    document.getElementById('highlight-status').textContent = 'Highlighted exact source quote on page ' + page + '. A quote match is not semantic truth.';
    mark.scrollIntoView({block:'nearest'}); target.focus();
  }));
  document.querySelectorAll('.capture-source').forEach(button => button.addEventListener('click', () => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) { showError('Select canonical source text, or enter an exact quote and page manually.'); return; }
    const range = selection.getRangeAt(0);
    const target = [...document.querySelectorAll('.canonical-source pre')].find(node => node.contains(range.startContainer) && node.contains(range.endContainer));
    const quote = selection.toString();
    if (!target || Array.from(quote).length > 256) { showError('Choose one source literal of at most 256 characters on one page.'); return; }
    const name = button.dataset.name;
    field(name, 'action').value = 'edit'; field(name, 'page').value = target.id.split('-').pop();
    field(name, 'quote').value = quote; field(name, 'literal').value = quote;
    const terms = quote.trim().match(/^(?:net\s*([0-9]{1,3})|([0-9]{1,3})\s*days)$/i);
    field(name, 'value').value = name === 'payment_terms_days' && terms ? (terms[1] || terms[2]) : quote;
    changed(); field(name, 'reason').focus();
  }));
  const decisions = () => {
    const result = {};
    for (const row of form.querySelectorAll('[data-field]')) {
      const name = row.dataset.field, action = field(name, 'action').value;
      const candidate = field(name, 'candidate').value;
      let value = ['edit','unresolved'].includes(action) ? field(name, 'value').value : null;
      if (name === 'payment_terms_days' && value !== null && /^[0-9]+$/.test(value)) value = Number(value);
      const decision = {action, candidate_id: action === 'accept' && candidate ? Number(candidate) : null,
        value, reason: field(name, 'reason').value, provenance: field(name, 'provenance').value};
      if (action === 'edit' && (field(name, 'page').value || field(name, 'quote').value || field(name, 'literal').value)) {
        decision.source_span = {page: Number(field(name, 'page').value), quote: field(name, 'quote').value, value_text: field(name, 'literal').value};
      }
      result[name] = decision;
    }
    return result;
  };
  const conflict = document.getElementById('conflict-panel');
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (form.dataset.editable !== 'yes') return;
    const partial = event.submitter?.value === 'partial', sentGeneration = generation;
    const buttons = form.querySelectorAll('button[type=submit]'); buttons.forEach(button => { button.disabled = true; });
    try {
      const response = await fetch(form.dataset.endpoint, {method:'PATCH', credentials:'same-origin',
        headers:{'Content-Type':'application/json','X-CSRFToken':form.elements.csrfmiddlewaretoken.value},
        body:JSON.stringify({expected_revision:Number(form.elements.expected_revision.value), decisions:decisions(), partial})});
      const data = await response.json();
      if (!response.ok) {
        if (data.error === 'stale_or_closed_draft') { conflict.hidden = false; compared = null; document.getElementById('use-revision').disabled = true; }
        showError((data.error || 'Save failed') + '. Your text has been preserved.'); return;
      }
      form.elements.expected_revision.value = data.revision; document.getElementById('revision').textContent = data.revision;
      dirty = generation !== sentGeneration; error.textContent = ''; conflict.hidden = true;
      if (!partial && !dirty) { window.location.assign(data.confirmation_url); return; }
      status.textContent = 'Saved revision ' + data.revision + (dirty ? '. Newer edits remain unsaved.' : '. No approval occurred.') + (data.validation_errors.length ? ' More decisions are required before approval.' : ' Ready for explicit confirmation.');
    } catch (_) { showError('Save outcome unavailable. Your text remains here; compare the saved revision before retrying.'); conflict.hidden = false; }
    finally { buttons.forEach(button => { button.disabled = false; }); }
  });
  document.getElementById('compare-current').addEventListener('click', async () => {
    try {
      const response = await fetch(form.dataset.endpoint, {credentials:'same-origin'});
      if (!response.ok) throw new Error();
      compared = await response.json();
      const display = document.getElementById('saved-comparison'); display.replaceChildren();
      const heading = document.createElement('p'); heading.textContent = 'Saved revision ' + compared.revision + ' · ' + compared.status; display.append(heading);
      for (const row of form.querySelectorAll('[data-field]')) {
        const name = row.dataset.field, saved = compared.decisions[name];
        const paragraph = document.createElement('p');
        paragraph.textContent = name + ': ' + (saved ? [saved.action, saved.value, saved.candidate_id ? 'candidate: ' + (compared.candidate_values[name] || 'unavailable') : '', saved.reason, saved.provenance, saved.source_span ? 'source page ' + saved.source_span.page + ': ' + saved.source_span.quote : ''].filter(v => v !== null && v !== '').join(' · ') : 'No saved decision');
        display.append(paragraph);
      }
      document.getElementById('reconciled').checked = false;
      document.getElementById('use-revision').disabled = true;
    } catch (_) { showError('Cannot read saved decisions. Your edits remain here.'); }
  });
  document.getElementById('reconciled').addEventListener('change', event => { document.getElementById('use-revision').disabled = !(event.target.checked && compared?.status === 'active'); });
  document.getElementById('use-revision').addEventListener('click', () => {
    if (!compared || compared.status !== 'active' || !document.getElementById('reconciled').checked) return;
    form.elements.expected_revision.value = compared.revision;
    document.getElementById('revision').textContent = compared.revision;
    conflict.hidden = true; error.textContent = ''; changed();
    status.textContent = 'Reconciled locally against revision ' + compared.revision + '. Save explicitly to submit your decisions.';
  });
  document.getElementById('reload-draft').addEventListener('click', () => {
    if (window.confirm('Discard unsaved edits in this tab and reload the saved draft?')) { dirty = false; window.location.reload(); }
  });
})();
