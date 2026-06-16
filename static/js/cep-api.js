document.addEventListener("DOMContentLoaded", () => {
  const cepInput =
    document.getElementById("cep") ||
    document.getElementById("id_cep") ||
    document.querySelector("[name='cep']");

  if (!cepInput) return;

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
    document.getElementById("id_uf") ||
    document.getElementById("uf") ||
    document.querySelector("[name='uf']");

  const onlyNumbers = (v) => (v || "").replace(/\D/g, "");

  function formatCep(v) {
    const d = onlyNumbers(v).slice(0, 8);
    return d.length > 5 ? d.slice(0, 5) + "-" + d.slice(5) : d;
  }

  function setValue(input, value) {
    if (!input) return;
    input.value = value || "";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function consultarCep(cep8) {
    const urlLocal = `/api/cep/${cep8}/`;

    try {
      const res = await fetch(urlLocal, {
        headers: { "Accept": "application/json" }
      });

      if (res.ok) {
        const data = await res.json();

        if (data && !data.erro) {
          return data;
        }
      }
    } catch (e) {
      console.warn("API local falhou, tentando ViaCEP...", e);
    }

    const resViaCep = await fetch(`https://viacep.com.br/ws/${cep8}/json/`);
    const dataViaCep = await resViaCep.json();

    if (dataViaCep.erro) {
      throw new Error("CEP não encontrado.");
    }

    return dataViaCep;
  }

  let lastCep = "";

  async function preencherEndereco() {
    const cep = onlyNumbers(cepInput.value);

    if (cep.length !== 8) return;
    if (cep === lastCep) return;

    lastCep = cep;

    try {
      const data = await consultarCep(cep);

      console.log("CEP DATA:", data);

      setValue(
        ruaInput,
        data.rua ||
        data.logradouro ||
        data.street ||
        ""
      );

      setValue(
        bairroInput,
        data.bairro ||
        data.neighborhood ||
        ""
      );

      setValue(
        cidadeInput,
        data.cidade ||
        data.localidade ||
        data.city ||
        ""
      );

      const uf =
        data.uf ||
        data.UF ||
        data.estado_sigla ||
        data.estado_uf ||
        "";

      setValue(ufInput, uf.toString().toUpperCase().slice(0, 2));

      if (numeroInput) {
        numeroInput.focus();
      }

    } catch (err) {
      lastCep = "";
      console.error("Erro ao consultar CEP:", err);
    }
  }

  cepInput.addEventListener("input", () => {
    cepInput.value = formatCep(cepInput.value);

    if (onlyNumbers(cepInput.value).length === 8) {
      preencherEndereco();
    } else {
      lastCep = "";
    }
  });

  cepInput.addEventListener("blur", preencherEndereco);

  if (onlyNumbers(cepInput.value).length === 8) {
    preencherEndereco();
  }
});