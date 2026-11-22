(() => {
  const form = document.getElementById('review-form');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const decisions = {};
    for (const row of form.querySelectorAll('[data-field]')) {
      const name = row.dataset.field;
      const action = form.elements[name + '_action'].value;
      const candidate = form.elements[name + '_candidate'].value;
      let value = action === 'edit' ? form.elements[name + '_value'].value : null;
      if (name === 'payment_terms_days' && action === 'edit' && /^[0-9]+$/.test(value)) value = Number(value);
      decisions[name] = {action, candidate_id: action === 'accept' && candidate ? Number(candidate) : null,
        value, reason: form.elements[name + '_reason'].value, provenance: form.elements[name + '_provenance'].value};
    }
    const error = document.getElementById('review-error');
    try {
      const response = await fetch(form.dataset.endpoint, {method: 'PATCH', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': form.elements.csrfmiddlewaretoken.value},
        body: JSON.stringify({expected_revision: Number(form.elements.expected_revision.value), decisions})});
      const data = await response.json();
      if (!response.ok) { error.textContent = data.error || 'Save failed. Reload to inspect the current revision.'; return; }
      window.location.assign(data.confirmation_url);
    } catch (_) { error.textContent = 'Save outcome unavailable. Reload before retrying.'; }
  });
})();
