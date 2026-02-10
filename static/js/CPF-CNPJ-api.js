document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("cpf"); // no seu HTML o id é "cpf"
  if (!input) return;

  // cria uma mensagem embaixo do input
  const msg = document.createElement("small");
  msg.style.display = "block";
  msg.style.marginTop = "6px";
  msg.style.fontWeight = "600";
  input.parentElement.appendChild(msg);

  const onlyDigits = (s) => (s || "").replace(/\D/g, "");

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

    // só valida quando tiver tamanho de CPF ou CNPJ
    if (!(digits.length === 11 || digits.length === 14)) {
      setMsg("", true);
      return;
    }

    setMsg("Validando...", true);

    try {
      const { res, data } = await validar(input.value);

      if (!res.ok) {
        setMsg(data.message || "Documento inválido.", false);
        return;
      }

      setMsg(data.message, data.ok);

      // opcional: marca visual no input
      input.style.borderColor = data.ok ? "green" : "crimson";
    } catch (e) {
      console.error(e);
      setMsg("Erro ao validar. Tente novamente.", false);
    }
  }

  input.addEventListener("blur", onCheck);
  input.addEventListener("input", () => {
    // limpa a cor enquanto digita
    input.style.borderColor = "";
    msg.textContent = "";
  });
});
