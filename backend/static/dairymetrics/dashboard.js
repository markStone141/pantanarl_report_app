(function () {
  const cardRoot = document.getElementById('dairymetrics-dashboard-card');
  const modalBody = document.getElementById('dairymetrics-entry-modal-body');
  const targetModalBody = document.getElementById('dairymetrics-target-modal-body');
  const overlay = document.getElementById('dairymetrics-entry-overlay');
  const targetOverlay = document.getElementById('dairymetrics-target-overlay');
  const openButton = document.getElementById('dairymetrics-open-entry');
  const closeButton = document.getElementById('dairymetrics-close-entry');
  const closeTargetButton = document.getElementById('dairymetrics-close-target');
  const memberSelect = document.getElementById('dairymetrics-member-select');
  const subtitle = document.getElementById('dairymetrics-dashboard-subtitle');
  if (!cardRoot) return;

  function openOverlay(target) {
    if (!target) return;
    target.classList.add('open');
    target.setAttribute('aria-hidden', 'false');
  }

  function closeOverlay(target) {
    if (!target) return;
    target.classList.remove('open');
    target.setAttribute('aria-hidden', 'true');
  }

  async function refreshDashboard(url) {
    const response = await fetch(url.toString(), {
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json'
      },
      credentials: 'same-origin'
    });
    if (!response.ok) return;
    const data = await response.json();
    if (data.card_html) cardRoot.innerHTML = data.card_html;
    if (typeof data.form_html === 'string' && modalBody) modalBody.innerHTML = data.form_html;
    if (typeof data.target_form_html === 'string' && targetModalBody) targetModalBody.innerHTML = data.target_form_html;
    if (data.page_subtitle && subtitle) subtitle.textContent = data.page_subtitle;
    window.history.replaceState({}, '', url.toString());
  }

  async function switchDepartment(code) {
    const url = new URL(window.location.href);
    if (code) {
      url.searchParams.set('department', code);
    } else {
      url.searchParams.delete('department');
    }
    await refreshDashboard(url);
  }

  document.addEventListener('click', function (event) {
    const toggle = event.target.closest('[data-department-toggle]');
    if (toggle) {
      event.preventDefault();
      const code = toggle.getAttribute('data-department-code');
      if (code) switchDepartment(code);
      return;
    }
    const scopeToggle = event.target.closest('[data-scope-toggle]');
    if (scopeToggle && !scopeToggle.disabled) {
      event.preventDefault();
      const scope = scopeToggle.getAttribute('data-scope-value');
      if (scope) {
        const url = new URL(window.location.href);
        url.searchParams.set('scope', scope);
        window.history.replaceState({}, '', url.toString());
        switchDepartment(url.searchParams.get('department') || '');
      }
      return;
    }
    if (event.target.closest('#dairymetrics-open-entry') || event.target.closest('[data-open-dairymetrics-entry]')) {
      event.preventDefault();
      openOverlay(overlay);
      return;
    }
    if (event.target.closest('[data-open-dairymetrics-target]')) {
      event.preventDefault();
      openOverlay(targetOverlay);
      return;
    }
    if (event.target.closest('#dairymetrics-close-entry') || event.target.closest('[data-close-dairymetrics-modal]')) {
      event.preventDefault();
      closeOverlay(overlay);
      return;
    }
    if (event.target.closest('#dairymetrics-close-target')) {
      event.preventDefault();
      closeOverlay(targetOverlay);
    }
  });

  if (memberSelect) {
    memberSelect.addEventListener('change', function () {
      if (!memberSelect.value) return;
      const currentUrl = new URL(window.location.href);
      const nextUrl = new URL(memberSelect.value, window.location.origin);
      ['scope', 'department', 'start_date', 'end_date'].forEach(function (key) {
        if (currentUrl.searchParams.has(key)) {
          nextUrl.searchParams.set(key, currentUrl.searchParams.get(key));
        }
      });
      refreshDashboard(nextUrl);
    });
  }

  if (overlay) {
    overlay.addEventListener('click', function (event) {
      if (event.target === overlay) closeOverlay(overlay);
    });
  }
  if (targetOverlay) {
    targetOverlay.addEventListener('click', function (event) {
      if (event.target === targetOverlay) closeOverlay(targetOverlay);
    });
  }

  if (openButton) {
    openButton.addEventListener('click', function () {
      openOverlay(overlay);
    });
  }
  if (closeButton) {
    closeButton.addEventListener('click', function () {
      closeOverlay(overlay);
    });
  }
  if (closeTargetButton) {
    closeTargetButton.addEventListener('click', function () {
      closeOverlay(targetOverlay);
    });
  }
})();
