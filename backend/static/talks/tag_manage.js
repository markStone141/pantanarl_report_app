(function () {
  const input = document.getElementById("id_tag_query");
  const resultsWrap = document.getElementById("tag-manage-results");
  const baseUrlEl = document.getElementById("tag-manage-base-url");
  if (!input || !resultsWrap || !baseUrlEl) return;

  let baseUrl = "";
  try {
    baseUrl = JSON.parse(baseUrlEl.textContent || '""');
  } catch (e) {
    baseUrl = window.location.pathname;
  }
  if (!baseUrl) baseUrl = window.location.pathname;

  let ajaxTimer = null;
  let currentController = null;

  function buildUrl(page) {
    const url = new URL(baseUrl, window.location.origin);
    const q = (input.value || "").trim();
    if (q) url.searchParams.set("q", q);
    if (page) url.searchParams.set("page", String(page));
    return url;
  }

  function updateHistory(url) {
    const relative = url.pathname + (url.search || "");
    window.history.replaceState({}, "", relative);
  }

  function fetchResults(page) {
    const url = buildUrl(page);
    if (currentController) currentController.abort();
    currentController = new AbortController();
    fetch(url.toString(), {
      method: "GET",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        Accept: "application/json",
      },
      credentials: "same-origin",
      signal: currentController.signal,
    })
      .then(function (response) {
        return response.json();
      })
      .then(function (data) {
        if (!data || !data.ok) return;
        resultsWrap.innerHTML = data.html || "";
        updateHistory(url);
      })
      .catch(function (error) {
        if (error && error.name === "AbortError") return;
      });
  }

  function queueFetch() {
    if (ajaxTimer) window.clearTimeout(ajaxTimer);
    ajaxTimer = window.setTimeout(function () {
      fetchResults();
    }, 280);
  }

  input.addEventListener("input", queueFetch);
  input.addEventListener("keydown", function (event) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    if (ajaxTimer) window.clearTimeout(ajaxTimer);
    fetchResults();
  });

  resultsWrap.addEventListener("click", function (event) {
    const link = event.target.closest(".tag-pagination a[href]");
    if (!link) return;
    event.preventDefault();
    const href = link.getAttribute("href") || "";
    const parsed = new URL(href, window.location.origin);
    const page = parsed.searchParams.get("page") || "";
    fetchResults(page);
  });
})();
