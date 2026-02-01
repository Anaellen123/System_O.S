document.addEventListener("DOMContentLoaded", function () {
    const form = document.getElementById("acompanharForm");

    if (form) {
        form.addEventListener("submit", function (event) {
            event.preventDefault();

            const osInput = form.querySelector("input");
            const numeroOS = osInput.value.trim();

            if (numeroOS === "") {
                alert("Por favor, informe o número da OS.");
                return;
            }

            // Aqui você pode futuramente fazer requisição AJAX
            console.log("Consultando OS:", numeroOS);

            alert("Consulta enviada para OS: " + numeroOS);
        });
    }
});
