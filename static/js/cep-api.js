document.addEventListener("DOMContentLoaded", () => {
  const cepInput = document.getElementById("cep");
  if (!cepInput) return;

  const ruaInput = document.getElementById("rua");
  const bairroInput = document.getElementById("bairro");
  const cidadeInput = document.getElementById("cidade");
  const numeroInput = document.getElementById("numero");

  // ✅ Permite configurar a URL base no HTML:
  // <script>window.CEP_API_BASE = "/api/cep/";</script>
  const CEP_API_BASE = (window.CEP_API_BASE || "/api/cep/").replace(/\/+$/, "") + "/";

  const onlyNumbers = (v) => (v || "").replace(/\D/g, "");

  function formatCep(v) {
    const d = onlyNumbers(v).slice(0, 8);
    if (d.length > 5) return d.slice(0, 5) + "-" + d.slice(5);
    return d;
  }

  async function consultarCep(cep8) {
    const url = `${CEP_API_BASE}${cep8}/`;
    const res = await fetch(url, { headers: { "Accept": "application/json" } });

    // ✅ Se o backend devolver HTML (ex: 404 page/login), isso evita crash no res.json()
    const contentType = res.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
      const txt = await res.text();
      throw new Error(`Resposta não-JSON em ${url} (status ${res.status}). Primeiros chars: ${txt.slice(0, 120)}`);
    }

    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Erro ao consultar CEP");
    return data;
  }

  let lastCep = "";

  async function preencherEndereco() {
    const cep = onlyNumbers(cepInput.value);

    if (cep.length !== 8) return;
    if (cep === lastCep) return;
    lastCep = cep;

    try {
      const data = await consultarCep(cep);

      if (ruaInput) ruaInput.value = data.rua || "";
      if (bairroInput) bairroInput.value = data.bairro || "";
      if (cidadeInput) cidadeInput.value = data.cidade || "";

      if (numeroInput) numeroInput.focus();
    } catch (err) {
      console.error("Erro CEP:", err);
      // opcional: alert amigável
      // alert("Não foi possível consultar o CEP. Verifique e tente novamente.");
    }
  }

  // Formata enquanto digita
  cepInput.addEventListener("input", () => {
    const before = cepInput.value;
    cepInput.value = formatCep(before);

    if (onlyNumbers(cepInput.value).length === 8) {
      preencherEndereco();
    } else {
      // ✅ permite consultar novamente se o usuário mudar
      lastCep = "";
    }
  });

  // Consultar ao sair do campo
  cepInput.addEventListener("blur", preencherEndereco);
});
