(function () {
  const topbar = document.getElementById("dashboard-topbar");
  const toggle = document.getElementById("dashboard-drawer-toggle");
  const nav = document.getElementById("dashboard-drawer-nav");
  const backdrop = document.getElementById("dashboard-drawer-backdrop");
  if (!topbar || !toggle || !nav || !backdrop) return;

  function setOpen(isOpen) {
    topbar.classList.toggle("drawer-open", isOpen);
    document.body.classList.toggle("app-nav-open", isOpen);
    toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    toggle.setAttribute("aria-label", isOpen ? "メニューを閉じる" : "メニューを開く");
    toggle.innerHTML = isOpen
      ? '<i class="fa-solid fa-xmark" aria-hidden="true"></i>'
      : '<i class="fa-solid fa-bars" aria-hidden="true"></i>';
    backdrop.hidden = !isOpen;
    if (isOpen) {
      const currentLink = nav.querySelector("[aria-current='page']") || nav.querySelector("a");
      if (currentLink) currentLink.focus();
    }
  }

  setOpen(false);

  toggle.addEventListener("click", function () {
    setOpen(!topbar.classList.contains("drawer-open"));
  });

  backdrop.addEventListener("click", function () {
    setOpen(false);
    toggle.focus();
  });

  nav.addEventListener("click", function (event) {
    const link = event.target.closest("a[href]");
    if (!link || event.defaultPrevented) return;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

    event.preventDefault();
    const destination = link.href;
    setOpen(false);
    window.location.assign(destination);
  });

  document.addEventListener("pointerdown", function (event) {
    if (!topbar.classList.contains("drawer-open")) return;
    if (nav.contains(event.target) || toggle.contains(event.target)) return;
    setOpen(false);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Tab" && topbar.classList.contains("drawer-open")) {
      const focusable = Array.from(nav.querySelectorAll("a[href]"));
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    if (event.key === "Escape" && topbar.classList.contains("drawer-open")) {
      setOpen(false);
      toggle.focus();
    }
  });

  window.addEventListener("resize", function () {
    if (window.innerWidth > 768) setOpen(false);
  });
})();
