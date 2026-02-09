document.addEventListener("DOMContentLoaded", () => {
  const totalSteps = 4;
  let step = 1;

  const stepsList = document.getElementById("stepsList");
  const contents = document.querySelectorAll(".step-content");
  const steps = document.querySelectorAll(".step");

  const btnPrev = document.getElementById("btnPrev");
  const btnNext = document.getElementById("btnNext");

  const progressBar = document.getElementById("progressBar");
  const progressPct = document.getElementById("progressPct");
  const stepLabel = document.getElementById("stepLabel");

  const form = document.getElementById("solicitarForm");

  // Se algo essencial estiver faltando, o JS não roda (evita travar silencioso)
  if (!form || !btnPrev || !btnNext || !stepsList || !progressBar || !progressPct || !stepLabel) {
    console.error("Algum elemento essencial do formulário não foi encontrado. Verifique os IDs no HTML.");
    return;
  }

  function setActiveStep(newStep) {
    step = Math.max(1, Math.min(totalSteps, newStep));

    // Sidebar
    steps.forEach((li) => {
      li.classList.toggle("active", Number(li.dataset.step) === step);
    });

    // Content
    contents.forEach((c) => {
      c.classList.toggle("active", Number(c.dataset.content) === step);
    });

    // Progress
    const pct = Math.round((step / totalSteps) * 100);
    progressBar.style.width = `${pct}%`;
    progressPct.textContent = `${pct}%`;
    stepLabel.textContent = `Etapa ${step} de ${totalSteps}`;

    // Buttons
    btnPrev.disabled = step === 1;
    btnNext.textContent = step === totalSteps ? "Enviar ✓" : "Próximo ›";

    // Preencher revisão
    if (step === 4) fillReview();
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
    };

    document.querySelectorAll("[data-r]").forEach((span) => {
      const key = span.getAttribute("data-r");
      span.textContent = map[key] ? map[key] : "—";
    });
  }

  function validateStep(currentStep) {
    // Etapa 1: obrigatórios
    if (currentStep === 1) {
      if (!getValue("document") || !getValue("full_name") || !getValue("phone")) return false;
    }

    // Etapa 2: obrigatórios
    if (currentStep === 2) {
      if (!getValue("service_type") || !getValue("description")) return false;
    }

    return true;
  }

  btnPrev.addEventListener("click", () => setActiveStep(step - 1));

  btnNext.addEventListener("click", () => {
    // Indo para próxima etapa
    if (step < totalSteps) {
      if (!validateStep(step)) {
        alert("Preencha os campos obrigatórios desta etapa para continuar.");
        return;
      }
      setActiveStep(step + 1);
      return;
    }

    // Etapa 4: enviar
    if (!validateStep(1) || !validateStep(2)) {
      alert("Há campos obrigatórios não preenchidos.");
      return;
    }

    // Melhor forma (respeita validações/handlers), fallback para submit direto
    if (form.requestSubmit) form.requestSubmit();
    else form.submit();
  });

  stepsList.addEventListener("click", (e) => {
    const li = e.target.closest(".step");
    if (!li) return;

    const target = Number(li.dataset.step);

    // Impedir pular pra frente sem preencher a etapa atual
    if (target > step && !validateStep(step)) {
      alert("Preencha os campos obrigatórios desta etapa para continuar.");
      return;
    }

    setActiveStep(target);
  });

  // Inicial
  setActiveStep(1);
});

