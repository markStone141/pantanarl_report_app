(function () {
  const input = document.getElementById("id_tag_query");
  const listWrap = document.getElementById("tag-search-suggestions");
  const dataEl = document.getElementById("tag-manage-all-tag-names");
  if (!input || !listWrap || !dataEl) return;

  let allTags = [];
  try {
    const parsed = JSON.parse(dataEl.textContent || "[]");
    if (Array.isArray(parsed)) allTags = parsed;
  } catch (e) {
    allTags = [];
  }

  function closeList() {
    listWrap.classList.remove("is-open");
    listWrap.innerHTML = "";
  }

  function openList() {
    listWrap.classList.add("is-open");
  }

  function renderSuggestions() {
    const q = (input.value || "").trim().toLowerCase();
    if (!q) {
      closeList();
      return;
    }
    const matches = allTags
      .filter(function (name) {
        return (name || "").toLowerCase().indexOf(q) >= 0;
      })
      .slice(0, 20);

    if (!matches.length) {
      closeList();
      return;
    }

    listWrap.innerHTML = "";
    matches.forEach(function (name) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tag-search-suggestion-item";
      btn.textContent = name;
      btn.addEventListener("click", function () {
        input.value = name;
        closeList();
      });
      listWrap.appendChild(btn);
    });
    openList();
  }

  input.addEventListener("input", renderSuggestions);
  input.addEventListener("focus", renderSuggestions);
  document.addEventListener("click", function (event) {
    if (event.target === input || listWrap.contains(event.target)) return;
    closeList();
  });
})();
