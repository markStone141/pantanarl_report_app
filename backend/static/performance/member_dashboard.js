(function () {
  const dataNode = document.getElementById("performance-activity-trend-data");
  const canvas = document.getElementById("performance-activity-trend-chart");
  const decreaseButton = document.getElementById("performance-trend-decrease");
  const increaseButton = document.getElementById("performance-trend-increase");
  const visibleCountNode = document.getElementById("performance-trend-visible-count");
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
  const minVisibleCount = Math.min(10, allLabels.length);
  let visibleCount = Math.min(trendData.default_visible_count || 30, allLabels.length);

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
    chart.data.datasets[0].data = sliceLatest(allAmounts);
    chart.data.datasets[1].data = sliceLatest(allCounts);
    chart.update();
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

  syncControls();
})();
