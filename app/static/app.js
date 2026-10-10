// Potwierdzenie akcji formularzy: <form data-confirm="Pytanie?"> (zamiast inline onsubmit — CSP).
document.addEventListener("submit", function (event) {
  var form = event.target.closest("form[data-confirm]");
  if (form && !window.confirm(form.dataset.confirm)) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
}, true);
