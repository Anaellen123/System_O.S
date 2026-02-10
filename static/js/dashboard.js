document.addEventListener("DOMContentLoaded", function () {

  /* =========================
   *  MENU ACCORDION (SIDEBAR)
   * ========================= */
  const accordions = document.querySelectorAll(".menu-accordion");

  accordions.forEach((acc) => {
    const toggle = acc.querySelector(".menu-toggle");
    if (!toggle) return;

    toggle.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();

      const isOpen = acc.classList.contains("is-open");

      // Fecha todos
      accordions.forEach((a) => {
        a.classList.remove("is-open");
        const btn = a.querySelector(".menu-toggle");
        if (btn) btn.setAttribute("aria-expanded", "false");
      });

      // Abre o clicado
      if (!isOpen) {
        acc.classList.add("is-open");
        toggle.setAttribute("aria-expanded", "true");
      }
    });
  });


  /* =========================
   *  BOTÕES DE PERÍODO
   * ========================= */
  const periodButtons = document.querySelectorAll(".segmented .seg");
  periodButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      periodButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const days = btn.dataset.period || btn.textContent.trim();
      console.log("Período selecionado:", days);
    });
  });


  /* =========================
   *  NOTIFICAÇÕES (exemplo)
   * ========================= */
  const notifBtn = document.querySelector(".notif");
  if (notifBtn) {
    notifBtn.addEventListener("click", () => {
      alert("Notificações em desenvolvimento 🚧");
    });
  }


  /* =========================
   *  GRÁFICO 1 (Solicitações) - Chart.js
   * ========================= */
  const canvas = document.getElementById("requestsChart");

  if (canvas) {
    if (typeof Chart === "undefined") {
      console.error("Chart.js não foi carregado.");
    } else {
      const labelsEl = document.getElementById("chart-labels");
      const dataEl = document.getElementById("chart-data");

      let labels = [];
      let data = [];

      try {
        if (labelsEl) labels = JSON.parse(labelsEl.textContent || "[]");
        if (dataEl) data = JSON.parse(dataEl.textContent || "[]");
      } catch (e) {
        console.error("Erro ao ler dados do gráfico:", e);
      }

      if (!labels.length || !data.length) {
        labels = ["01/01", "03/01", "05/01", "07/01", "09/01", "11/01", "13/01"];
        data = [0, 1, 0, 2, 1, 3, 2];
      }

      new Chart(canvas, {
        type: "line",
        data: {
          labels,
          datasets: [
            {
              label: "Solicitações",
              data,
              fill: true,
              tension: 0.35,
              pointRadius: 3,
              pointHoverRadius: 5,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { display: false } },
            y: { beginAtZero: true },
          },
        },
      });
    }
  }


  /* =========================
   *  GRÁFICO 2 (Bairros) - Chart.js
   * ========================= */
  const ctxBairros = document.getElementById("neighborhoodChart");

  if (ctxBairros) {
    if (typeof Chart === "undefined") {
      console.error("Chart.js não foi carregado (bairros).");
    } else {
      const bairrosLabelsEl = document.getElementById("bairros-labels");
      const bairrosDataEl = document.getElementById("bairros-data");

      let bairrosLabels = [];
      let bairrosData = [];

      try {
        if (bairrosLabelsEl) bairrosLabels = JSON.parse(bairrosLabelsEl.textContent || "[]");
        if (bairrosDataEl) bairrosData = JSON.parse(bairrosDataEl.textContent || "[]");
      } catch (e) {
        console.error("Erro ao ler dados do gráfico de bairros:", e);
      }

      // se não tiver dados, não quebra (só avisa)
      if (!bairrosLabels.length || !bairrosData.length) {
        console.warn("Sem dados para gráfico de bairros (bairros_labels/bairros_data vieram vazios).");
      }

      new Chart(ctxBairros, {
        type: "bar",
        data: {
          labels: bairrosLabels,
          datasets: [{
            label: "Quantidade de OS",
            data: bairrosData,
            borderWidth: 1
          }]
        },
        options: {
          indexAxis: "y",
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { x: { beginAtZero: true } }
        }
      });
    }
  }

});


/* =========================
 *  CEP AUTOCOMPLETE
 * ========================= */
(function () {
  const cepInput = document.getElementById("cep");
  if (!cepInput) return;

  const ruaInput = document.getElementById("rua");
  const bairroInput = document.getElementById("bairro");
  const cidadeInput = document.getElementById("cidade");
  const numeroInput = document.getElementById("numero");

  function onlyNumbers(str) {
    return (str || "").replace(/\D/g, "");
  }

  function limparEndereco() {
    if (ruaInput) ruaInput.value = "";
    if (bairroInput) bairroInput.value = "";
    if (cidadeInput) cidadeInput.value = "";
  }

  async function consultarCep(cep) {
    const res = await fetch(`/api/cep/${cep}/`);
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
    } catch (e) {
      console.error(e);
      limparEndereco();
      alert("Não consegui consultar o CEP. Verifique e tente novamente.");
    }
  }

  cepInput.addEventListener("blur", preencherEndereco);
  cepInput.addEventListener("input", () => {
    const cep = onlyNumbers(cepInput.value);
    if (cep.length === 8) preencherEndereco();
  });
})();
