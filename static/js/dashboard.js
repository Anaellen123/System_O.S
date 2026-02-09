document.addEventListener("DOMContentLoaded", function () {
  /* =========================
   *  BOTÕES DE PERÍODO
   * ========================= */
  const periodButtons = document.querySelectorAll(".segmented .seg");
  periodButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      periodButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      // se você colocou data-period="90/30/7" no HTML:
      const days = btn.dataset.period || btn.textContent.trim();
      console.log("Período selecionado:", days);

      // Futuro (quando você criar endpoint):
      // fetch(`/dashboard/data/?days=${days}`)
      //   .then(r => r.json())
      //   .then(({labels, data}) => updateChart(labels, data));
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
   *  SIDEBAR ATIVO
   * ========================= */
  const menuLinks = document.querySelectorAll(".menu-item");
  menuLinks.forEach((link) => {
    link.addEventListener("click", () => {
      menuLinks.forEach((l) => l.classList.remove("active"));
      link.classList.add("active");
    });
  });

  /* =========================
   *  GRÁFICO (Chart.js)
   * ========================= */
  const canvas = document.getElementById("requestsChart");
  if (!canvas) return;

  // garante que o Chart.js foi carregado antes
  if (typeof Chart === "undefined") {
    console.error("Chart.js não foi carregado. Confirme o script do Chart.js no dashboard_base.html.");
    return;
  }

  // lê os dados reais do template (json_script)
  const labelsEl = document.getElementById("chart-labels");
  const dataEl = document.getElementById("chart-data");

  let labels = [];
  let data = [];

  try {
    if (labelsEl) labels = JSON.parse(labelsEl.textContent || "[]");
    if (dataEl) data = JSON.parse(dataEl.textContent || "[]");
  } catch (e) {
    console.error("Erro ao ler chart_labels/chart_data do template:", e);
  }

  // fallback (caso você ainda não tenha passado chart_labels/chart_data na view)
  if (!labels.length || !data.length) {
    labels = ["01/01", "03/01", "05/01", "07/01", "09/01", "11/01", "13/01"];
    data = [0, 1, 0, 2, 1, 3, 2];
  }

  // cria o gráfico
  const chart = new Chart(canvas, {
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
      plugins: {
        legend: { display: false },
      },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true },
      },
    },
  });

  // função pronta para futuro update via fetch
  function updateChart(newLabels, newData) {
    chart.data.labels = newLabels || [];
    chart.data.datasets[0].data = newData || [];
    chart.update();
  }
});
