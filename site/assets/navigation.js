const topbar = document.querySelector(".topbar");

// Translated navigation can wrap, so use the rendered height for section links.
function updateTopbarHeight() {
  document.documentElement.style.setProperty("--topbar-height", topbar.offsetHeight + "px");
}

updateTopbarHeight();
new ResizeObserver(updateTopbarHeight).observe(topbar);
