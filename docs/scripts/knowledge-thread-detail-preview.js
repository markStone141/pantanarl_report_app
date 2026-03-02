window.toggleReplies = function (btn) {
      if (!btn) return;
      var targetId = btn.getAttribute("data-target-replies");
      var target = targetId ? document.getElementById(targetId) : null;
      if (!target) return;
      var count = btn.getAttribute("data-reply-count") || "0";
      var willOpen = target.hidden;
      target.hidden = !willOpen;
      btn.setAttribute("aria-expanded", willOpen ? "true" : "false");
      btn.textContent = willOpen ? "返信を非表示（" + count + ")" : "返信を表示（" + count + ")";
    };

    (function () {
      var fab = document.getElementById("fab-followup");
      var overlay = document.getElementById("followup-overlay");
      var replyButtons = document.querySelectorAll(".followup-actions .comment-reply-btn");
      var replyContext = document.getElementById("reply-context");
      var ratingGroup = document.getElementById("rating-group");
      var filterButtons = document.querySelectorAll("[data-comment-filter]");
      var commentCards = Array.from(document.querySelectorAll(".followup[data-comment-type]"));
      var emptyNote = document.getElementById("comment-empty");
      var commentPageCount = document.getElementById("comment-page-count");
      var commentLoadMoreBtn = document.getElementById("comment-load-more-btn");
      var scrollTimer = null;
      var activeCommentFilter = "";
      var COMMENT_PAGE_SIZE = 10;
      var displayedCommentCount = COMMENT_PAGE_SIZE;

      function applyCommentFilter() {
        var matchedCards = [];
        commentCards.forEach(function (card) {
          var type = card.getAttribute("data-comment-type");
          if (!activeCommentFilter || type === activeCommentFilter) {
            matchedCards.push(card);
          }
        });
        var showCount = Math.min(displayedCommentCount, matchedCards.length);
        commentCards.forEach(function (card) {
          card.style.display = "none";
        });
        for (var i = 0; i < showCount; i += 1) {
          matchedCards[i].style.display = "";
        }
        if (emptyNote) {
          emptyNote.style.display = matchedCards.length === 0 ? "block" : "none";
        }
        if (commentPageCount) {
          commentPageCount.textContent = "表示: " + showCount + " / " + matchedCards.length;
        }
        if (commentLoadMoreBtn) {
          commentLoadMoreBtn.style.display = matchedCards.length > showCount ? "" : "none";
        }
      }

      function openOverlay(contextText) {
        if (overlay) overlay.classList.add("open");
        document.body.style.overflow = "hidden";
        if (fab) fab.classList.add("hidden");
        if (ratingGroup) {
          ratingGroup.style.display = contextText ? "none" : "";
        }
        if (replyContext) {
          if (contextText) {
            replyContext.style.display = "block";
            replyContext.textContent = "返信先: " + contextText;
          } else {
            replyContext.style.display = "none";
            replyContext.textContent = "";
          }
        }
      }
      function closeOverlay() {
        if (overlay) overlay.classList.remove("open");
        document.body.style.overflow = "";
        if (fab) fab.classList.remove("hidden");
      }
      function hideFabWhileScrolling() {
        if (!fab || (overlay && overlay.classList.contains("open"))) return;
        fab.classList.add("hidden");
        if (scrollTimer) clearTimeout(scrollTimer);
        scrollTimer = setTimeout(function () {
          if (!overlay || !overlay.classList.contains("open")) fab.classList.remove("hidden");
        }, 520);
      }

      if (fab) {
        fab.addEventListener("click", function () {
          openOverlay("");
        });
      }
      replyButtons.forEach(function (btn) {
        btn.addEventListener("click", function () {
          var article = btn.closest(".followup");
          var label = "コメント";
          if (article) {
            var labelEl = article.querySelector(".meta.row span");
            if (labelEl && labelEl.textContent) {
              label = labelEl.textContent.trim();
            }
          }
          openOverlay(label);
        });
      });
      document.querySelectorAll("[data-close-overlay]").forEach(function (btn) {
        btn.addEventListener("click", closeOverlay);
      });
      if (overlay) {
        overlay.addEventListener("click", function (event) {
          if (event.target === overlay) closeOverlay();
        });
      }
      filterButtons.forEach(function (btn) {
        btn.addEventListener("click", function () {
          var type = btn.getAttribute("data-comment-filter") || "";
          activeCommentFilter = activeCommentFilter === type ? "" : type;
          displayedCommentCount = COMMENT_PAGE_SIZE;
          filterButtons.forEach(function (other) {
            other.classList.toggle("active", other === btn && !!activeCommentFilter);
          });
          applyCommentFilter();
        });
      });
      if (commentLoadMoreBtn) {
        commentLoadMoreBtn.addEventListener("click", function () {
          displayedCommentCount += COMMENT_PAGE_SIZE;
          applyCommentFilter();
        });
      }
      window.addEventListener("scroll", hideFabWhileScrolling, { passive: true });
      applyCommentFilter();
    })();
