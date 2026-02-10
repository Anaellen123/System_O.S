document.addEventListener("DOMContentLoaded", () => {
  const cepInput = document.getElementById("cep");
  if (!cepInput) return; // só roda na página que tem CEP

  const ruaInput = document.getElementById("rua");
  const bairroInput = document.getElementById("bairro");
  const cidadeInput = document.getElementById("cidade");
  const numeroInput = document.getElementById("numero");

  const onlyNumbers = (v) => (v || "").replace(/\D/g, "");

  async function consultarCep(cep) {
    const res = await fetch(`/api/cep/${cep}/`);
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "Erro ao consultar CEP");
    }
    return data; // {rua, bairro, cidade, uf}
  }

  let lastCep = "";

  async function preencherEndereco() {
    const cep = onlyNumbers(cepInput.value);

    if (cep.length !== 8) return;
    if (cep === lastCep) return;
    lastCep = cep;

    console.log("Consultando CEP:", cep);

    try {
      const data = await consultarCep(cep);
      console.log("Resposta API CEP:", data);

      if (ruaInput) ruaInput.value = data.rua || "";
      if (bairroInput) bairroInput.value = data.bairro || "";
      if (cidadeInput) cidadeInput.value = data.cidade || "";

      if (numeroInput) numeroInput.focus();
    } catch (err) {
      console.error("Erro CEP:", err);
    }
  }

  cepInput.addEventListener("blur", preencherEndereco);
  cepInput.addEventListener("input", () => {
    if (onlyNumbers(cepInput.value).length === 8) {
      preencherEndereco();
    }
  });
});
