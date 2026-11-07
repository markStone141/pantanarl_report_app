(function () {
  const root = document.querySelector('[data-period-comparison]');
  const node = document.getElementById('period-comparison-chart-data');
  if (!root || !node) return;
  const select = root.querySelector('#period-chart-metric');
  const frame = root.querySelector('#period-comparison-frame');
  const status = root.querySelector('[data-period-status]');
  const retry = root.querySelector('[data-period-retry]');
  const empty = root.querySelector('[data-period-chart-empty]');
  const canvas = document.createElement('canvas');
  frame.appendChild(canvas);
  const colors = ['#1d7dfa', '#ef4444', '#14b8a6', '#8b5cf6', '#f59e0b', '#64748b'];
  let data = JSON.parse(node.textContent);
  let chart, controller, version = 0, mode = 'table';
  function render() {
    if (mode !== 'graph') return;
    if (typeof window.Chart === 'undefined') {
      status.textContent = 'グラフを読み込めませんでした。ページを再読み込みしてください。';
      return;
    }
    if (chart) chart.destroy();
    const hasData = data.datasets.some(series => series.data.some(value => value !== null));
    frame.hidden = !hasData;
    empty.hidden = hasData;
    if (!hasData) return;
    canvas.setAttribute('aria-label', data.label + '：路程別の月次推移');
    chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: data.labels,
        datasets: data.datasets.map(function (series, index) {
          const color = colors[index] || 'hsl(' + ((index * 137.5) % 360) + ',65%,45%)';
          return { ...series, borderColor: color, backgroundColor: color, spanGaps: false, tension: 0.1 };
        }),
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: {
          x: { title: { display: true, text: '月' } },
          y: { beginAtZero: true, title: { display: true, text: data.label + (data.unit ? '（' + data.unit + '）' : '') } },
        },
        plugins: { tooltip: { callbacks: {
          label: context => context.dataset.label + '：' + context.parsed.y.toLocaleString('ja-JP', { maximumFractionDigits: 1 }) + data.unit,
        } } },
      },
    });
  }
  root.querySelectorAll('[data-period-mode]').forEach(function (button) {
    button.addEventListener('click', function () {
      mode = button.dataset.periodMode;
      root.querySelectorAll('[data-period-panel]').forEach(panel => { panel.hidden = panel.dataset.periodPanel !== mode; });
      root.querySelectorAll('[data-period-mode]').forEach(item => {
        const active = item === button;
        item.classList.toggle('is-active', active);
        item.setAttribute('aria-pressed', String(active));
      });
      render();
    });
  });
  async function load() {
    const requestVersion = ++version;
    if (controller) controller.abort();
    controller = new AbortController();
    const url = new URL(root.dataset.chartUrl, window.location.origin);
    url.searchParams.set('period_metric', select.value);
    status.textContent = '読み込み中…';
    root.setAttribute('aria-busy', 'true');
    retry.hidden = true;
    try {
      const response = await fetch(url, { signal: controller.signal, headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      if (!response.ok) throw new Error('request failed');
      const next = await response.json();
      if (requestVersion !== version) return;
      data = next;
      render();
      status.textContent = data.label + 'を表示しています。';
    } catch (error) {
      if (requestVersion !== version || error.name === 'AbortError') return;
      status.textContent = '取得できませんでした。現在のグラフは「' + data.label + '」です。再試行してください。';
      retry.hidden = false;
    } finally {
      if (requestVersion === version) root.setAttribute('aria-busy', 'false');
    }
  }
  select.addEventListener('change', load);
  retry.addEventListener('click', load);
})();
