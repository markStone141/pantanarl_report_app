(function () {
  const selectedDataEl = document.getElementById("post-edit-selected-tags-data");
  const selectedTags = selectedDataEl ? JSON.parse(selectedDataEl.textContent || "[]") : [];
  const selected = Array.isArray(selectedTags) ? selectedTags.slice() : [];
  const searchInput = document.getElementById("post-edit-tag-search");
  const optionButtons = Array.prototype.slice.call(document.querySelectorAll(".post-edit-tag-btn"));
  const selectedWrap = document.getElementById("post-edit-selected-tags");
  const hiddenWrap = document.getElementById("post-edit-selected-hidden");

  function render() {
    if (!selectedWrap || !hiddenWrap) return;
    selectedWrap.innerHTML = "";
    hiddenWrap.innerHTML = "";
    optionButtons.forEach(function (btn) {
      const tag = btn.getAttribute("data-tag") || "";
      if (selected.indexOf(tag) >= 0) {
        btn.classList.add("is-selected");
      } else {
        btn.classList.remove("is-selected");
      }
    });
    selected.forEach(function (tag) {
      const chip = document.createElement("span");
      chip.className = "post-edit-selected-tag";
      chip.textContent = tag;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "post-edit-selected-remove";
      remove.innerHTML = '<i class="fa-solid fa-xmark"></i>';
      remove.addEventListener("click", function () {
        const idx = selected.indexOf(tag);
        if (idx >= 0) selected.splice(idx, 1);
        render();
      });
      chip.appendChild(remove);
      selectedWrap.appendChild(chip);

      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = "tags";
      hidden.value = tag;
      hiddenWrap.appendChild(hidden);
    });
  }

  optionButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      const tag = btn.getAttribute("data-tag") || "";
      const idx = selected.indexOf(tag);
      if (idx >= 0) {
        selected.splice(idx, 1);
      } else {
        selected.push(tag);
      }
      render();
    });
  });

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      const q = (searchInput.value || "").trim().toLowerCase();
      optionButtons.forEach(function (btn) {
        const text = (btn.getAttribute("data-tag") || "").toLowerCase();
        btn.style.display = q === "" || text.indexOf(q) >= 0 ? "" : "none";
      });
    });
  }

  render();
})();
