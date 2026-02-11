document.addEventListener("DOMContentLoaded", () => {
  const passwordInput = document.getElementById("id_password");
  const toggleBtn = document.getElementById("togglePassword");

  if (!passwordInput || !toggleBtn) return;

  const icon = toggleBtn.querySelector("i");

  toggleBtn.addEventListener("click", () => {
    const show = passwordInput.type === "password";
    passwordInput.type = show ? "text" : "password";

    if (icon) {
      icon.className = show ? "bi bi-eye-slash" : "bi bi-eye";
    }
  });
});
