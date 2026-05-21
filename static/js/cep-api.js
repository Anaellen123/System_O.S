document.addEventListener("DOMContentLoaded", () => {

  // =========================
  // INPUT CEP
  // =========================
  const cepInput =
    document.getElementById("cep") ||
    document.getElementById("id_cep") ||
    document.querySelector("[name='cep']");

  if (!cepInput) return;

  // =========================
  // CAMPOS ENDEREÇO
  // =========================
  const ruaInput =
    document.getElementById("rua") ||
    document.getElementById("id_street") ||
    document.querySelector("[name='street']");

  const bairroInput =
    document.getElementById("bairro") ||
    document.getElementById("id_neighborhood") ||
    document.querySelector("[name='neighborhood']");

  const cidadeInput =
    document.getElementById("cidade") ||
    document.getElementById("id_city") ||
    document.querySelector("[name='city']");

  const numeroInput =
    document.getElementById("numero") ||
    document.getElementById("id_number") ||
    document.querySelector("[name='number']");

  const ufInput =
    document.getElementById("uf") ||
    document.getElementById("id_uf") ||
    document.querySelector("[name='uf']");

  // =========================
  // URL API CEP
  // =========================
  const CEP_API_BASE =
    (window.CEP_API_BASE || "/api/cep/")
      .replace(/\/+$/, "") + "/";

  // =========================
  // HELPERS
  // =========================
  const onlyNumbers = (v) => (v || "").replace(/\D/g, "");

  function formatCep(v) {
    const d = onlyNumbers(v).slice(0, 8);

    if (d.length > 5) {
      return d.slice(0, 5) + "-" + d.slice(5);
    }

    return d;
  }

  // =========================
  // CONSULTAR CEP
  // =========================
  async function consultarCep(cep8) {

    const url = `${CEP_API_BASE}${cep8}/`;

    const res = await fetch(url, {
      headers: {
        "Accept": "application/json"
      }
    });

    const contentType =
      res.headers.get("content-type") || "";

    // evita crash quando API devolve HTML
    if (!contentType.includes("application/json")) {

      const txt = await res.text();

      throw new Error(
        `Resposta não-JSON em ${url} ` +
        `(status ${res.status}). ` +
        `Primeiros chars: ${txt.slice(0, 120)}`
      );
    }

    const data = await res.json();

    if (!res.ok) {
      throw new Error(
        data.error || "Erro ao consultar CEP"
      );
    }

    return data;
  }

  // =========================
  // CONTROLE CEP
  // =========================
  let lastCep = "";

  // =========================
  // PREENCHER ENDEREÇO
  // =========================
  async function preencherEndereco() {

    const cep = onlyNumbers(cepInput.value);

    if (cep.length !== 8) return;

    if (cep === lastCep) return;

    lastCep = cep;

    try {

      const data = await consultarCep(cep);

      // LOG DEBUG
      console.log("CEP DATA:", data);

      if (ruaInput) {
        ruaInput.value =
          data.rua ||
          data.logradouro ||
          "";
      }

      if (bairroInput) {
        bairroInput.value =
          data.bairro || "";
      }

      if (cidadeInput) {
        cidadeInput.value =
          data.cidade ||
          data.localidade ||
          "";
      }

      if (ufInput) {
        ufInput.value =
          data.uf ||
          data.estado ||
          "";
      }

      if (numeroInput) {
        numeroInput.focus();
      }

    } catch (err) {

      console.error("Erro CEP:", err);

      // opcional:
      // alert("Não foi possível consultar o CEP.");
    }
  }

  // =========================
  // INPUT CEP
  // =========================
  cepInput.addEventListener("input", () => {

    const before = cepInput.value;

    cepInput.value = formatCep(before);

    if (onlyNumbers(cepInput.value).length === 8) {

      preencherEndereco();

    } else {

      // permite consultar novamente
      lastCep = "";
    }
  });

  // =========================
  // BLUR CEP
  // =========================
  cepInput.addEventListener("blur", preencherEndereco);

});