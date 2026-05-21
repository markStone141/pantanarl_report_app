(function () {
  function initProgressDonuts() {
    if (typeof window.Chart === "undefined") {
      return;
    }
    const donutCanvases = document.querySelectorAll(".performance-progress-donut-chart");
    donutCanvases.forEach(function (canvas) {
      const context = canvas.getContext("2d");
      if (!context) {
        return;
      }
      if (canvas._performanceDonutChart) {
        canvas._performanceDonutChart.destroy();
      }
      canvas.width = 132;
      canvas.height = 132;
      canvas.style.width = "132px";
      canvas.style.height = "132px";
      const rawRate = canvas.dataset.rate;
      const chartValues = (canvas.dataset.chartValues || "")
        .split(",")
        .map(function (value) { return Number(value || 0); })
        .filter(function (value) { return !Number.isNaN(value); });
      const numericRate = rawRate === "" ? null : Number(rawRate);
      const boundedRate = numericRate == null || Number.isNaN(numericRate) ? 0 : Math.max(0, Math.min(numericRate, 100));
      const datasetValues = chartValues.length ? chartValues : (boundedRate > 0 ? [boundedRate, 100 - boundedRate] : [0, 100]);
      const datasetColors = chartValues.length >= 3 ? ["#0a84ff", "#f59e0b", "#dbe7f5"] : ["#0a84ff", "#dbe7f5"];
      canvas._performanceDonutChart = new window.Chart(context, {
        type: "doughnut",
        data: {
          datasets: [
            {
              data: datasetValues,
              backgroundColor: datasetColors,
              borderWidth: 0,
              hoverOffset: 0,
            },
          ],
        },
        options: {
          responsive: false,
          maintainAspectRatio: false,
          cutout: "68%",
          animation: false,
          events: [],
          plugins: {
            legend: { display: false },
            tooltip: { enabled: false },
          },
        },
      });
    });
  }

  if (document.readyState === "complete") {
    initProgressDonuts();
  } else {
    window.addEventListener("load", initProgressDonuts, { once: true });
  }

  const dataNode = document.getElementById("performance-activity-trend-data");
  const canvas = document.getElementById("performance-activity-trend-chart");
  const decreaseButton = document.getElementById("performance-trend-decrease");
  const increaseButton = document.getElementById("performance-trend-increase");
  const visibleCountNode = document.getElementById("performance-trend-visible-count");
  const modeAmountButton = document.getElementById("performance-trend-mode-amount");
  const modeRateButton = document.getElementById("performance-trend-mode-rate");
  const modeActivityButton = document.getElementById("performance-trend-mode-activity");
  const dateLinksNode = document.getElementById("performance-trend-date-links");
  const descriptionNode = document.getElementById("performance-trend-description");
  const primaryLegendNode = document.getElementById("performance-trend-primary-legend");
  const primarySwatchNode = document.getElementById("performance-trend-primary-swatch");
  const primaryLabelNode = document.getElementById("performance-trend-primary-label");
  const lineLabelNode = document.getElementById("performance-trend-line-label");
  const secondaryLegendNode = document.getElementById("performance-trend-secondary-legend");
  const secondarySwatchNode = document.getElementById("performance-trend-secondary-swatch");
  const summaryCards = {};
  if (!dataNode || !canvas) {
    return;
  }

  document.querySelectorAll("[data-performance-summary-card]").forEach(function (node) {
    const key = node.dataset.performanceSummaryCard;
    const valueNode = node.querySelector("[data-performance-summary-value]");
    if (key && valueNode) {
      summaryCards[key] = valueNode;
    }
  });

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
  const allDates = (trendData.dates || []).slice();
  const allAmounts = trendData.amounts.slice();
  const allCounts = trendData.counts.slice();
  const allAdjustmentAmounts = (trendData.adjustment_amounts || []).slice();
  const allAdjustmentCounts = (trendData.adjustment_counts || []).slice();
  const allApproachCounts = (trendData.approach_counts || []).slice();
  const allCommunicationCounts = (trendData.communication_counts || []).slice();
  const allTargetAmounts = (trendData.target_amounts || []).slice();
  const allRateValues = (trendData.rate_values || []).slice();
  const minVisibleCount = Math.min(10, allLabels.length);
  let visibleCount = Math.min(trendData.default_visible_count || 30, allLabels.length);
  let currentMode = "amount";
  const dayDetailContainer = document.getElementById("performance-day-detail-container");
  let dayDetailRequestId = 0;

  const amountGradient = context.createLinearGradient(0, 0, 0, 240);
  amountGradient.addColorStop(0, "rgba(39, 123, 211, 0.92)");
  amountGradient.addColorStop(1, "rgba(39, 123, 211, 0.28)");

  function sliceLatest(values) {
    return values.slice(Math.max(0, values.length - visibleCount));
  }

  function visibleDateAt(index) {
    const visibleDates = sliceLatest(allDates);
    if (index < 0 || index >= visibleDates.length) {
      return "";
    }
    return visibleDates[index] || "";
  }

  function sumValues(values) {
    return values.reduce(function (total, value) {
      return total + Number(value || 0);
    }, 0);
  }

  function formatCount(value) {
    const numericValue = Number(value || 0);
    return (trendData.count_label || "件数") === "件数相当"
      ? numericValue.toLocaleString("ja-JP")
      : numericValue.toLocaleString("ja-JP") + "件";
  }

  function formatAmount(value) {
    return Number(value || 0).toLocaleString("ja-JP") + "円";
  }

  function updateSummaryCards() {
    if (!Object.keys(summaryCards).length) {
      return;
    }
    const visibleLabels = sliceLatest(allLabels);
    if (summaryCards.approach_total) {
      summaryCards.approach_total.textContent = sumValues(sliceLatest(allApproachCounts)).toLocaleString("ja-JP");
    }
    if (summaryCards.communication_total) {
      summaryCards.communication_total.textContent = sumValues(sliceLatest(allCommunicationCounts)).toLocaleString("ja-JP");
    }
    if (summaryCards.count_total) {
      summaryCards.count_total.textContent = formatCount(sumValues(sliceLatest(allCounts)));
    }
    if (summaryCards.amount_total) {
      summaryCards.amount_total.textContent = formatAmount(sumValues(sliceLatest(allAmounts)));
    }
    if (summaryCards.adjustment_count_total) {
      summaryCards.adjustment_count_total.textContent = formatCount(sumValues(sliceLatest(allAdjustmentCounts)));
    }
    if (summaryCards.adjustment_amount_total) {
      summaryCards.adjustment_amount_total.textContent = formatAmount(sumValues(sliceLatest(allAdjustmentAmounts)));
    }
    if (summaryCards.active_days) {
      summaryCards.active_days.textContent = visibleLabels.length.toLocaleString("ja-JP") + "日";
    }
  }

  function updateLegend() {
    if (modeAmountButton) {
      modeAmountButton.classList.toggle("is-active", currentMode === "amount");
    }
    if (modeRateButton) {
      modeRateButton.classList.toggle("is-active", currentMode === "rate");
    }
    if (modeActivityButton) {
      modeActivityButton.classList.toggle("is-active", currentMode === "activity");
    }
    if (currentMode === "amount") {
      if (descriptionNode) {
        descriptionNode.textContent = "1稼働 = 実績が登録された1日です。金額は棒、" + (trendData.count_label || "件数") + "は折れ線で表示します。";
      }
      if (primaryLegendNode) {
        primaryLegendNode.hidden = false;
      }
      if (primarySwatchNode) {
        primarySwatchNode.className = "performance-trend-legend-swatch performance-trend-legend-swatch-bar";
      }
      if (primaryLabelNode) {
        primaryLabelNode.textContent = "金額";
      }
      if (lineLabelNode) {
        lineLabelNode.textContent = trendData.count_label || "件数";
      }
      if (secondaryLegendNode) {
        secondaryLegendNode.hidden = false;
      }
      if (secondarySwatchNode) {
        secondarySwatchNode.className = "performance-trend-legend-swatch performance-trend-legend-swatch-line";
      }
      return;
    }
    if (currentMode === "rate") {
      if (descriptionNode) {
        descriptionNode.textContent = "1稼働 = 実績が登録された1日です。各稼働日の目標金額に対する達成率を折れ線で表示します。";
      }
      if (primaryLegendNode) {
        primaryLegendNode.hidden = false;
      }
      if (primarySwatchNode) {
        primarySwatchNode.className = "performance-trend-legend-swatch performance-trend-legend-swatch-line";
      }
      if (primaryLabelNode) {
        primaryLabelNode.textContent = "達成率（%）";
      }
      if (secondaryLegendNode) {
        secondaryLegendNode.hidden = true;
      }
      return;
    }
    if (descriptionNode) {
      descriptionNode.textContent = "1稼働 = 実績が登録された1日です。アプローチ数とコミュニケーション数を折れ線で表示します。";
    }
    if (primaryLegendNode) {
      primaryLegendNode.hidden = false;
    }
    if (primarySwatchNode) {
      primarySwatchNode.className = "performance-trend-legend-swatch performance-trend-legend-swatch-line-primary";
    }
    if (primaryLabelNode) {
      primaryLabelNode.textContent = "アプローチ数";
    }
    if (lineLabelNode) {
      lineLabelNode.textContent = "コミュニケーション数";
    }
    if (secondaryLegendNode) {
      secondaryLegendNode.hidden = false;
    }
    if (secondarySwatchNode) {
      secondarySwatchNode.className = "performance-trend-legend-swatch performance-trend-legend-swatch-line-secondary";
    }
  }

  function loadDayDetail(selectedDate) {
    if (!dayDetailContainer || !dayDetailContainer.dataset.dayDetailUrl || !selectedDate) {
      return;
    }
    const requestId = dayDetailRequestId + 1;
    dayDetailRequestId = requestId;
    dayDetailContainer.classList.add("is-loading");
    const separator = dayDetailContainer.dataset.dayDetailUrl.indexOf("?") === -1 ? "?" : "&";
    fetch(dayDetailContainer.dataset.dayDetailUrl + separator + "date=" + encodeURIComponent(selectedDate), {
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
      credentials: "same-origin",
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("failed");
        }
        return response.text();
      })
      .then(function (html) {
        if (requestId !== dayDetailRequestId) {
          return;
        }
        dayDetailContainer.innerHTML = html;
      })
      .catch(function () {})
      .finally(function () {
        if (requestId === dayDetailRequestId) {
          dayDetailContainer.classList.remove("is-loading");
        }
      });
  }

  function renderDateLinks() {
    if (!dateLinksNode) {
      return;
    }
    const visibleDates = sliceLatest(allDates);
    const visibleLabels = sliceLatest(allLabels);
    dateLinksNode.innerHTML = "";
    visibleDates.forEach(function (value, index) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "performance-trend-date-link";
      button.dataset.date = value;
      button.textContent = visibleLabels[index] || value;
      button.addEventListener("click", function () {
        loadDayDetail(value);
      });
      dateLinksNode.appendChild(button);
    });
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
              if (currentMode === "rate") {
                const index = tooltipItem.dataIndex;
                const visibleAmounts = sliceLatest(allAmounts);
                const visibleTargets = sliceLatest(allTargetAmounts);
                const visibleRates = sliceLatest(allRateValues);
                const actualAmount = Number(visibleAmounts[index] || 0).toLocaleString("ja-JP");
                const targetAmount = Number(visibleTargets[index] || 0).toLocaleString("ja-JP");
                const rateValue = visibleRates[index];
                return [
                  "実績金額 " + actualAmount + "円",
                  "目標金額 " + targetAmount + "円",
                  "達成率 " + (rateValue == null ? "-" : Number(rateValue).toLocaleString("ja-JP") + "%"),
                ];
              }
              if (currentMode === "activity") {
                return (tooltipItem.dataset.label || "") + " " + Number(tooltipItem.raw || 0).toLocaleString("ja-JP");
              }
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

  function setMode(nextMode) {
    currentMode = nextMode;
    updateLegend();
    if (currentMode === "rate") {
      chart.data.datasets = [
        {
          type: "line",
          label: "達成率（%）",
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
    } else if (currentMode === "activity") {
      chart.data.datasets = [
        {
          type: "line",
          label: "アプローチ数",
          data: sliceLatest(allApproachCounts),
          yAxisID: "yCount",
          borderColor: "#277bd3",
          backgroundColor: "#277bd3",
          borderWidth: 3,
          pointRadius: 3,
          pointHoverRadius: 4,
          tension: 0.28,
        },
        {
          type: "line",
          label: "コミュニケーション数",
          data: sliceLatest(allCommunicationCounts),
          yAxisID: "yCount",
          borderColor: "#14b8a6",
          backgroundColor: "#14b8a6",
          borderWidth: 3,
          pointRadius: 3,
          pointHoverRadius: 4,
          tension: 0.28,
        },
      ];
      chart.options.scales.yAmount.display = false;
      chart.options.scales.yCount.display = true;
      delete chart.options.scales.yRate;
    } else {
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
    updateSummaryCards();
    renderDateLinks();
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
  if (modeActivityButton) {
    modeActivityButton.addEventListener("click", function () {
      setMode("activity");
    });
  }
  updateLegend();
  syncControls();
})();
