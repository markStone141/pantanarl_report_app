(function () {
      const filterButtons = document.querySelectorAll("[data-filter-tag]");
      const tagSearchInput = document.getElementById("tag-search");
      const summaryEl = document.getElementById("filter-summary");
      const postList = document.getElementById("post-list");
      const fabStack = document.getElementById("fab-stack");
      const fabFilter = document.getElementById("fab-filter");
      const fabCreate = document.getElementById("fab-create");
      const filterOverlay = document.getElementById("filter-overlay");
      const createOverlay = document.getElementById("create-overlay");
      const tagMoreBtn = document.getElementById("tag-more-btn");
      const authorInput = document.getElementById("author-filter");
      const listCount = document.getElementById("list-count");
      const loadMoreBtn = document.getElementById("load-more-btn");
      const PAGE_SIZE = 20;
      const TAG_PAGE_SIZE = 8;
      let displayedCount = PAGE_SIZE;
      let visibleOrderedCards = [];
      let tagsExpanded = false;
      let scrollTimer = null;

      function parseTags(value) {
        return String(value || "")
          .split(",")
          .map(function (v) { return v.trim(); })
          .filter(Boolean);
      }

      function activeTags() {
        return Array.from(filterButtons)
          .filter(function (btn) { return btn.classList.contains("active"); })
          .map(function (btn) { return btn.getAttribute("data-filter-tag"); });
      }

      function sortTagButtonsByCount() {
        const parent = filterButtons[0]?.parentElement;
        if (!parent) return;
        Array.from(filterButtons)
          .sort(function (a, b) {
            return Number(b.getAttribute("data-tag-count") || "0") - Number(a.getAttribute("data-tag-count") || "0");
          })
          .forEach(function (btn) {
            parent.appendChild(btn);
          });
      }

      function applyTagCollapse() {
        const sortedButtons = Array.from(document.querySelectorAll("[data-filter-tag]"));
        const tagSearch = String(tagSearchInput?.value || "").trim().toLowerCase();
        sortedButtons.forEach(function (btn, index) {
          const label = (btn.getAttribute("data-filter-tag") || "").toLowerCase();
          const matched = !tagSearch || label.includes(tagSearch);
          const hiddenByDefault = !tagsExpanded && index >= TAG_PAGE_SIZE;
          const hideByCollapse = hiddenByDefault && !btn.classList.contains("active");
          btn.classList.toggle("is-collapsed", !matched || hideByCollapse);
        });
        if (tagMoreBtn) {
          if (sortedButtons.length <= TAG_PAGE_SIZE) {
            tagMoreBtn.style.display = "none";
          } else {
            tagMoreBtn.style.display = "";
            tagMoreBtn.textContent = tagsExpanded ? "閉じる" : "もっと表示";
          }
        }
      }

      function seedMockPosts() {
        if (!postList) return;
        const baseDate = new Date("2026-03-01T09:00:00");
        const tagsPool = [
          ["初回接触", "UN", "成功事例"],
          ["断り対応", "WV", "失敗事例"],
          ["クロージング", "UN", "成功事例"],
          ["初回接触", "WV", "成功事例"],
        ];
        for (let i = 0; i < 26; i += 1) {
          const tags = tagsPool[i % tagsPool.length];
          const date = new Date(baseDate.getTime() - i * 60 * 60 * 1000);
          const month = date.getMonth() + 1;
          const day = date.getDate();
          const hour = String(date.getHours()).padStart(2, "0");
          const min = String(date.getMinutes()).padStart(2, "0");
          const card = document.createElement("a");
          const author = "メンバー" + ((i % 6) + 1);
          card.className = "post-link";
          card.href = "knowledge-thread-detail-preview.html";
          card.setAttribute("data-activity-at", date.toISOString().slice(0, 19));
          card.setAttribute("data-new-post", i % 9 === 0 ? "1" : "0");
          card.setAttribute("data-new-comment", i % 4 === 0 ? "1" : "0");
          card.setAttribute("data-author", author);
          card.setAttribute("data-tags", tags.join(","));
          card.innerHTML =
            '<strong>モック投稿 ' + (i + 3) + "</strong>" +
            '<div class="meta">投稿者: ' + author + " / 2026-" + String(month).padStart(2, "0") + "-" + String(day).padStart(2, "0") + " " + hour + ":" + min + "</div>" +
            '<p class="muted">タグ絞り込みと未読優先ソートの挙動確認用モック投稿です。</p>' +
            '<div class="badge-row"><span class="state-badge state-new-comment">' + (i % 4 === 0 ? "新着コメントあり" : "更新あり") + '</span><span class="match-badge">一致 0</span></div>' +
            '<div class="sub-meta"><span class="sub-meta-item"><svg viewBox="0 0 24 24" fill="none"><path d="M4 6h16v10H7l-3 3V6z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>' + ((i % 7) + 1) + "</span>" +
            '<span class="sub-meta-item">最終更新 ' + month + "/" + day + " " + hour + ":" + min + "</span></div>" +
            '<div class="outcome-strip">' +
            '<span class="outcome-item outcome-good"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 10v10M11 10h7.5a2 2 0 0 1 1.9 2.6l-1.4 4.8A2 2 0 0 1 17.1 19H11V10zM7 10 9.6 4.8A1.8 1.8 0 0 1 11.2 4c.9.1 1.5.9 1.4 1.8L12 10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>' + ((i % 5) + 1) + "</span>" +
            '<span class="outcome-item outcome-keep"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M6 12h12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' + (i % 3) + "</span>" +
            '<span class="outcome-item outcome-retry"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M20 11a8 8 0 1 0 2.3 5.6M20 4v7h-7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' + (i % 2) + "</span>" +
            '<span class="outcome-item outcome-question"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M9.5 9a2.5 2.5 0 1 1 4.3 1.7c-.8.8-1.8 1.3-1.8 2.5M12 17h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' + (i % 4) + "</span>" +
            "</div>" +
            '<div class="tag-list"><span class="tag-chip">#' + tags[0] + '</span><span class="tag-chip">#' + tags[1] + '</span><span class="tag-chip">#' + tags[2] + "</span></div>";
          postList.appendChild(card);
        }
      }

      function updatePostOrdering() {
        if (!postList) return;
        const selectedTags = activeTags();
        const authorKeyword = String(authorInput?.value || "").trim().toLowerCase();
        const cards = Array.from(postList.querySelectorAll(".post-link"));

        const scored = cards.map(function (card) {
          const tags = parseTags(card.getAttribute("data-tags"));
          const matchCount = selectedTags.filter(function (tag) { return tags.includes(tag); }).length;
          const author = String(card.getAttribute("data-author") || "").toLowerCase();
          const authorMatched = !authorKeyword || author.includes(authorKeyword);
          const show = authorMatched && (selectedTags.length === 0 || matchCount > 0);
          const matchBadge = card.querySelector(".match-badge");
          if (matchBadge) {
            matchBadge.textContent = "一致 " + matchCount;
          }
          return {
            card: card,
            matchCount: matchCount,
            newComment: Number(card.getAttribute("data-new-comment") || "0"),
            newPost: Number(card.getAttribute("data-new-post") || "0"),
            activity: new Date(card.getAttribute("data-activity-at") || "1970-01-01").getTime(),
            show: show,
          };
        });

        scored.sort(function (a, b) {
          if (b.matchCount !== a.matchCount) return b.matchCount - a.matchCount;
          if (b.newComment !== a.newComment) return b.newComment - a.newComment;
          if (b.newPost !== a.newPost) return b.newPost - a.newPost;
          return b.activity - a.activity;
        });

        visibleOrderedCards = scored.filter(function (row) { return row.show; });
        const showCount = Math.min(displayedCount, visibleOrderedCards.length);
        scored.forEach(function (row) {
          row.card.style.display = "none";
          postList.appendChild(row.card);
        });
        for (let i = 0; i < showCount; i += 1) {
          visibleOrderedCards[i].card.style.display = "";
        }

        if (listCount) {
          listCount.textContent = "表示: " + showCount + " / " + visibleOrderedCards.length;
        }
        if (loadMoreBtn) {
          loadMoreBtn.style.display = visibleOrderedCards.length > showCount ? "" : "none";
        }

        if (summaryEl) {
          if (!selectedTags.length && !authorKeyword) {
            summaryEl.textContent = "絞り込み: なし";
          } else {
            const parts = [];
            if (selectedTags.length) parts.push(selectedTags.join(" / "));
            if (authorKeyword) parts.push("投稿者: " + authorKeyword);
            summaryEl.textContent = "絞り込み: " + parts.join(" | ");
          }
        }
      }

      function openOverlay(el) {
        if (!el) return;
        el.classList.add("open");
        document.body.style.overflow = "hidden";
      }

      function closeOverlay(el) {
        if (!el) return;
        el.classList.remove("open");
        if (!filterOverlay?.classList.contains("open") && !createOverlay?.classList.contains("open")) {
          document.body.style.overflow = "";
        }
      }

      function hideFabsWhileScrolling() {
        if (!fabStack) return;
        if (filterOverlay?.classList.contains("open") || createOverlay?.classList.contains("open")) return;
        fabStack.classList.add("hidden");
        if (scrollTimer) clearTimeout(scrollTimer);
        scrollTimer = setTimeout(function () {
          fabStack.classList.remove("hidden");
        }, 520);
      }

      const list = document.getElementById("post-list");
      if (!list) return;

      filterButtons.forEach(function (btn) {
        btn.addEventListener("click", function () {
          btn.classList.toggle("active");
          displayedCount = PAGE_SIZE;
          applyTagCollapse();
          updatePostOrdering();
        });
      });
      tagMoreBtn?.addEventListener("click", function () {
        tagsExpanded = !tagsExpanded;
        applyTagCollapse();
      });
      tagSearchInput?.addEventListener("input", function () {
        tagsExpanded = true;
        applyTagCollapse();
      });
      authorInput?.addEventListener("change", function () {
        displayedCount = PAGE_SIZE;
        updatePostOrdering();
      });
      loadMoreBtn?.addEventListener("click", function () {
        displayedCount += PAGE_SIZE;
        updatePostOrdering();
      });
      fabFilter?.addEventListener("click", function () {
        openOverlay(filterOverlay);
      });
      fabCreate?.addEventListener("click", function () {
        openOverlay(createOverlay);
      });
      document.querySelectorAll("[data-close-overlay]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          closeOverlay(btn.closest(".overlay"));
        });
      });
      [filterOverlay, createOverlay].forEach(function (overlay) {
        overlay?.addEventListener("click", function (event) {
          if (event.target === overlay) {
            closeOverlay(overlay);
          }
        });
      });
      window.addEventListener("scroll", hideFabsWhileScrolling, { passive: true });
      seedMockPosts();
      sortTagButtonsByCount();
      applyTagCollapse();
      updatePostOrdering();
    })();
