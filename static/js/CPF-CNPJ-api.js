document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("cpf");
  if (!input) return;

  const form = input.closest("form");
  let cpfValido = false;

  const msg = document.createElement("small");
  msg.style.display = "block";
  msg.style.marginTop = "6px";
  msg.style.fontWeight = "600";
  input.parentElement.appendChild(msg);

  const onlyDigits = (s) => (s || "").replace(/\D/g, "");

  function maskCPF(value) {
    value = onlyDigits(value).slice(0, 11);

    if (value.length > 9) {
      return value.replace(/^(\d{3})(\d{3})(\d{3})(\d{1,2}).*/, "$1.$2.$3-$4");
    }
    if (value.length > 6) {
      return value.replace(/^(\d{3})(\d{3})(\d{1,3}).*/, "$1.$2.$3");
    }
    if (value.length > 3) {
      return value.replace(/^(\d{3})(\d{1,3}).*/, "$1.$2");
    }
    return value;
  }

  async function validar(value) {
    const res = await fetch(`/api/validate-document/?value=${encodeURIComponent(value)}`);
    const data = await res.json();
    return { res, data };
  }

  function setMsg(text, ok) {
    msg.textContent = text || "";
    msg.style.color = ok ? "green" : "crimson";
  }

  async function onCheck() {
    const digits = onlyDigits(input.value);

    cpfValido = false;

    if (!digits) {
      setMsg("", true);
      input.style.borderColor = "";
      return;
    }

    if (digits.length !== 11) {
      setMsg("CPF deve ter 11 dígitos.", false);
      input.style.borderColor = "crimson";
      return;
    }

    setMsg("Validando CPF...", true);

    try {
      const { res, data } = await validar(input.value);

      if (!res.ok || !data.ok) {
        setMsg(data.message || "CPF inválido.", false);
        input.style.borderColor = "crimson";
        cpfValido = false;
        return;
      }

      setMsg(data.message || "CPF válido.", true);
      input.style.borderColor = "green";
      cpfValido = true;

    } catch (e) {
      console.error(e);
      setMsg("Erro ao validar CPF.", false);
      input.style.borderColor = "crimson";
      cpfValido = false;
    }
  }

  input.addEventListener("input", () => {
    input.value = maskCPF(input.value);
    input.style.borderColor = "";
    msg.textContent = "";
    cpfValido = false;
  });

  input.addEventListener("blur", onCheck);

  if (form) {
    form.addEventListener("submit", async (e) => {
      const digits = onlyDigits(input.value);

      if (digits.length !== 11) {
        e.preventDefault();
        setMsg("Informe um CPF válido com 11 dígitos.", false);
        input.style.borderColor = "crimson";
        input.focus();
        return;
      }

      if (!cpfValido) {
        e.preventDefault();
        await onCheck();

        if (!cpfValido) {
          input.focus();
        }
      }
    });
  }
});