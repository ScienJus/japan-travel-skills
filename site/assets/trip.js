const trip = document.querySelector(".trip");
const controls = trip.querySelector(".day-buttons");
const buttons = Array.from(controls.querySelectorAll("button"));
const panels = buttons.map(button => document.getElementById(button.getAttribute("aria-controls")));

function showDay(selected) {
  buttons.forEach((button, index) => {
    const active = selected === index;
    button.setAttribute("aria-pressed", String(active));
    panels[index].hidden = !active;
  });
  trip.dataset.day = String(selected + 1);
}

buttons.forEach((button, index) => {
  button.addEventListener("click", () => showDay(index));
});
showDay(0);
controls.hidden = false;
