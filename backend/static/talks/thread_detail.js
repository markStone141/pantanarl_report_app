(function () {
  const buttons = document.querySelectorAll("[data-filter-kind]");
  const items = document.querySelectorAll(".knowledge-comment-item");
  let activeKind = "";

  function render() {
    items.forEach(function (item) {
      const kind = item.getAttribute("data-comment-kind") || "";
      item.hidden = activeKind !== "" && kind !== activeKind;
    });
    buttons.forEach(function (btn) {
      const isActive = (btn.getAttribute("data-filter-kind") || "") === activeKind;
      btn.classList.toggle("is-active", isActive);
    });
  }

  if (buttons.length && items.length) {
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        const kind = btn.getAttribute("data-filter-kind") || "";
        activeKind = activeKind === kind ? "" : kind;
        render();
      });
    });
  }

  const openComment = document.getElementById("knowledge-open-comment");
  const closeComment = document.getElementById("knowledge-close-comment");
  const cancelComment = document.getElementById("knowledge-cancel-comment");
  const commentOverlay = document.getElementById("knowledge-comment-overlay");
  const parentId = document.getElementById("knowledge-parent-id");
  const replyContext = document.getElementById("knowledge-reply-context");
  const commentBody = document.getElementById("knowledge-comment-body");
  const replyButtons = document.querySelectorAll("[data-reply-target]");
  const reactionBlock = document.getElementById("knowledge-reaction-block");
  const reactionCode = document.getElementById("knowledge-reaction-code");
  const reactionButtons = document.querySelectorAll("[data-reaction-code]");

  function openCommentSheet() {
    if (!commentOverlay) return;
    commentOverlay.classList.add("open");
    commentOverlay.setAttribute("aria-hidden", "false");
    if (commentBody) commentBody.focus();
  }

  function closeCommentSheet() {
    if (!commentOverlay) return;
    commentOverlay.classList.remove("open");
    commentOverlay.setAttribute("aria-hidden", "true");
    if (parentId) parentId.value = "";
    if (replyContext) {
      replyContext.classList.remove("is-open");
      replyContext.textContent = "";
    }
    if (reactionBlock) reactionBlock.style.display = "";
  }

  if (openComment) openComment.addEventListener("click", openCommentSheet);
  if (closeComment) closeComment.addEventListener("click", closeCommentSheet);
  if (cancelComment) cancelComment.addEventListener("click", closeCommentSheet);
  if (commentOverlay) {
    commentOverlay.addEventListener("click", function (event) {
      if (event.target === commentOverlay) closeCommentSheet();
    });
  }

  replyButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (parentId) parentId.value = btn.getAttribute("data-reply-target") || "";
      if (replyContext) {
        const author = btn.getAttribute("data-reply-author") || "";
        replyContext.textContent = "返信先: " + author;
        replyContext.classList.add("is-open");
      }
      if (reactionBlock) reactionBlock.style.display = "none";
      openCommentSheet();
    });
  });

  reactionButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      const code = btn.getAttribute("data-reaction-code") || "";
      if (!code) return;
      if (reactionCode) reactionCode.value = code;
      reactionButtons.forEach(function (other) {
        other.classList.toggle("is-selected", other === btn);
      });
    });
  });

  const favoriteForm = document.querySelector(".js-favorite-form");
  if (favoriteForm) {
    favoriteForm.addEventListener("submit", function (event) {
      event.preventDefault();
      const formData = new FormData(favoriteForm);
      fetch(favoriteForm.action, {
        method: "POST",
        body: formData,
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          Accept: "application/json",
        },
        credentials: "same-origin",
      })
        .then(function (response) {
          return response.json();
        })
        .then(function (data) {
          if (!data || !data.ok) return;
          const button = favoriteForm.querySelector(".js-favorite-btn");
          const icon = favoriteForm.querySelector(".js-favorite-icon");
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
          }
        })
        .catch(function () {});
    });
  }
})();
