(function () {
  const topbar = document.getElementById("dashboard-topbar");
  const toggle = document.getElementById("dashboard-drawer-toggle");
  const nav = document.getElementById("dashboard-drawer-nav");
  const backdrop = document.getElementById("dashboard-drawer-backdrop");
  if (!topbar || !toggle || !nav || !backdrop) return;

  function setOpen(isOpen) {
    topbar.classList.toggle("drawer-open", isOpen);
    toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    toggle.setAttribute("aria-label", isOpen ? "Close menu" : "Open menu");
    toggle.innerHTML = isOpen
      ? '<i class="fa-solid fa-xmark" aria-hidden="true"></i>'
      : '<i class="fa-solid fa-bars" aria-hidden="true"></i>';
    backdrop.hidden = !isOpen;
  }

  setOpen(false);

  toggle.addEventListener("click", function () {
    setOpen(!topbar.classList.contains("drawer-open"));
  });

  backdrop.addEventListener("click", function () {
    setOpen(false);
  });

  window.addEventListener("resize", function () {
    if (window.innerWidth > 768) setOpen(false);
  });
})();
