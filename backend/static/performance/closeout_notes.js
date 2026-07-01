(() => {
  const panel = document.querySelector("#closeout-filter-panel");
  const openButton = document.querySelector("[data-closeout-filter-open]");
  const closeButton = document.querySelector("[data-closeout-filter-close]");
  const backdrop = document.querySelector("[data-closeout-filter-backdrop]");

  if (!panel || !openButton || !closeButton || !backdrop) return;

  const closeFilter = () => {
    panel.classList.remove("is-open");
    backdrop.hidden = true;
    openButton.setAttribute("aria-expanded", "false");
    document.body.classList.remove("closeout-filter-open");
    openButton.focus();
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
})();
