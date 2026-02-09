const passwordInput = document.getElementById("id_password");
const toggleBtn = document.getElementById("togglePassword");
const icon = toggleBtn.querySelector("i");

toggleBtn.addEventListener("click", () => {
    const show = passwordInput.type === "password";
    passwordInput.type = show ? "text" : "password";
    icon.className = show ? "bi bi-eye-slash" : "bi bi-eye";
  });