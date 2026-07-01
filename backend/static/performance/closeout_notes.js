(() => {
  const panel = document.querySelector("#closeout-filter-panel");
  const openButton = document.querySelector("[data-closeout-filter-open]");
  const closeButton = document.querySelector("[data-closeout-filter-close]");
  const backdrop = document.querySelector("[data-closeout-filter-backdrop]");
  const form = document.querySelector("[data-closeout-filter-form]");
  const results = document.querySelector("[data-closeout-results]");
  const count = document.querySelector("[data-closeout-count]");
  const scopeTitle = document.querySelector("#closeout-filter-title");
  const scopeInput = document.querySelector("[data-closeout-scope-input]");
  const scopeLinks = document.querySelectorAll("[data-closeout-scope]");

  if (!panel || !openButton || !closeButton || !backdrop || !form || !results) return;

  const closeFilter = (restoreFocus = true) => {
    panel.classList.remove("is-open");
    backdrop.hidden = true;
    openButton.setAttribute("aria-expanded", "false");
    document.body.classList.remove("closeout-filter-open");
    if (restoreFocus) openButton.focus();
  };

  const openFilter = () => {
    panel.classList.add("is-open");
    backdrop.hidden = false;
    openButton.setAttribute("aria-expanded", "true");
    document.body.classList.add("closeout-filter-open");
    closeButton.focus();
  };

  openButton.addEventListener("click", openFilter);
  closeButton.addEventListener("click", closeFilter);
  backdrop.addEventListener("click", closeFilter);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && panel.classList.contains("is-open")) {
      closeFilter();
    }
  });

  let debounceTimer = null;
  let activeRequest = null;

  const updateScope = (scopeKey, scopeLabel) => {
    if (scopeInput) scopeInput.value = scopeKey;
    if (scopeTitle) scopeTitle.textContent = scopeLabel;
    scopeLinks.forEach((link) => {
      link.classList.toggle("is-active", link.dataset.closeoutScope === scopeKey);
    });
  };

  const fetchResults = async (url, { closeOnSuccess = false } = {}) => {
    if (activeRequest) activeRequest.abort();
    activeRequest = new AbortController();
    results.classList.add("is-loading");

    try {
      const response = await fetch(url, {
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          Accept: "application/json",
        },
        signal: activeRequest.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      results.innerHTML = payload.results_html;
      if (count) count.textContent = payload.count;
      updateScope(payload.scope_key, payload.scope_label);
      window.history.replaceState({}, "", url);
      if (closeOnSuccess && window.matchMedia("(max-width: 700px)").matches) {
        closeFilter(false);
      }
    } catch (error) {
      if (error.name !== "AbortError") {
        window.location.assign(url);
      }
    } finally {
      results.classList.remove("is-loading");
    }
  };

  const formUrl = () => {
    const params = new URLSearchParams(new FormData(form));
    params.delete("page");
    return `${window.location.pathname}?${params.toString()}`;
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    fetchResults(formUrl(), { closeOnSuccess: true });
  });

  form.addEventListener("input", (event) => {
    if (event.target.name !== "q") return;
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(() => fetchResults(formUrl()), 350);
  });

  form.addEventListener("change", (event) => {
    const field = event.target;
    if (field.name === "q") return;
    if (field.name === "month" && field.value) {
      form.elements.period_id.value = "";
      form.elements.date_from.value = "";
      form.elements.date_to.value = "";
    } else if (field.name === "period_id" && field.value) {
      form.elements.month.value = "";
      form.elements.date_from.value = "";
      form.elements.date_to.value = "";
    } else if ((field.name === "date_from" || field.name === "date_to") && field.value) {
      form.elements.month.value = "";
      form.elements.period_id.value = "";
      if (scopeInput) scopeInput.value = "custom";
    }
    fetchResults(formUrl());
  });

  scopeLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      form.elements.month.value = "";
      form.elements.period_id.value = "";
      form.elements.date_from.value = "";
      form.elements.date_to.value = "";
      if (scopeInput) scopeInput.value = link.dataset.closeoutScope;
      fetchResults(formUrl());
    });
  });

  results.addEventListener("click", (event) => {
    const paginationLink = event.target.closest(".pagination a");
    if (!paginationLink) return;
    event.preventDefault();
    fetchResults(paginationLink.href);
  });

  window.addEventListener("popstate", () => window.location.reload());
})();
