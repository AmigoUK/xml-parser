// Inicjalizacja Swagger UI (poza HTML — CSP bez inline <script>).
(function () {
  var el = document.getElementById("swagger");
  SwaggerUIBundle({ url: el.dataset.specUrl, dom_id: "#swagger", validatorUrl: null });
})();
