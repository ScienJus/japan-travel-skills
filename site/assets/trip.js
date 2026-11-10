function connectChoices(controls, initial, onChange) {
  const buttons = Array.from(controls.querySelectorAll("button"));
  const panels = buttons.map(button => document.getElementById(button.getAttribute("aria-controls")));

  function select(selected) {
    buttons.forEach((button, index) => {
      const active = selected === index;
      button.setAttribute("aria-pressed", String(active));
      panels[index].hidden = !active;
    });
    onChange?.(selected);
  }

  buttons.forEach((button, index) => {
    button.addEventListener("click", () => select(index));
  });
  select(initial);
  controls.hidden = false;
}

connectChoices(document.querySelector(".demo-modes"), 0);

const trip = document.querySelector(".trip");
connectChoices(trip.querySelector(".day-buttons"), 1, selected => {
  trip.dataset.day = String(selected + 1);
});

const preview = document.querySelector(".map-preview");
const frame = preview.querySelector("iframe");
preview.addEventListener("toggle", () => {
  if (preview.open && !frame.hasAttribute("src")) {
    frame.src = frame.dataset.src;
  }
});
preview.hidden = false;
