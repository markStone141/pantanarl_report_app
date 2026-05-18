(function () {
  const scopeSelect = document.querySelector("[data-metrics-v2-scope]");
  const scopeFields = document.querySelectorAll("[data-metrics-v2-scope-field]");
  const dataNode = document.getElementById("metrics-v2-dashboard-data");

  function toggleScopeFields() {
    if (!scopeSelect) {
      return;
    }
    const value = scopeSelect.value;
    scopeFields.forEach(function (field) {
      field.hidden = field.dataset.metricsV2ScopeField !== value;
    });
  }

  toggleScopeFields();
  if (scopeSelect) {
    scopeSelect.addEventListener("change", toggleScopeFields);
  }

  if (!dataNode || typeof window.Chart === "undefined") {
    return;
  }

  let payload;
  try {
    payload = JSON.parse(dataNode.textContent || "{}");
  } catch (_error) {
    return;
  }

  const defaultPalette = ["#1d7dfa", "#7bc4ff", "#56d4a7", "#f59e0b", "#ef4444", "#8b5cf6", "#14b8a6", "#94a3b8", "#f97316"];

  function createDoughnutChart(canvas, labels, values, options) {
    if (!canvas) {
      return;
    }
    const context = canvas.getContext("2d");
    if (!context) {
      return;
    }
    const chartOptions = options || {};
    new window.Chart(context, {
      type: "doughnut",
      data: {
        labels: labels,
        datasets: [
          {
            data: values,
            backgroundColor: defaultPalette.slice(0, values.length),
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: chartOptions.responsive !== false,
        maintainAspectRatio: chartOptions.maintainAspectRatio !== false,
        cutout: "66%",
        plugins: {
          legend: {
            display: chartOptions.legendDisplay !== false,
            position: "bottom",
            labels: {
              boxWidth: 10,
            },
          },
          tooltip: {
            enabled: chartOptions.tooltipEnabled !== false,
          },
        },
      },
    });
  }

  function createRateDoughnutChart(canvas, values) {
    if (!canvas) {
      return;
    }
    canvas.width = 132;
    canvas.height = 132;
    createDoughnutChart(canvas, ["比率", "残り"], values, {
      legendDisplay: false,
      tooltipEnabled: false,
      responsive: false,
      maintainAspectRatio: true,
    });
  }

  document.querySelectorAll(".metrics-v2-donut-chart").forEach(function (canvas) {
    const values = (canvas.dataset.chartValues || "")
      .split(",")
      .map(function (value) { return Number(value || 0); });
    createRateDoughnutChart(canvas, values);
  });

  document.querySelectorAll(".metrics-v2-distribution-chart").forEach(function (canvas) {
    const labels = (canvas.dataset.chartLabels || "").split("|").filter(Boolean);
    const values = (canvas.dataset.chartValues || "")
      .split(",")
      .map(function (value) { return Number(value || 0); });
    createDoughnutChart(canvas, labels, values, { legendDisplay: true, tooltipEnabled: true });
  });

  function buildComboChart(canvasId, chartPayload) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !chartPayload || !chartPayload.labels || !chartPayload.labels.length) {
      return null;
    }
    const context = canvas.getContext("2d");
    if (!context) {
      return null;
    }
    const gradient = context.createLinearGradient(0, 0, 0, 240);
    gradient.addColorStop(0, "rgba(29, 125, 250, 0.88)");
    gradient.addColorStop(1, "rgba(29, 125, 250, 0.18)");
    return new window.Chart(context, {
      data: {
        labels: chartPayload.labels,
        datasets: [
          {
            type: "bar",
            label: "金額",
            data: chartPayload.amounts,
            backgroundColor: gradient,
            borderColor: "#1d7dfa",
            borderWidth: 1,
            yAxisID: "yAmount",
            borderRadius: 8,
            barPercentage: 0.72,
            categoryPercentage: 0.76,
          },
          {
            type: "line",
            label: "件数",
            data: chartPayload.counts,
            borderColor: "#f59e0b",
            backgroundColor: "#f59e0b",
            borderWidth: 3,
            pointRadius: 3,
            tension: 0.28,
            yAxisID: "yCount",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: "index",
          intersect: false,
        },
        scales: {
          yAmount: {
            beginAtZero: true,
            position: "left",
          },
          yCount: {
            beginAtZero: true,
            position: "right",
            grid: {
              drawOnChartArea: false,
            },
          },
        },
      },
    });
  }

  buildComboChart("metrics-v2-month-history-chart", payload.month_history);
  buildComboChart("metrics-v2-period-history-chart", payload.period_history);

  const rankingCanvas = document.getElementById("metrics-v2-ranking-chart");
  const rankingList = document.getElementById("metrics-v2-ranking-list");
  const rankingButtons = document.querySelectorAll("[data-metrics-v2-ranking-button]");
  let rankingChart = null;

  function renderRanking(metricKey) {
    const metricPayload = payload.ranking && payload.ranking.metric_map ? payload.ranking.metric_map[metricKey] : null;
    if (!rankingCanvas || !metricPayload) {
      return;
    }
    if (rankingChart) {
      rankingChart.destroy();
    }
    const context = rankingCanvas.getContext("2d");
    rankingChart = new window.Chart(context, {
      type: "bar",
      data: {
        labels: metricPayload.labels,
        datasets: [
          {
            label: metricPayload.label,
            data: metricPayload.values,
            backgroundColor: "#1d7dfa",
            borderRadius: 8,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: false,
          },
          tooltip: {
            callbacks: {
              label: function (tooltipItem) {
                const value = tooltipItem.raw;
                if (metricPayload.unit === "%") {
                  return tooltipItem.dataset.label + " " + Number(value || 0).toFixed(1) + "%";
                }
                if (metricPayload.unit === "円") {
                  return tooltipItem.dataset.label + " " + Number(value || 0).toLocaleString("ja-JP") + "円";
                }
                return tooltipItem.dataset.label + " " + Number(value || 0).toLocaleString("ja-JP");
              },
            },
          },
        },
      },
    });

    if (rankingList) {
      rankingList.innerHTML = "";
      metricPayload.rows.forEach(function (row) {
        const item = document.createElement("a");
        item.className = "metric-card metrics-v2-ranking-row";
        item.href = row.detail_url;
        item.innerHTML = '<div class="row"><strong>' + row.member_name + '</strong><span>' + row.value_text + "</span></div>";
        rankingList.appendChild(item);
      });
    }
    rankingButtons.forEach(function (button) {
      button.classList.toggle("is-active", button.dataset.metricKey === metricKey);
    });
  }

  rankingButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      renderRanking(button.dataset.metricKey);
    });
  });
  renderRanking((payload.ranking && payload.ranking.default_metric) || "support_amount");

  const amountModeButtons = document.querySelectorAll("[data-metrics-v2-amount-mode]");
  const averageAmountCanvas = document.getElementById("metrics-v2-average-amount-chart");
  let averageAmountChart = null;

  function renderAverageAmount(mode) {
    const chartPayload = payload.average_amount_comparison ? payload.average_amount_comparison[mode] : null;
    if (!averageAmountCanvas || !chartPayload) {
      return;
    }
    if (averageAmountChart) {
      averageAmountChart.destroy();
    }
    averageAmountChart = new window.Chart(averageAmountCanvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: chartPayload.labels,
        datasets: [
          {
            label: chartPayload.title,
            data: chartPayload.values,
            backgroundColor: "#56d4a7",
            borderRadius: 8,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (tooltipItem) {
                if (tooltipItem.raw == null) {
                  return chartPayload.title + " -";
                }
                return chartPayload.title + " " + Number(tooltipItem.raw).toLocaleString("ja-JP") + "円";
              },
            },
          },
        },
      },
    });
    amountModeButtons.forEach(function (button) {
      button.classList.toggle("is-active", button.dataset.metricsV2AmountMode === mode);
    });
  }

  amountModeButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      renderAverageAmount(button.dataset.metricsV2AmountMode);
    });
  });
  renderAverageAmount("age");
})();
