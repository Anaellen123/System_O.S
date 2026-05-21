document.addEventListener("DOMContentLoaded", () => {

  // =========================
  // CHIPS
  // =========================
  document.querySelectorAll(".chips").forEach((group) => {
    const targetId = group.getAttribute("data-target");
    const target = targetId ? document.getElementById(targetId) : null;

    group.querySelectorAll(".chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        group.querySelectorAll(".chip").forEach((b) => {
          b.classList.remove("is-active");
        });

        btn.classList.add("is-active");

        const val = btn.getAttribute("data-value");

        if (target) {
          target.value = val;
        }
      });
    });
  });

  // =========================
  // ESCONDE SELECT PERSON_TYPE
  // =========================
  const personSelect = document.getElementById("id_person_type");

  if (personSelect && personSelect.tagName === "SELECT") {
    personSelect.style.display = "none";
    personSelect.value = "PF";
  }

  // =========================
  // CPF - BUSCA E PREENCHIMENTO AUTOMÁTICO
  // =========================
  const cpfInput = document.getElementById("id_document");
  const cpfWarning = document.getElementById("cpf-warning");

  const nomeInput =
    document.getElementById("id_full_name") ||
    document.querySelector("[name='full_name']");

  const phoneInput =
    document.getElementById("id_phone") ||
    document.querySelector("[name='phone']");

  const cepInput =
    document.getElementById("id_cep") ||
    document.querySelector("[name='cep']");

  const streetInput =
    document.getElementById("id_street") ||
    document.querySelector("[name='street']");

  const numberInput =
    document.getElementById("id_number") ||
    document.querySelector("[name='number']");

  const neighborhoodInput =
    document.getElementById("id_neighborhood") ||
    document.querySelector("[name='neighborhood']");

  const cityInput =
    document.getElementById("id_city") ||
    document.querySelector("[name='city']");

  let cpfSuccessText = document.getElementById("cpf-success-text");

  if (!cpfSuccessText && cpfInput) {
    cpfSuccessText = document.createElement("div");
    cpfSuccessText.id = "cpf-success-text";
    cpfSuccessText.className = "cpf-success-text";
    cpfSuccessText.style.display = "none";
    cpfSuccessText.textContent = "CPF encontrado. Dados preenchidos automaticamente.";

    cpfInput.insertAdjacentElement("afterend", cpfSuccessText);
  }

  if (cpfInput && cpfWarning) {
    let timeoutCpf = null;

    function limparCampo(input) {
      if (!input) return;

      input.classList.remove("cpf-found");
      input.value = "";
      input.readOnly = false;
    }

    function marcarCampoVerde(input, bloquear = true) {
      if (!input) return;

      input.classList.add("cpf-found");
      input.readOnly = bloquear;
    }

    function limparStatusCPF() {
      cpfWarning.style.display = "none";

      if (cpfSuccessText) {
        cpfSuccessText.style.display = "none";
      }

      cpfInput.classList.remove("cpf-not-found");
      cpfInput.classList.remove("cpf-found");

      limparCampo(nomeInput);
      limparCampo(phoneInput);
      limparCampo(cepInput);
      limparCampo(streetInput);
      limparCampo(numberInput);
      limparCampo(neighborhoodInput);
      limparCampo(cityInput);
    }

    function marcarCpfEncontrado(data) {
      const usuario = data?.user || {};

      cpfWarning.style.display = "none";

      cpfInput.classList.remove("cpf-not-found");
      cpfInput.classList.add("cpf-found");

      if (cpfSuccessText) {
        cpfSuccessText.style.display = "flex";
      }

      if (nomeInput) {
        nomeInput.value = usuario.name || "";
        marcarCampoVerde(nomeInput, true);
      }

      if (phoneInput) {
        phoneInput.value = usuario.phone || "";
        marcarCampoVerde(phoneInput, Boolean(usuario.phone));
      }

      if (cepInput) {
        cepInput.value = usuario.cep || "";
        marcarCampoVerde(cepInput, Boolean(usuario.cep));
      }

      if (streetInput) {
        streetInput.value = usuario.street || "";
        marcarCampoVerde(streetInput, Boolean(usuario.street));
      }

      if (numberInput) {
        numberInput.value = usuario.number || "";
        marcarCampoVerde(numberInput, Boolean(usuario.number));
      }

      if (neighborhoodInput) {
        neighborhoodInput.value = usuario.neighborhood || "";
        marcarCampoVerde(neighborhoodInput, Boolean(usuario.neighborhood));
      }

      if (cityInput) {
        cityInput.value = usuario.city || "";
        marcarCampoVerde(cityInput, Boolean(usuario.city));
      }
    }

    function marcarCpfNaoEncontrado() {
      cpfInput.classList.remove("cpf-found");
      cpfInput.classList.add("cpf-not-found");

      if (cpfSuccessText) {
        cpfSuccessText.style.display = "none";
      }

      cpfWarning.style.display = "flex";

      limparCampo(nomeInput);
      limparCampo(phoneInput);
      limparCampo(cepInput);
      limparCampo(streetInput);
      limparCampo(numberInput);
      limparCampo(neighborhoodInput);
      limparCampo(cityInput);
    }

    async function verificarCPF() {
      const cpf = cpfInput.value.replace(/\D/g, "");

      limparStatusCPF();

      if (cpf.length !== 11) {
        return;
      }

      try {
        const response = await fetch(`/api/check-cpf-exists/?cpf=${cpf}`, {
          method: "GET",
          headers: {
            "X-Requested-With": "XMLHttpRequest"
          }
        });

        const data = await response.json();

        if (data.ok && data.exists === true) {
          marcarCpfEncontrado(data);
          return;
        }

        if (data.ok && data.exists === false) {
          marcarCpfNaoEncontrado();
        }

      } catch (error) {
        console.log("Erro ao verificar CPF:", error);
      }
    }

    function verificarAoDigitar() {
      clearTimeout(timeoutCpf);

      timeoutCpf = setTimeout(() => {
        verificarCPF();
      }, 300);
    }

    cpfInput.addEventListener("input", verificarAoDigitar);
    cpfInput.addEventListener("keyup", verificarAoDigitar);
    cpfInput.addEventListener("change", verificarCPF);

    cpfInput.addEventListener("paste", () => {
      setTimeout(verificarCPF, 100);
    });

    cpfInput.addEventListener("blur", verificarCPF);
  }
});