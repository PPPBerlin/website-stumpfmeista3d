// ============================================================
// Produktseite (beide Schaufenster): Galerie, Optionen, Preis,
// Verfügbarkeit und Artikelnummer. Design-spezifische Klassen
// kommen per data-Attribut aus dem Template:
//   <div id="gallery" data-active="…" data-inactive="…">
//   <p id="stock-info" data-ok="…" data-out="…" data-na="…" data-ok-text="Auf Lager">
//   <script id="combos" type="application/json">{"<Wert-IDs>": {id, price, available, sku}}
// Bestandszahlen werden bewusst nicht angezeigt (nur verfügbar / ausverkauft).
// Optionsgruppe „Farbe“: das Bild, dessen Bildbeschreibung wie die Farbe
// heißt, wird angezeigt.
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  const gallery = document.getElementById('gallery');
  const main = document.getElementById('main-image');
  const thumbs = gallery ? [...gallery.querySelectorAll('.thumb')] : [];

  function showImage(btn) {
    if (!main || !btn) return;
    main.src = btn.dataset.src;
    main.alt = btn.dataset.alt;
    const on = gallery.dataset.active.split(' ');
    const off = gallery.dataset.inactive.split(' ');
    thumbs.forEach(b => { b.classList.remove(...on); b.classList.add(...off); });
    btn.classList.remove(...off); btn.classList.add(...on);
  }
  thumbs.forEach(btn => btn.addEventListener('click', () => showImage(btn)));

  const norm = s => (s || '').trim().toLowerCase().replace(/\s+/g, ' ');
  document.querySelectorAll('.option-group[data-color] input[type="radio"]').forEach(r => {
    r.addEventListener('change', () => {
      const match = thumbs.find(b => norm(b.dataset.alt) === norm(r.dataset.name));
      if (match) showImage(match);
    });
  });

  const combosEl = document.getElementById('combos');
  if (!combosEl) return;
  const combos = JSON.parse(combosEl.textContent || '{}');
  const hidden = document.getElementById('variant-id');
  const info = document.getElementById('stock-info');
  const btn = document.getElementById('add-btn');
  const price = document.getElementById('price');
  const sku = document.getElementById('sku');

  function update() {
    const ids = [...document.querySelectorAll('.option-group input[type="radio"]:checked')]
      .map(i => parseInt(i.value, 10)).sort((a, b) => a - b);
    const c = combos[ids.join('-')];
    if (hidden) hidden.value = c ? c.id : '';
    if (c && price) price.textContent = c.price;
    if (sku) sku.textContent = c ? c.sku : '–';
    const ok = !!(c && c.available);
    if (btn) btn.disabled = !ok;
    if (!info) return;
    if (!c) { info.textContent = 'Diese Kombination gibt es leider nicht.'; info.className = info.dataset.na; }
    else if (!c.available) { info.textContent = 'Diese Auswahl ist leider ausverkauft.'; info.className = info.dataset.out; }
    else { info.textContent = info.dataset.okText || 'Auf Lager'; info.className = info.dataset.ok; }
  }
  document.querySelectorAll('.option-group input[type="radio"]').forEach(r => r.addEventListener('change', update));
  update();

  // Vorausgewählte Farbe → passendes Bild
  const pre = document.querySelector('.option-group[data-color] input[type="radio"]:checked');
  if (pre) pre.dispatchEvent(new Event('change'));
});
