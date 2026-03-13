(function () {
  const root = document.querySelector('[data-monthly-edit-root]');
  if (!root || root.getAttribute('data-monthly-editable') !== 'true') return;

  const updateUrl = root.getAttribute('data-update-url');
  if (!updateUrl) return;

  const RESTORE_KEY = 'dairymetrics-monthly-scroll';
  let activeCell = null;
  let tapState = { cell: null, at: 0 };

  function getCookie(name) {
    const cookie = document.cookie
      .split(';')
      .map(function (item) { return item.trim(); })
      .find(function (item) { return item.startsWith(name + '='); });
    return cookie ? decodeURIComponent(cookie.split('=').slice(1).join('=')) : '';
  }

  function restoreScroll() {
    try {
      const payload = JSON.parse(sessionStorage.getItem(RESTORE_KEY) || '{}');
      if (typeof payload.left === 'number') root.scrollLeft = payload.left;
      if (typeof payload.top === 'number') window.scrollTo(0, payload.top);
      sessionStorage.removeItem(RESTORE_KEY);
    } catch (error) {
      sessionStorage.removeItem(RESTORE_KEY);
    }
  }

  function rememberScroll() {
    sessionStorage.setItem(RESTORE_KEY, JSON.stringify({ left: root.scrollLeft, top: window.scrollY }));
  }

  function formatValue(value, type) {
    if (type === 'text') {
      return value || '-';
    }
    const numeric = Number(value || 0);
    return numeric.toLocaleString('ja-JP');
  }

  function finishEditing(cell, nextHtml) {
    cell.innerHTML = nextHtml;
    cell.classList.toggle('is-empty', cell.getAttribute('data-value') === '' || cell.getAttribute('data-value') === '0' || cell.getAttribute('data-value') === '-');
    cell.classList.remove('is-editing');
    activeCell = null;
  }

  async function saveCell(cell, input) {
    const value = input.value.trim();
    const formData = new FormData();
    formData.append('member_id', cell.getAttribute('data-member-id') || '');
    formData.append('department', cell.getAttribute('data-department-code') || '');
    formData.append('entry_date', cell.getAttribute('data-entry-date') || '');
    formData.append('field', cell.getAttribute('data-field') || '');
    formData.append('value', value);

    const response = await fetch(updateUrl, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCookie('csrftoken'),
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json',
      },
      credentials: 'same-origin',
      body: formData,
    });

    if (!response.ok) {
      finishEditing(cell, '<span class="dairymetrics-admin-edit-error">保存失敗</span>');
      setTimeout(function () {
        window.location.reload();
      }, 600);
      return;
    }

    rememberScroll();
    window.location.reload();
  }

  function startEditing(cell) {
    if (activeCell === cell || activeCell) return;
    activeCell = cell;
    cell.classList.add('is-editing');

    const type = cell.getAttribute('data-cell-type') || 'number';
    const rawValue = cell.getAttribute('data-value') || '';
    const input = document.createElement(type === 'text' ? 'input' : 'input');
    input.type = type === 'text' ? 'text' : 'number';
    input.className = 'dairymetrics-admin-inline-input';
    input.value = rawValue === '-' ? '' : rawValue;
    input.autocomplete = 'off';
    if (type !== 'text') {
      input.min = '0';
      input.step = '1';
      input.inputMode = 'numeric';
    }
    cell.innerHTML = '';
    cell.appendChild(input);
    input.focus();
    input.select();

    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') {
        event.preventDefault();
        saveCell(cell, input);
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        finishEditing(cell, type === 'text' ? '<span class="dairymetrics-admin-location">' + formatValue(rawValue, type) + '</span>' : formatValue(rawValue, type));
      }
    });

    input.addEventListener('blur', function () {
      if (!cell.classList.contains('is-editing')) return;
      saveCell(cell, input);
    });
  }

  document.addEventListener('dblclick', function (event) {
    const cell = event.target.closest('[data-editable-cell]');
    if (!cell || !root.contains(cell)) return;
    event.preventDefault();
    startEditing(cell);
  });

  document.addEventListener('touchend', function (event) {
    const cell = event.target.closest('[data-editable-cell]');
    if (!cell || !root.contains(cell)) return;
    const now = Date.now();
    if (tapState.cell === cell && now - tapState.at < 320) {
      event.preventDefault();
      startEditing(cell);
      tapState = { cell: null, at: 0 };
      return;
    }
    tapState = { cell: cell, at: now };
  }, { passive: false });

  restoreScroll();
})();
