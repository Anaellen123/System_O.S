document.addEventListener("DOMContentLoaded", () => {
  // ativa chips e escreve no input alvo (hidden ou select)
  document.querySelectorAll(".chips").forEach((group) => {
    const targetId = group.getAttribute("data-target");
    const target = targetId ? document.getElementById(targetId) : null;

    group.querySelectorAll(".chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        group.querySelectorAll(".chip").forEach((b) => b.classList.remove("is-active"));
        btn.classList.add("is-active");

        const val = btn.getAttribute("data-value");

        if (target) {
          // se for select do Django
          if (target.tagName === "SELECT") {
            target.value = val;
          } else {
            // hidden input
            target.value = val;
          }
        }
      });
    });
  });

  // esconde o select person_type do Django (porque estamos usando chips)
  const personSelect = document.getElementById("id_person_type");
  if (personSelect && personSelect.tagName === "SELECT") {
    personSelect.style.display = "none";
    // valor inicial
    personSelect.value = "PF";
  }
});
