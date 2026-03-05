document.addEventListener("DOMContentLoaded", () => {
  // totalSteps dinâmico (4 ou 5) conforme o HTML renderizado
  const stepsList = document.getElementById("stepsList");
  const steps = document.querySelectorAll(".step");
  const contents = document.querySelectorAll(".step-content");
  const totalSteps = steps.length || 4;

  let step = 1;

  const btnPrev = document.getElementById("btnPrev");
  const btnNext = document.getElementById("btnNext");

  const progressBar = document.getElementById("progressBar");
  const progressPct = document.getElementById("progressPct");
  const stepLabel = document.getElementById("stepLabel");

  const form = document.getElementById("solicitarForm");

  // Se algo essencial estiver faltando, o JS não roda
  if (!form || !btnPrev || !btnNext || !stepsList || !progressBar || !progressPct || !stepLabel) {
    console.error("Algum elemento essencial do formulário não foi encontrado. Verifique os IDs no HTML.");
    return;
  }

  // =========================
  // CPF CHECK
  // =========================
  const cpfInput = document.getElementById("cpf");
  const cpfError = document.getElementById("cpfError");
  const cpfApi = (window.CPF_CHECK_API || "/api/check-cpf/").replace(/\/+$/, "") + "/";

  let cpfBlocked = false;

  function onlyDigits(v) {
    return (v || "").replace(/\D/g, "");
  }

  function getPersonType() {
    const checked = form.querySelector('[name="person_type"]:checked');
    return checked ? checked.value : "PF";
  }

  function setCpfError(msg) {
    if (!cpfError) return;
    if (msg) {
      cpfError.style.display = "block";
      cpfError.textContent = msg;
    } else {
      cpfError.style.display = "none";
      cpfError.textContent = "";
    }
  }

  async function checkCpfExistsIfNeeded() {
    if (!cpfInput) return true;

    const personType = getPersonType();
    const digits = onlyDigits(cpfInput.value);

    // Só vale pra PF (CPF)
    if (personType !== "PF") {
      cpfBlocked = false;
      setCpfError("");
      return true;
    }

    // Só checa se tem 11 dígitos
    if (digits.length !== 11) {
      cpfBlocked = false;
      setCpfError("");
      return true;
    }

    try {
      const url = `${cpfApi}?cpf=${encodeURIComponent(digits)}`;
      const resp = await fetch(url, { method: "GET" });

      if (!resp.ok) {
        cpfBlocked = false;
        setCpfError("");
        return true;
      }

      const data = await resp.json();
      if (data && data.ok && data.exists) {
        cpfBlocked = true;
        setCpfError("Este CPF já possui cadastro. Faça login para continuar.");
        return false;
      }

      cpfBlocked = false;
      setCpfError("");
      return true;
    } catch (e) {
      cpfBlocked = false;
      setCpfError("");
      return true;
    }
  }

  if (cpfInput) {
    cpfInput.addEventListener("blur", () => { checkCpfExistsIfNeeded(); });
    cpfInput.addEventListener("input", () => { if (!cpfBlocked) setCpfError(""); });

    form.querySelectorAll('[name="person_type"]').forEach((r) => {
      r.addEventListener("change", () => { checkCpfExistsIfNeeded(); });
    });
  }

  // =========================
  // UPLOAD UI
  // =========================
  const anexosInput = document.getElementById("anexos");
  const uploadTitle = document.getElementById("uploadTitle");
  const uploadSub = document.getElementById("uploadSub");
  const uploadFeedback = document.getElementById("uploadFeedback");
  const uploadPreviews = document.getElementById("uploadPreviews");

  function resetUploadUI() {
    if (uploadTitle) uploadTitle.textContent = "Clique para selecionar arquivos";
    if (uploadSub) uploadSub.textContent = "PNG ou JPG";
    if (uploadFeedback) uploadFeedback.textContent = "";
    if (uploadPreviews) uploadPreviews.innerHTML = "";
  }

  function showUpload(files) {
    if (uploadTitle) uploadTitle.textContent = `${files.length} arquivo(s) selecionado(s)`;
    if (uploadSub) uploadSub.textContent = files.map((f) => f.name).join(", ");
    if (uploadFeedback) uploadFeedback.textContent = "Arquivos prontos para envio ✅";

    if (!uploadPreviews) return;
    uploadPreviews.innerHTML = "";

    files.forEach((file) => {
      const okTypes = ["image/png", "image/jpeg"];
      if (!okTypes.includes(file.type)) return;

      const img = document.createElement("img");
      img.className = "upload-thumb";
      img.alt = file.name;

      const url = URL.createObjectURL(file);
      img.src = url;
      img.onload = () => URL.revokeObjectURL(url);

      uploadPreviews.appendChild(img);
    });
  }

  function setFileList(input, files) {
    const dt = new DataTransfer();
    files.forEach((f) => dt.items.add(f));
    input.files = dt.files;
  }

  if (anexosInput) {
    resetUploadUI();

    anexosInput.addEventListener("change", () => {
      const files = Array.from(anexosInput.files || []);

      if (!files.length) {
        resetUploadUI();
        return;
      }

      const allowed = ["image/png", "image/jpeg"];
      const validFiles = [];
      const invalidFiles = [];

      files.forEach((f) => {
        if (allowed.includes(f.type)) validFiles.push(f);
        else invalidFiles.push(f.name);
      });

      if (invalidFiles.length) {
        alert(`Apenas JPG ou PNG são permitidos.\nRemovidos: ${invalidFiles.join(", ")}`);
        setFileList(anexosInput, validFiles);
      }

      if (!validFiles.length) {
        resetUploadUI();
        return;
      }

      showUpload(validFiles);
    });
  }

  // =========================
  // STEPS
  // =========================
  function setActiveStep(newStep) {
    step = Math.max(1, Math.min(totalSteps, newStep));

    steps.forEach((li) => {
      li.classList.toggle("active", Number(li.dataset.step) === step);
    });

    contents.forEach((c) => {
      c.classList.toggle("active", Number(c.dataset.content) === step);
    });

    const pct = Math.round((step / totalSteps) * 100);
    progressBar.style.width = `${pct}%`;
    progressPct.textContent = `${pct}%`;
    stepLabel.textContent = `Etapa ${step} de ${totalSteps}`;

    btnPrev.disabled = step === 1;
    btnNext.textContent = step === totalSteps ? "Enviar ✓" : "Próximo ›";

    if (step === totalSteps) fillReview();
  }

  function getValue(name) {
    const el = form.querySelector(`[name="${name}"]`);
    if (!el) return "";

    if (el.type === "radio") {
      const checked = form.querySelector(`[name="${name}"]:checked`);
      return checked ? checked.value : "";
    }
    return (el.value || "").trim();
  }

  function fillReview() {
    const full_name = getValue("full_name");
    const documentVal = getValue("document");
    const phone = getValue("phone");

    const service_type = getValue("service_type");
    const description = getValue("description");
    const notes = getValue("notes");

    const street = getValue("street");
    const number = getValue("number");
    const neighborhood = getValue("neighborhood");
    const city = getValue("city");
    const cep = getValue("cep");

    const reg_email = getValue("reg_email");

    const address = [street, number && `nº ${number}`, neighborhood, city, cep]
      .filter(Boolean)
      .join(", ");

    const map = {
      full_name,
      document: documentVal,
      phone,
      service_type,
      description,
      notes,
      address: address || "—",
      reg_email: reg_email || "—",
    };

    document.querySelectorAll("[data-r]").forEach((span) => {
      const key = span.getAttribute("data-r");
      span.textContent = map[key] ? map[key] : "—";
    });
  }

  function hasAccountStep() {
    // só existe se os inputs existem no DOM (template renderiza quando não está logado)
    return Boolean(document.getElementById("reg_email")) &&
           Boolean(document.getElementById("reg_password1")) &&
           Boolean(document.getElementById("reg_password2"));
  }

  async function validateStep(currentStep) {
    // Etapa 1: dados do solicitante
    if (currentStep === 1) {
      if (!getValue("document") || !getValue("full_name") || !getValue("phone")) return false;
      const ok = await checkCpfExistsIfNeeded();
      if (!ok) return false;
    }

    // Etapa 2: criar conta (somente se existir)
    if (currentStep === 2 && hasAccountStep()) {
      const email = getValue("reg_email");
      const p1 = getValue("reg_password1");
      const p2 = getValue("reg_password2");

      if (!email || !p1 || !p2) return false;
      if (p1 !== p2) return false;
    }

    // Localização e Serviço:
    // Se tem etapa de conta, fica na etapa 3; se não tem, fica na etapa 2.
    const serviceStep = hasAccountStep() ? 3 : 2;
    if (currentStep === serviceStep) {
      if (!getValue("service_type") || !getValue("description")) return false;
    }

    return true;
  }

  btnPrev.addEventListener("click", () => setActiveStep(step - 1));

  btnNext.addEventListener("click", async () => {
    if (step < totalSteps) {
      const ok = await validateStep(step);
      if (!ok) {
        alert("Preencha os campos obrigatórios desta etapa para continuar.");
        return;
      }
      setActiveStep(step + 1);
      return;
    }

    // valida tudo antes de enviar
    for (let s = 1; s <= totalSteps; s++) {
      const ok = await validateStep(s);
      if (!ok) {
        alert("Há campos obrigatórios não preenchidos.");
        setActiveStep(s);
        return;
      }
    }

    if (form.requestSubmit) form.requestSubmit();
    else form.submit();
  });

  stepsList.addEventListener("click", async (e) => {
    const li = e.target.closest(".step");
    if (!li) return;

    const target = Number(li.dataset.step);

    if (target > step) {
      const ok = await validateStep(step);
      if (!ok) {
        alert("Preencha os campos obrigatórios desta etapa para continuar.");
        return;
      }
    }

    setActiveStep(target);
  });

  // Inicial
  setActiveStep(1);
});

/* =========================================================
   SUCESSO + DOWNLOAD DO COMPROVANTE
   ========================================================= */
(function () {
  const created = Boolean(window.OS_CREATED);
  const targetWidth = Number(window.OS_TARGET_WIDTH || 900);

  const overlay = document.getElementById("successOverlay");
  const btnClose = document.getElementById("successClose");

  const receipt = document.getElementById("receiptCard");
  const btnDownload = document.getElementById("btnDownload");
  const btnCopyOs = document.getElementById("btnCopyOs");
  const osNumberEl = document.getElementById("receiptOsNumber");

  if (!overlay || !receipt) return;

  function open() {
    overlay.classList.add("open");
    overlay.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function close() {
    overlay.classList.remove("open");
    overlay.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  async function downloadReceipt(auto = false) {
    if (!window.html2canvas) {
      alert("Biblioteca html2canvas não carregou. Verifique o <script> no HTML.");
      return;
    }

    const canvas = await window.html2canvas(receipt, {
      backgroundColor: null,
      scale: 2,
      useCORS: true,
    });

    const ratio = canvas.height / canvas.width;
    const outW = targetWidth;
    const outH = Math.round(targetWidth * ratio);

    const out = document.createElement("canvas");
    out.width = outW;
    out.height = outH;

    const ctx = out.getContext("2d");
    ctx.drawImage(canvas, 0, 0, outW, outH);

    const dataUrl = out.toDataURL("image/png", 1.0);

    const a = document.createElement("a");
    const osText = (osNumberEl?.textContent || "OS").trim().replace(/\s+/g, "");
    a.download = `ordem-servico-${osText}.png`;
    a.href = dataUrl;
    document.body.appendChild(a);
    a.click();
    a.remove();

    if (auto && btnDownload) btnDownload.textContent = "Baixado ✓";
  }

  btnClose?.addEventListener("click", close);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay.classList.contains("open")) close();
  });

  btnDownload?.addEventListener("click", () => downloadReceipt(false));

  btnCopyOs?.addEventListener("click", async () => {
    const osText = (osNumberEl?.textContent || "").trim();
    if (!osText) return;

    try {
      await navigator.clipboard.writeText(osText);
      btnCopyOs.textContent = "Copiado ✓";
      setTimeout(() => (btnCopyOs.textContent = "Copiar OS"), 1200);
    } catch (err) {
      alert("Não foi possível copiar automaticamente. Copie manualmente: " + osText);
    }
  });

  if (created) {
    open();
    setTimeout(() => downloadReceipt(true), 350);
  }
})();