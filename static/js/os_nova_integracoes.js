document.addEventListener("DOMContentLoaded", () => {
  /* =========================================================
     Helpers
     ========================================================= */
  const $ = (...ids) => ids.map((id) => document.getElementById(id)).find(Boolean);

  const onlyNumbers = (v) => (v || "").replace(/\D/g, "");
  const debounce = (fn, ms = 250) => {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  };

  // usa as variáveis CSS do seu tema
  const cssVar = (name, fallback) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

  const COLOR_OK = cssVar("--blue-2", "#2563eb");
  const COLOR_BAD = "#e11d48"; // vermelho elegante
  const COLOR_WARN = "#f59e0b"; // amarelo elegante

  function mountMsgBelow(inputEl) {
    if (!inputEl) return null;

    // evita duplicar
    let msg = inputEl.parentElement?.querySelector(".field-msg");
    if (msg) return msg;

    msg = document.createElement("small");
    msg.className = "field-msg";
    msg.style.display = "block";
    msg.style.marginTop = "6px";
    msg.style.fontWeight = "800";
    msg.style.fontSize = "12px";
    msg.style.letterSpacing = ".01em";
    msg.style.opacity = ".95";
    inputEl.parentElement?.appendChild(msg);
    return msg;
  }

  function setFieldState(inputEl, msgEl, text, type) {
    if (msgEl) {
      msgEl.textContent = text || "";
      if (!text) msgEl.style.color = "";
      else if (type === "ok") msgEl.style.color = COLOR_OK;
      else if (type === "warn") msgEl.style.color = COLOR_WARN;
      else msgEl.style.color = COLOR_BAD;
    }

    if (inputEl) {
      if (!type) {
        inputEl.style.borderColor = "";
        inputEl.style.boxShadow = "";
        return;
      }
      if (type === "ok") {
        inputEl.style.borderColor = COLOR_OK;
        inputEl.style.boxShadow = `0 0 0 4px rgba(37,99,235,.14)`;
      } else if (type === "warn") {
        inputEl.style.borderColor = COLOR_WARN;
        inputEl.style.boxShadow = `0 0 0 4px rgba(245,158,11,.14)`;
      } else {
        inputEl.style.borderColor = COLOR_BAD;
        inputEl.style.boxShadow = `0 0 0 4px rgba(225,29,72,.14)`;
      }
    }
  }

  /* =========================================================
     CEP (Via sua API Django /api/cep/<cep>/ )
     ========================================================= */
  const cepInput = $("id_cep", "cep");
  const ruaInput = $("id_street", "rua");
  const bairroInput = $("id_neighborhood", "bairro");
  const cidadeInput = $("id_city", "cidade");
  const numeroInput = $("id_number", "numero");
  const ufInput = $("id_uf", "uf"); // se existir no seu form; se não existir, ignore

  if (cepInput) {
    const cepMsg = mountMsgBelow(cepInput);

    // URL base configurável: window.CEP_API_BASE = "/api/cep/";
    const CEP_API_BASE = (window.CEP_API_BASE || "/api/cep/").replace(/\/+$/, "") + "/";

    function formatCep(v) {
      const d = onlyNumbers(v).slice(0, 8);
      if (d.length > 5) return d.slice(0, 5) + "-" + d.slice(5);
      return d;
    }

    async function consultarCep(cep8) {
      const url = `${CEP_API_BASE}${cep8}/`;
      const res = await fetch(url, { headers: { Accept: "application/json" } });

      const contentType = res.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        const txt = await res.text();
        throw new Error(
          `Resposta não-JSON em ${url} (status ${res.status}). Primeiros chars: ${txt.slice(0, 120)}`
        );
      }

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Erro ao consultar CEP");
      return data;
    }

    let lastCep = "";

    async function preencherEndereco() {
      const cep = onlyNumbers(cepInput.value);

      if (cep.length === 0) {
        setFieldState(cepInput, cepMsg, "", null);
        lastCep = "";
        return;
      }

      if (cep.length !== 8) {
        setFieldState(cepInput, cepMsg, "Digite 8 dígitos do CEP.", "warn");
        lastCep = "";
        return;
      }

      if (cep === lastCep) return;
      lastCep = cep;

      setFieldState(cepInput, cepMsg, "Consultando CEP...", "warn");

      try {
        const data = await consultarCep(cep);

        if (ruaInput) ruaInput.value = data.rua || "";
        if (bairroInput) bairroInput.value = data.bairro || "";
        if (cidadeInput) cidadeInput.value = data.cidade || "";
        if (ufInput) ufInput.value = data.uf || "";

        setFieldState(cepInput, cepMsg, "CEP encontrado ✅", "ok");

        if (numeroInput) numeroInput.focus();
      } catch (err) {
        console.error("Erro CEP:", err);
        setFieldState(cepInput, cepMsg, "Não foi possível consultar o CEP.", "bad");
        lastCep = "";
      }
    }

    // Formata enquanto digita
    cepInput.addEventListener("input", () => {
      cepInput.value = formatCep(cepInput.value);

      const digits = onlyNumbers(cepInput.value);
      if (digits.length === 8) preencherEndereco();
      else {
        lastCep = "";
        setFieldState(cepInput, cepMsg, "", null);
      }
    });

    cepInput.addEventListener("blur", preencherEndereco);
  }

  /* =========================================================
     CPF/CNPJ (sua API /api/validate-document/?value=... )
     ========================================================= */
  const docInput = $("id_document", "cpf");
  if (docInput) {
    const docMsg = mountMsgBelow(docInput);

    async function validarDocumento(value) {
      const res = await fetch(`/api/validate-document/?value=${encodeURIComponent(value)}`, {
        headers: { Accept: "application/json" },
      });

      const contentType = res.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        const txt = await res.text();
        throw new Error(
          `Resposta não-JSON em validação (status ${res.status}). Primeiros chars: ${txt.slice(0, 120)}`
        );
      }

      const data = await res.json();
      return { res, data };
    }

    const onCheck = async () => {
      const digits = onlyNumbers(docInput.value);

      // só valida quando for CPF (11) ou CNPJ (14)
      if (!(digits.length === 11 || digits.length === 14)) {
        setFieldState(docInput, docMsg, "", null);
        return;
      }

      setFieldState(docInput, docMsg, "Validando documento...", "warn");

      try {
        const { res, data } = await validarDocumento(docInput.value);

        if (!res.ok) {
          setFieldState(docInput, docMsg, data.message || "Documento inválido.", "bad");
          return;
        }

        setFieldState(docInput, docMsg, data.message || "OK", data.ok ? "ok" : "bad");
      } catch (e) {
        console.error(e);
        setFieldState(docInput, docMsg, "Erro ao validar. Tente novamente.", "bad");
      }
    };

    docInput.addEventListener("blur", onCheck);

    // enquanto digita, limpa mensagem e estilo
    docInput.addEventListener(
      "input",
      debounce(() => {
        setFieldState(docInput, docMsg, "", null);
      }, 120)
    );
  }
});
