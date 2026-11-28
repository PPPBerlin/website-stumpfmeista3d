// ============================================================
// Produktseite (beide Schaufenster): Galerie, Varianten, Preis,
// Bestand und Artikelnummer. Design-spezifische Klassen kommen
// per data-Attribut aus dem Template:
//   <div id="gallery" data-active="…" data-inactive="…">
//   <p id="stock-info" data-ok="…" data-out="…" data-ok-text="Auf Lager">
// Bestandszahlen werden bewusst nicht angezeigt (nur verfügbar / ausverkauft).
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  const gallery = document.getElementById('gallery');
  const main = document.getElementById('main-image');
  if (gallery && main) {
    const on = gallery.dataset.active.split(' ');
    const off = gallery.dataset.inactive.split(' ');
    gallery.querySelectorAll('.thumb').forEach(btn => {
      btn.addEventListener('click', () => {
        main.src = btn.dataset.src;
        main.alt = btn.dataset.alt;
        gallery.querySelectorAll('.thumb').forEach(b => { b.classList.remove(...on); b.classList.add(...off); });
        btn.classList.remove(...off); btn.classList.add(...on);
      });
    });
  }

  const info = document.getElementById('stock-info');
  const qty = document.getElementById('qty');
  const btn = document.getElementById('add-btn');
  const price = document.getElementById('price');
  const sku = document.getElementById('sku');

  function update() {
    const sel = document.querySelector('input[name="variant_id"]:checked') ||
                document.querySelector('input[type="hidden"][name="variant_id"]');
    if (!sel) {
      if (btn) btn.disabled = true;
      const first = document.querySelector('input[name="variant_id"]');
      if (first && sku) sku.textContent = first.dataset.sku;
      return;
    }
    if (price) price.textContent = sel.dataset.price;
    if (sku) sku.textContent = sel.dataset.sku;
    const available = sel.dataset.available === '1';
    if (btn) btn.disabled = !available;
    if (!info) return;
    if (!available) { info.textContent = 'Ausverkauft'; info.className = info.dataset.out; }
    else { info.textContent = info.dataset.okText || 'Auf Lager'; info.className = info.dataset.ok; }
  }
  document.querySelectorAll('input[name="variant_id"]').forEach(r => r.addEventListener('change', update));
  update();
});
