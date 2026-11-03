// Pole pro čtečku (sekce 6.5): <input data-sken>. Čtečka funguje jako klávesnice a končí Enterem.
// První pole data-sken dostane fokus; Enter přeskočí na další pole formuláře,
// v posledním poli stiskne tlačítko s atributem data-potvrdit.
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const pole = [...document.querySelectorAll("input[data-sken], input[data-dalsi]")];
  const prvni = document.querySelector("input[data-sken]");
  if (prvni) prvni.focus();
  for (const [i, input] of pole.entries()) {
    input.addEventListener("keydown", (udalost) => {
      if (udalost.key !== "Enter") return;
      udalost.preventDefault();
      const dalsi = pole[i + 1];
      if (dalsi) {
        dalsi.focus();
        dalsi.select();
      } else {
        const tlacitko = input.form ? input.form.querySelector("[data-potvrdit]") : document.querySelector("[data-potvrdit]");
        if (tlacitko && !tlacitko.disabled) tlacitko.click();
      }
    });
  }
});
