(function () {
  async function refreshOverview(code) {
    const root = document.getElementById('dairymetrics-admin-overview-content');
    if (!root) return;
    const url = new URL(window.location.href);
    if (code) {
      url.searchParams.set('department', code);
    } else {
      url.searchParams.delete('department');
    }
    const response = await fetch(url.toString(), {
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json'
      },
      credentials: 'same-origin'
    });
    if (!response.ok) return;
    const data = await response.json();
    if (data.overview_html) {
      root.innerHTML = data.overview_html;
      window.history.replaceState({}, '', url.toString());
    }
  }

  document.addEventListener('change', function (event) {
    const departmentSelect = event.target.closest('[data-admin-overview-department]');
    if (!departmentSelect) return;
    refreshOverview(departmentSelect.value);
  });
})();
