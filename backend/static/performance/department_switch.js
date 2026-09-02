(function () {
  const root = document.querySelector("[data-performance-department-switch-root]");
  const select = root?.querySelector("[data-performance-department-switch]");
  const status = root?.querySelector("[data-performance-department-status]");
  if (!root || !select) {
    return;
  }

  let activeRequest = null;

  function buildUrl(departmentId) {
    const url = new URL(select.dataset.switchUrl || window.location.href, window.location.origin);
    const currentParams = new URLSearchParams(window.location.search);
    currentParams.set("dashboard_department", departmentId);
    currentParams.delete("status");
    url.search = currentParams.toString();
    return url;
  }

  function destroyDashboardCharts(container) {
    if (!container || typeof window.Chart === "undefined" || typeof window.Chart.getChart !== "function") {
      return;
    }
    container.querySelectorAll("canvas").forEach(function (canvas) {
      const chart = window.Chart.getChart(canvas);
      if (chart) {
        chart.destroy();
      }
    });
  }

  async function loadDepartment(departmentId, options) {
    const currentContent = document.querySelector("[data-performance-dashboard-content]");
    if (!currentContent) {
      window.location.assign(buildUrl(departmentId).toString());
      return;
    }

    if (activeRequest) {
      activeRequest.abort();
    }
    const requestController = new AbortController();
    activeRequest = requestController;
    const requestUrl = buildUrl(departmentId);
    const previousValue = select.dataset.confirmedValue || select.value;
    select.disabled = true;
    currentContent.setAttribute("aria-busy", "true");
    if (status) {
      status.textContent = "部署を切り替えています。";
    }

    try {
      const response = await fetch(requestUrl, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal: requestController.signal,
      });
      if (!response.ok) {
        throw new Error("department switch failed");
      }
      const documentFragment = new DOMParser().parseFromString(await response.text(), "text/html");
      const nextContent = documentFragment.querySelector("[data-performance-dashboard-content]");
      if (!nextContent) {
        throw new Error("dashboard content missing");
      }
      destroyDashboardCharts(currentContent);
      currentContent.replaceWith(nextContent);
      select.dataset.confirmedValue = departmentId;
      if (options?.updateHistory !== false) {
        window.history.pushState({ dashboardDepartment: departmentId }, "", requestUrl);
      }
      if (typeof window.initPerformanceDashboard === "function") {
        window.initPerformanceDashboard();
      }
      if (status) {
        status.textContent = "表示する部署を切り替えました。";
      }
    } catch (error) {
      if (error.name === "AbortError") {
        return;
      }
      select.value = previousValue;
      if (status) {
        status.textContent = "部署を切り替えられませんでした。もう一度お試しください。";
      }
    } finally {
      if (activeRequest === requestController) {
        select.disabled = false;
        const latestContent = document.querySelector("[data-performance-dashboard-content]");
        latestContent?.setAttribute("aria-busy", "false");
        activeRequest = null;
      }
    }
  }

  select.dataset.confirmedValue = select.value;
  const initialUrl = new URL(window.location.href);
  if (!initialUrl.searchParams.has("dashboard_department")) {
    initialUrl.searchParams.set("dashboard_department", select.value);
    window.history.replaceState({ dashboardDepartment: select.value }, "", initialUrl);
  }
  select.addEventListener("change", function () {
    loadDepartment(select.value, { updateHistory: true });
  });

  window.addEventListener("popstate", function () {
    const departmentId = new URLSearchParams(window.location.search).get("dashboard_department");
    if (!departmentId || departmentId === select.value) {
      return;
    }
    select.value = departmentId;
    loadDepartment(departmentId, { updateHistory: false });
  });
})();
