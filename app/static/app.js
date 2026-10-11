// Potwierdzenie akcji formularzy: <form data-confirm="Pytanie?"> (zamiast inline onsubmit — CSP).
document.addEventListener("submit", function (event) {
  var form = event.target.closest("form[data-confirm]");
  if (form && !window.confirm(form.dataset.confirm)) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
}, true);

// Filtr wierszy tabeli: <input data-table-filter="#id-tabeli"> (np. tabela kodów problemów w Pomocy).
document.addEventListener("input", function (event) {
  var input = event.target.closest("input[data-table-filter]");
  if (!input) return;
  var table = document.querySelector(input.dataset.tableFilter);
  if (!table) return;
  var needle = input.value.trim().toLowerCase();
  table.querySelectorAll("tbody tr").forEach(function (row) {
    row.hidden = needle !== "" && row.textContent.toLowerCase().indexOf(needle) === -1;
  });
});
