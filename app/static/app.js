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

// Formularz „Wgraj fakturę”: nazwa wybranego albo upuszczonego pliku. Komponent Alpine.js w buildzie CSP — metody
// zamiast wyrażeń w atrybutach (przypisanie do $refs.f.files i `?.` nie są w nim dozwolone).
document.addEventListener("alpine:init", function () {
  Alpine.data("uploadForm", function () {
    return {
      name: "",
      submitting: false,
      // Powrót przyciskiem „Wstecz” (bfcache) przywraca stronę ze stanem „Przetwarzanie…” — odblokuj przycisk.
      init() { window.addEventListener("pageshow", (e) => { if (e.persisted) this.submitting = false; }); },
      noop() {},
      // Blokada podwójnego wysłania: przycisk wyłączony po pierwszym submit (ustawiane przez @submit w szablonie).
      submitted() { this.submitting = true; },
      submitLabel() { return this.submitting ? "Przetwarzanie…" : "Przetwórz"; },
      dropped(event) {
        this.$refs.f.files = event.dataTransfer.files;
        this.name = this.fileName(this.$refs.f.files);
      },
      changed(event) { this.name = this.fileName(event.target.files); },
      fileName(files) { return files && files.length ? files[0].name : ""; },
    };
  });
});
