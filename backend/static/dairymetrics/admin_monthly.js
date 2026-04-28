(function () {
  const root = document.querySelector('[data-monthly-edit-root]');
  if (!root || root.getAttribute('data-monthly-editable') !== 'true') return;

  const bulkUpdateUrl = root.getAttribute('data-bulk-update-url');
  if (!bulkUpdateUrl) return;

  const headerScroll = document.querySelector('[data-monthly-header-scroll]');
  const leftScroll = document.querySelector('[data-monthly-left-scroll]');
  const cornerHead = document.querySelector('[data-monthly-corner-head]');
  const headerHead = document.querySelector('[data-monthly-header-head]');
  const leftBody = document.querySelector('[data-monthly-left-body]');
  const rightBody = document.querySelector('[data-monthly-right-body]');
  const editButton = document.querySelector('[data-monthly-edit-start]');
  const saveButton = document.querySelector('[data-monthly-edit-save]');
  const cancelButton = document.querySelector('[data-monthly-edit-cancel]');
  const statusNode = document.querySelector('[data-monthly-edit-status]');
  const editableCells = Array.from(root.querySelectorAll('[data-editable-cell]'));
  const RESTORE_KEY = 'dairymetrics-monthly-scroll';
  let isEditing = false;

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
      if (typeof payload.top === 'number') root.scrollTop = payload.top;
      sessionStorage.removeItem(RESTORE_KEY);
    } catch (error) {
      sessionStorage.removeItem(RESTORE_KEY);
    }
    syncPaneScroll();
  }

  function rememberScroll() {
    sessionStorage.setItem(RESTORE_KEY, JSON.stringify({ left: root.scrollLeft, top: root.scrollTop }));
  }

  function syncPaneScroll() {
    if (headerScroll) headerScroll.scrollLeft = root.scrollLeft;
    if (leftScroll) leftScroll.scrollTop = root.scrollTop;
  }

  function syncSectionHeights(sourceRows, targetRows) {
    if (!sourceRows || !targetRows || sourceRows.length !== targetRows.length) return;
    sourceRows.forEach(function (row) { row.style.height = ''; });
    targetRows.forEach(function (row) { row.style.height = ''; });
    sourceRows.forEach(function (row, index) {
      const targetRow = targetRows[index];
      const height = Math.max(row.getBoundingClientRect().height, targetRow.getBoundingClientRect().height);
      row.style.height = height + 'px';
      targetRow.style.height = height + 'px';
    });
  }

  function syncPaneHeights() {
    if (cornerHead && headerHead) {
      syncSectionHeights(
        Array.from(cornerHead.querySelectorAll('thead tr')),
        Array.from(headerHead.querySelectorAll('thead tr'))
      );
    }
    if (leftBody && rightBody) {
      const leftRows = Array.from(leftBody.querySelectorAll('tr'));
      const rightRows = Array.from(rightBody.querySelectorAll('tr'));
      syncSectionHeights(leftRows, rightRows);

      leftRows.forEach(function (row) {
        const memberCell = row.querySelector('.dairymetrics-admin-member-cell[rowspan]');
        if (!memberCell) return;
        memberCell.style.height = '';
        const groupSize = Number(memberCell.getAttribute('rowspan') || '1');
        const startIndex = leftRows.indexOf(row);
        const totalHeight = rightRows
          .slice(startIndex, startIndex + groupSize)
          .reduce(function (sum, currentRow) {
            return sum + currentRow.getBoundingClientRect().height;
          }, 0);
        memberCell.style.height = totalHeight + 'px';
      });
    }
  }

  function setStatus(message, isError) {
    if (!statusNode) return;
    statusNode.textContent = message || '';
    statusNode.classList.toggle('is-error', Boolean(isError));
  }

  function formatValue(value, type) {
    if (type === 'text') {
      return value || '-';
    }
    const normalized = value === '' ? 0 : Number(value || 0);
    return normalized.toLocaleString('ja-JP');
  }

  function renderDisplay(cell) {
    const type = cell.getAttribute('data-cell-type') || 'number';
    const rawValue = cell.getAttribute('data-value') || '';
    if (type === 'text') {
      cell.innerHTML = '<span class="dairymetrics-admin-location">' + formatValue(rawValue, type) + '</span>';
    } else {
      cell.textContent = formatValue(rawValue, type);
    }
    cell.classList.toggle('is-empty', rawValue === '' || rawValue === '0' || rawValue === '-');
    cell.classList.remove('is-editing');
    cell.classList.remove('is-dirty');
  }

  function normalizeValue(value, type) {
    const trimmed = (value || '').trim();
    if (type === 'text') {
      return trimmed;
    }
    if (trimmed === '') {
      return '';
    }
    return String(Number(trimmed));
  }

  function syncDirtyState(cell) {
    const input = cell.querySelector('.dairymetrics-admin-inline-input');
    if (!input) return;
    const type = cell.getAttribute('data-cell-type') || 'number';
    const originalValue = normalizeValue(cell.getAttribute('data-original-value') || '', type);
    const currentValue = normalizeValue(input.value, type);
    cell.classList.toggle('is-dirty', currentValue !== originalValue);
  }

  function buildInput(cell) {
    const type = cell.getAttribute('data-cell-type') || 'number';
    const rawValue = cell.getAttribute('data-value') || '';
    const input = document.createElement('input');
    input.type = type === 'text' ? 'text' : 'number';
    input.className = 'dairymetrics-admin-inline-input';
    input.value = rawValue === '-' ? '' : rawValue;
    input.autocomplete = 'off';
    if (type !== 'text') {
      input.min = '0';
      input.step = '1';
      input.inputMode = 'numeric';
    }
    input.addEventListener('input', function () {
      syncDirtyState(cell);
    });
    return input;
  }

  function enterEditMode() {
    if (isEditing) return;
    isEditing = true;
    editableCells.forEach(function (cell) {
      cell.setAttribute('data-original-value', cell.getAttribute('data-value') || '');
      cell.classList.add('is-editing');
      cell.innerHTML = '';
      cell.appendChild(buildInput(cell));
    });
    syncPaneHeights();
    if (editButton) editButton.hidden = true;
    if (saveButton) saveButton.hidden = false;
    if (cancelButton) cancelButton.hidden = false;
    root.classList.add('is-bulk-editing');
    setStatus('変更したセルだけ保存します。', false);
  }

  function exitEditMode() {
    isEditing = false;
    editableCells.forEach(function (cell) {
      renderDisplay(cell);
      cell.removeAttribute('data-original-value');
    });
    syncPaneHeights();
    if (editButton) editButton.hidden = false;
    if (saveButton) saveButton.hidden = true;
    if (cancelButton) cancelButton.hidden = true;
    root.classList.remove('is-bulk-editing');
  }

  function collectChanges() {
    return editableCells.reduce(function (changes, cell) {
      const input = cell.querySelector('.dairymetrics-admin-inline-input');
      if (!input) return changes;
      const type = cell.getAttribute('data-cell-type') || 'number';
      const originalValue = normalizeValue(cell.getAttribute('data-original-value') || '', type);
      const currentValue = normalizeValue(input.value, type);
      if (currentValue === originalValue) {
        return changes;
      }
      changes.push({
        member_id: cell.getAttribute('data-member-id') || '',
        department: cell.getAttribute('data-department-code') || '',
        entry_date: cell.getAttribute('data-entry-date') || '',
        field: cell.getAttribute('data-field') || '',
        value: type === 'text' ? input.value.trim() : currentValue,
      });
      return changes;
    }, []);
  }

  async function saveChanges() {
    const changes = collectChanges();
    if (!changes.length) {
      setStatus('変更はありません。', false);
      exitEditMode();
      return;
    }

    if (saveButton) saveButton.disabled = true;
    if (cancelButton) cancelButton.disabled = true;
    setStatus('保存中...', false);

    const response = await fetch(bulkUpdateUrl, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCookie('csrftoken'),
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
      },
      credentials: 'same-origin',
      body: JSON.stringify({ changes: changes }),
    });

    const payload = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      setStatus('保存失敗', true);
      if (typeof payload.index === 'number') {
        const failedCell = editableCells.find(function (cell) {
          const input = cell.querySelector('.dairymetrics-admin-inline-input');
          return input && cell.classList.contains('is-dirty');
        });
        if (failedCell) {
          failedCell.querySelector('.dairymetrics-admin-inline-input').focus();
        }
      }
      if (saveButton) saveButton.disabled = false;
      if (cancelButton) cancelButton.disabled = false;
      return;
    }

    rememberScroll();
    window.location.reload();
  }

  if (editButton) {
    editButton.addEventListener('click', enterEditMode);
  }
  if (saveButton) {
    saveButton.addEventListener('click', function () {
      saveChanges();
    });
  }
  if (cancelButton) {
    cancelButton.addEventListener('click', function () {
      setStatus('', false);
      exitEditMode();
    });
  }

  root.addEventListener('scroll', syncPaneScroll, { passive: true });
  window.addEventListener('resize', syncPaneHeights);
  restoreScroll();
  syncPaneHeights();
})();
