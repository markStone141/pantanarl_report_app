(function () {
  const dataNode = document.getElementById("performance-activity-trend-data");
  const canvas = document.getElementById("performance-activity-trend-chart");
  const decreaseButton = document.getElementById("performance-trend-decrease");
  const increaseButton = document.getElementById("performance-trend-increase");
  const visibleCountNode = document.getElementById("performance-trend-visible-count");
  const modeAmountButton = document.getElementById("performance-trend-mode-amount");
  const modeRateButton = document.getElementById("performance-trend-mode-rate");
  const summaryNode = document.getElementById("performance-trend-summary");
  const lineLabelNode = document.getElementById("performance-trend-line-label");
  if (!dataNode || !canvas) {
    return;
  }

  let trendData;
  try {
    trendData = JSON.parse(dataNode.textContent || "{}");
  } catch (error) {
    return;
  }
  if (!trendData.labels || !trendData.labels.length || typeof window.Chart === "undefined") {
    return;
  }

  const context = canvas.getContext("2d");
  if (!context) {
    return;
  }

  const allLabels = trendData.labels.slice();
  const allAmounts = trendData.amounts.slice();
  const allCounts = trendData.counts.slice();
  const allTargetAmounts = (trendData.target_amounts || []).slice();
  const allRateValues = (trendData.rate_values || []).slice();
  const minVisibleCount = Math.min(10, allLabels.length);
  let visibleCount = Math.min(trendData.default_visible_count || 30, allLabels.length);
  let currentMode = "amount";

  const amountGradient = context.createLinearGradient(0, 0, 0, 240);
  amountGradient.addColorStop(0, "rgba(39, 123, 211, 0.92)");
  amountGradient.addColorStop(1, "rgba(39, 123, 211, 0.28)");

  function sliceLatest(values) {
    return values.slice(Math.max(0, values.length - visibleCount));
  }

  const chart = new window.Chart(context, {
    data: {
      labels: sliceLatest(allLabels),
      datasets: [
        {
          type: "bar",
          label: "金額",
          data: sliceLatest(allAmounts),
          yAxisID: "yAmount",
          backgroundColor: amountGradient,
          borderColor: "#277bd3",
          borderWidth: 1,
          borderRadius: 6,
          barPercentage: 0.72,
          categoryPercentage: 0.82,
        },
        {
          type: "line",
          label: trendData.count_label || "件数",
          data: sliceLatest(allCounts),
          yAxisID: "yCount",
          borderColor: "#ef7d32",
          backgroundColor: "#ef7d32",
          borderWidth: 3,
          pointRadius: 3,
          pointHoverRadius: 4,
          tension: 0.28,
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
      plugins: {
        legend: {
          display: false,
        },
        tooltip: {
          callbacks: {
            label(tooltipItem) {
              if (tooltipItem.dataset.type === "bar") {
                return "金額 " + Number(tooltipItem.raw || 0).toLocaleString("ja-JP") + "円";
              }
              return (trendData.count_label || "件数") + " " + Number(tooltipItem.raw || 0).toLocaleString("ja-JP");
            },
          },
        },
      },
      scales: {
        x: {
          grid: {
            display: false,
          },
          ticks: {
            autoSkip: true,
            maxTicksLimit: 8,
            color: "#6b7280",
          },
        },
        yAmount: {
          position: "left",
          beginAtZero: true,
          grid: {
            color: "rgba(215, 227, 236, 0.9)",
          },
          ticks: {
            color: "#277bd3",
            callback(value) {
              return Number(value).toLocaleString("ja-JP") + "円";
            },
          },
        },
        yCount: {
          position: "right",
          beginAtZero: true,
          grid: {
            drawOnChartArea: false,
          },
          ticks: {
            color: "#ef7d32",
            precision: 0,
          },
        },
      },
    },
  });

  function sumValues(values) {
    return values.reduce(function (total, value) {
      return total + Number(value || 0);
    }, 0);
  }

  function updateSummary() {
    if (!summaryNode) {
      return;
    }
    if (currentMode === "rate") {
      const visibleAmounts = sliceLatest(allAmounts);
      const visibleTargets = sliceLatest(allTargetAmounts);
      summaryNode.textContent =
        "可視範囲の実績合計 " +
        sumValues(visibleAmounts).toLocaleString("ja-JP") +
        "円 / 目標合計 " +
        sumValues(visibleTargets).toLocaleString("ja-JP") +
        "円";
      return;
    }
    summaryNode.textContent = "";
  }

  function setMode(nextMode) {
    currentMode = nextMode;
    if (modeAmountButton) {
      modeAmountButton.classList.toggle("is-active", currentMode === "amount");
    }
    if (modeRateButton) {
      modeRateButton.classList.toggle("is-active", currentMode === "rate");
    }
    if (currentMode === "rate") {
      if (lineLabelNode) {
        lineLabelNode.textContent = "達成率（%）";
      }
      chart.data.datasets = [
        {
          type: "line",
          label: "日目達成率",
          data: sliceLatest(allRateValues),
          yAxisID: "yRate",
          borderColor: "#ef7d32",
          backgroundColor: "#ef7d32",
          borderWidth: 3,
          pointRadius: 3,
          pointHoverRadius: 4,
          tension: 0.28,
          spanGaps: false,
        },
      ];
      chart.options.scales.yAmount.display = false;
      chart.options.scales.yCount.display = false;
      chart.options.scales.yRate = {
        position: "left",
        beginAtZero: true,
        grid: {
          color: "rgba(215, 227, 236, 0.9)",
        },
        ticks: {
          color: "#ef7d32",
          callback(value) {
            return Number(value).toLocaleString("ja-JP") + "%";
          },
        },
      };
    } else {
      if (lineLabelNode) {
        lineLabelNode.textContent = trendData.count_label || "件数";
      }
      chart.data.datasets = [
        {
          type: "bar",
          label: "金額",
          data: sliceLatest(allAmounts),
          yAxisID: "yAmount",
          backgroundColor: amountGradient,
          borderColor: "#277bd3",
          borderWidth: 1,
          borderRadius: 6,
          barPercentage: 0.72,
          categoryPercentage: 0.82,
        },
        {
          type: "line",
          label: trendData.count_label || "件数",
          data: sliceLatest(allCounts),
          yAxisID: "yCount",
          borderColor: "#ef7d32",
          backgroundColor: "#ef7d32",
          borderWidth: 3,
          pointRadius: 3,
          pointHoverRadius: 4,
          tension: 0.28,
        },
      ];
      chart.options.scales.yAmount.display = true;
      chart.options.scales.yCount.display = true;
      delete chart.options.scales.yRate;
    }
    chart.update();
    updateSummary();
  }

  function syncControls() {
    if (visibleCountNode) {
      visibleCountNode.textContent = visibleCount + "稼働表示";
    }
    if (decreaseButton) {
      decreaseButton.disabled = visibleCount <= minVisibleCount;
    }
    if (increaseButton) {
      increaseButton.disabled = visibleCount >= allLabels.length;
    }
  }

  function updateVisibleRange(nextVisibleCount) {
    visibleCount = Math.max(minVisibleCount, Math.min(nextVisibleCount, allLabels.length));
    chart.data.labels = sliceLatest(allLabels);
    setMode(currentMode);
    syncControls();
  }

  if (decreaseButton) {
    decreaseButton.addEventListener("click", function () {
      updateVisibleRange(visibleCount - 10);
    });
  }
  if (increaseButton) {
    increaseButton.addEventListener("click", function () {
      updateVisibleRange(visibleCount + 10);
    });
  }
  if (modeAmountButton) {
    modeAmountButton.addEventListener("click", function () {
      setMode("amount");
    });
  }
  if (modeRateButton) {
    modeRateButton.addEventListener("click", function () {
      setMode("rate");
    });
  }

  syncControls();
  updateSummary();
})();
