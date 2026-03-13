(function () {
  const overlay = document.getElementById('dairymetrics-ranking-overlay');
  const body = document.getElementById('dairymetrics-ranking-modal-body');
  const closeButton = document.getElementById('dairymetrics-close-ranking');
  if (!overlay || !body) return;

  function openOverlay() {
    overlay.classList.add('open');
    overlay.setAttribute('aria-hidden', 'false');
  }

  function closeOverlay() {
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
  }

  async function openRankingDetail(button) {
    const detailUrl = overlay.getAttribute('data-ranking-detail-url');
    if (!detailUrl) return;
    const url = new URL(detailUrl, window.location.origin);
    url.searchParams.set('metric', button.getAttribute('data-metric-key') || '');
    url.searchParams.set('department', button.getAttribute('data-department-code') || '');
    url.searchParams.set('scope', button.getAttribute('data-scope') || 'today');
    const memberId = button.getAttribute('data-member-id');
    if (memberId) {
      url.searchParams.set('member', memberId);
    }
    const startDate = button.getAttribute('data-start-date');
    const endDate = button.getAttribute('data-end-date');
    if (startDate) {
      url.searchParams.set('start_date', startDate);
    }
    if (endDate) {
      url.searchParams.set('end_date', endDate);
    }

    const response = await fetch(url.toString(), {
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json',
      },
      credentials: 'same-origin',
    });
    if (!response.ok) return;
    const data = await response.json();
    if (!data.modal_html) return;
    body.innerHTML = data.modal_html;
    openOverlay();
  }

  document.addEventListener('click', function (event) {
    const trigger = event.target.closest('[data-open-ranking-detail]');
    if (trigger) {
      event.preventDefault();
      openRankingDetail(trigger);
      return;
    }
    if (event.target === overlay || event.target.closest('#dairymetrics-close-ranking')) {
      event.preventDefault();
      closeOverlay();
    }
  });

  if (closeButton) {
    closeButton.addEventListener('click', function () {
      closeOverlay();
    });
  }
})();
