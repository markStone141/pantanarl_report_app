(function () {
  const cardRoot = document.getElementById('dairymetrics-dashboard-card');
  const modalBody = document.getElementById('dairymetrics-entry-modal-body');
  const overlay = document.getElementById('dairymetrics-entry-overlay');
  const openButton = document.getElementById('dairymetrics-open-entry');
  const closeButton = document.getElementById('dairymetrics-close-entry');
  if (!cardRoot) return;

  function openOverlay() {
    if (!overlay) return;
    overlay.classList.add('open');
    overlay.setAttribute('aria-hidden', 'false');
  }

  function closeOverlay() {
    if (!overlay) return;
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
  }

  async function switchDepartment(code) {
    const url = new URL(window.location.href);
    url.searchParams.set('department', code);
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
    if (data.form_html && modalBody) modalBody.innerHTML = data.form_html;
    window.history.replaceState({}, '', url.toString());
  }

  document.addEventListener('click', function (event) {
    const toggle = event.target.closest('[data-department-toggle]');
    if (toggle) {
      event.preventDefault();
      const code = toggle.getAttribute('data-department-code');
      if (code) switchDepartment(code);
      return;
    }
    if (event.target.closest('#dairymetrics-open-entry')) {
      event.preventDefault();
      openOverlay();
      return;
    }
    if (event.target.closest('#dairymetrics-close-entry') || event.target.closest('[data-close-dairymetrics-modal]')) {
      event.preventDefault();
      closeOverlay();
    }
  });

  if (overlay) {
    overlay.addEventListener('click', function (event) {
      if (event.target === overlay) closeOverlay();
    });
  }

  if (openButton) {
    openButton.addEventListener('click', openOverlay);
  }
  if (closeButton) {
    closeButton.addEventListener('click', closeOverlay);
  }
})();
