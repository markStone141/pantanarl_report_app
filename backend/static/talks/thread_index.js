(function () {
    const openFilter = document.getElementById("knowledge-open-filter");
    const closeFilter = document.getElementById("knowledge-close-filter");
    const filterOverlay = document.getElementById("knowledge-filter-overlay");
    const createButton = document.getElementById("knowledge-create-button");
    const createOverlay = document.getElementById("knowledge-create-overlay");
    const openCreateDesktop = document.getElementById("knowledge-open-create");
    const closeCreate = document.getElementById("knowledge-close-create");
    const cancelCreate = document.getElementById("knowledge-create-cancel");
    const submitCreate = document.getElementById("knowledge-create-submit");
    const createForm = document.getElementById("knowledge-create-form");
    const createTitle = document.getElementById("knowledge-create-title");
    const createBody = document.getElementById("knowledge-create-body");
    const createTagSearch = document.getElementById("knowledge-create-tag-search");
    const createShowAllTagsButton = document.getElementById("knowledge-create-show-all-tags");
    const filterShowAllTagsButton = document.getElementById("knowledge-filter-show-all-tags");
    const filterShowAllTagsMobileButton = document.getElementById("knowledge-filter-show-all-tags-mobile");
    const createTagOptions = Array.prototype.slice.call(document.querySelectorAll("[data-create-tag-option]"));
    const createSelectedTags = document.getElementById("knowledge-create-selected-tags");
    const createSelectedHidden = document.getElementById("knowledge-create-selected-hidden");
    const selectedCreateTags = [];
    let createTagAllVisible = false;
    function openSheet() {
      if (!filterOverlay) return;
      filterOverlay.classList.add("open");
      filterOverlay.setAttribute("aria-hidden", "false");
    }
    function closeSheet() {
      if (!filterOverlay) return;
      filterOverlay.classList.remove("open");
      filterOverlay.setAttribute("aria-hidden", "true");
    }
    function openCreateSheet() {
      if (!createOverlay) return;
      createOverlay.classList.add("open");
      createOverlay.setAttribute("aria-hidden", "false");
    }
    function closeCreateSheet() {
      if (!createOverlay) return;
      createOverlay.classList.remove("open");
      createOverlay.setAttribute("aria-hidden", "true");
    }

    if (openFilter) {
      openFilter.addEventListener("click", openSheet);
    }
    if (closeFilter) {
      closeFilter.addEventListener("click", closeSheet);
    }
    if (filterOverlay) {
      filterOverlay.addEventListener("click", function (event) {
        if (event.target === filterOverlay) closeSheet();
      });
    }
    if (createButton) {
      createButton.addEventListener("click", openCreateSheet);
    }
    if (openCreateDesktop) {
      openCreateDesktop.addEventListener("click", function (event) {
        event.preventDefault();
        openCreateSheet();
      });
    }
    if (closeCreate) {
      closeCreate.addEventListener("click", closeCreateSheet);
    }
    if (cancelCreate) {
      cancelCreate.addEventListener("click", closeCreateSheet);
    }
    if (createOverlay) {
      createOverlay.addEventListener("click", function (event) {
        if (event.target === createOverlay) closeCreateSheet();
      });
    }
    document.addEventListener("click", function (event) {
      const trigger = event.target.closest("[data-open-create]");
      if (!trigger) return;
      event.preventDefault();
      openCreateSheet();
    });
    if (submitCreate) {
      submitCreate.addEventListener("click", function () {
        if (!createTitle || !createBody || !createForm) return;
        if ((createTitle.value || "").trim() === "") {
          window.alert("タイトルを入力してください。");
          createTitle.focus();
          return;
        }
        if ((createBody.value || "").trim() === "") {
          window.alert("本文を入力してください。");
          createBody.focus();
          return;
        }
        if (!selectedCreateTags.length) {
          window.alert("タグを1つ以上選択してください。");
          return;
        }
        createForm.submit();
      });
    }

    function renderCreateSelectedTags() {
      if (!createSelectedTags || !createSelectedHidden) return;
      createSelectedTags.innerHTML = "";
      createSelectedHidden.innerHTML = "";
      selectedCreateTags.forEach(function (tag) {
        const chip = document.createElement("span");
        chip.className = "knowledge-selected-tag";
        chip.textContent = tag;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "knowledge-selected-tag-remove";
        remove.innerHTML = '<i class="fa-solid fa-xmark"></i>';
        remove.addEventListener("click", function () {
          const idx = selectedCreateTags.indexOf(tag);
          if (idx >= 0) selectedCreateTags.splice(idx, 1);
          renderCreateSelectedTags();
        });
        chip.appendChild(remove);
        createSelectedTags.appendChild(chip);

        const hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = "tags";
        hidden.value = tag;
        createSelectedHidden.appendChild(hidden);
      });
    }

    createTagOptions.forEach(function (button) {
      button.addEventListener("click", function () {
        const tag = button.getAttribute("data-create-tag-option");
        if (!tag || selectedCreateTags.indexOf(tag) >= 0) return;
        selectedCreateTags.push(tag);
        renderCreateSelectedTags();
      });
    });

    function updateCreateShowAllButton() {
      if (!createShowAllTagsButton) return;
      const q = (createTagSearch && createTagSearch.value ? createTagSearch.value : "").trim();
      if (q !== "") {
        createShowAllTagsButton.style.display = "none";
        return;
      }
      createShowAllTagsButton.style.display = "";
      createShowAllTagsButton.textContent = createTagAllVisible
        ? "10件表示に戻す"
        : "すべてのタグを見る";
    }

    function applyCreateTagVisibility() {
      const q = (createTagSearch && createTagSearch.value ? createTagSearch.value : "").trim().toLowerCase();
      createTagOptions.forEach(function (button) {
        const text = (button.getAttribute("data-create-tag-option") || "").toLowerCase();
        if (q === "") {
          button.style.display = !createTagAllVisible && button.classList.contains("is-hidden-default") ? "none" : "";
          return;
        }
        button.style.display = text.indexOf(q) >= 0 ? "" : "none";
      });
      updateCreateShowAllButton();
    }

    if (createShowAllTagsButton) {
      createShowAllTagsButton.addEventListener("click", function () {
        createTagAllVisible = !createTagAllVisible;
        applyCreateTagVisibility();
      });
    }

    if (createTagSearch) {
      createTagSearch.addEventListener("input", function () {
        applyCreateTagVisibility();
      });
    }

    function bindTagSearch(inputId, groupName, showAllButtonId) {
      const input = document.getElementById(inputId);
      const group = document.querySelector('[data-tag-group="' + groupName + '"]');
      const showAllBtn = document.getElementById(showAllButtonId);
      if (!input || !group) return;
      const options = Array.prototype.slice.call(group.querySelectorAll("[data-tag-option]"));
      let allVisible = false;
      function updateButtonState() {
        if (!showAllBtn) return;
        const q = (input.value || "").trim();
        if (q !== "") {
          showAllBtn.style.display = "none";
          return;
        }
        showAllBtn.style.display = "";
        showAllBtn.textContent = allVisible ? "10件表示に戻す" : "すべてのタグを見る";
      }
      function applyVisibility() {
        const q = (input.value || "").trim().toLowerCase();
        options.forEach(function (el) {
          const text = (el.textContent || "").trim().toLowerCase();
          if (q === "") {
            el.style.display = !allVisible && el.classList.contains("is-hidden-default") ? "none" : "";
            return;
          }
          el.style.display = text.indexOf(q) >= 0 ? "" : "none";
        });
        updateButtonState();
      }
      if (showAllBtn) {
        showAllBtn.addEventListener("click", function () {
          allVisible = !allVisible;
          applyVisibility();
        });
      }
      input.addEventListener("input", function () {
        applyVisibility();
      });
      applyVisibility();
    }

    bindTagSearch("knowledge-tag-search", "desktop", "knowledge-filter-show-all-tags");
    bindTagSearch("knowledge-tag-search-mobile", "mobile", "knowledge-filter-show-all-tags-mobile");
    applyCreateTagVisibility();

    const threadCards = document.querySelectorAll(".js-thread-card");
    threadCards.forEach(function (card) {
      card.addEventListener("click", function (event) {
        const interactive = event.target.closest("a, button, form, input, textarea, select, label");
        if (interactive && card.contains(interactive)) return;
        const href = card.getAttribute("data-href");
        if (href) window.location.href = href;
      });
    });

    const root = document.querySelector('.knowledge-page');
    const favoriteOnlyActive = root ? root.dataset.favoriteOnly === '1' : false;
    function bindFavoriteForms(scope) {
      const forms = (scope || document).querySelectorAll(".js-favorite-form");
      forms.forEach(function (form) {
        if (form.dataset.boundFavorite === "1") return;
        form.dataset.boundFavorite = "1";
        form.addEventListener("submit", function (event) {
          event.preventDefault();
          const formData = new FormData(form);
          fetch(form.action, {
            method: "POST",
            body: formData,
            headers: {
              "X-Requested-With": "XMLHttpRequest",
              "Accept": "application/json"
            },
            credentials: "same-origin"
          })
            .then(function (response) { return response.json(); })
            .then(function (data) {
              if (!data || !data.ok) return;
              const button = form.querySelector(".js-favorite-btn");
              const icon = form.querySelector(".js-favorite-icon");
              if (!button || !icon) return;
              if (data.is_favorite) {
                button.setAttribute("title", "お気に入り解除");
                button.setAttribute("aria-label", "お気に入り解除");
                icon.className = "fa-solid fa-star js-favorite-icon";
                icon.style.color = "#d89b12";
              } else {
                button.setAttribute("title", "お気に入り");
                button.setAttribute("aria-label", "お気に入り");
                icon.className = "fa-regular fa-star js-favorite-icon";
                icon.style.color = "";
                if (favoriteOnlyActive) {
                  const card = form.closest(".js-thread-card");
                  if (card) card.remove();
                }
              }
            })
            .catch(function () {});
        });
      });
    }
    bindFavoriteForms(document);
  })();
