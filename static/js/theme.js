document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("themeToggle");
  const txt = document.getElementById("themeText");
  if (!btn || !txt) return;

  const icon = btn.querySelector("i.bi");

  function apply(mode) {
    const isDark = mode === "dark";

    document.body.classList.toggle("theme-dark", isDark);
    btn.setAttribute("aria-pressed", String(isDark));

    txt.textContent = `Tema: ${isDark ? "Escuro" : "Claro"}`;

    if (icon) {
      icon.classList.toggle("bi-sun", !isDark);
      icon.classList.toggle("bi-moon-stars", isDark);
    }

    localStorage.setItem("theme", mode);
  }

  // carrega preferência salva
  apply(localStorage.getItem("theme") || "light");

  btn.addEventListener("click", () => {
    const isDark = document.body.classList.contains("theme-dark");
    apply(isDark ? "light" : "dark");
  });
});
