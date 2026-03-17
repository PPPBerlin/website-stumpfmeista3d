// ============================================================
// Stumpfmeista3D — main.js
// Vanilla JS: Mobile Menu, Datei-Upload UI, Kontaktformular AJAX
// ============================================================

document.addEventListener('DOMContentLoaded', () => {

  // ----------------------------------------------------------
  // Mobile Menü Toggle
  // ----------------------------------------------------------
  const menuToggle = document.getElementById('menu-toggle');
  const mobileMenu = document.getElementById('mobile-menu');

  if (menuToggle && mobileMenu) {
    menuToggle.addEventListener('click', () => {
      mobileMenu.classList.toggle('hidden');
    });
    // Menü schließen bei Link-Klick
    mobileMenu.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => mobileMenu.classList.add('hidden'));
    });
  }

  // ----------------------------------------------------------
  // Smooth Scroll für Anker-Links (Fallback für ältere Browser)
  // ----------------------------------------------------------
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', (e) => {
      const target = document.querySelector(anchor.getAttribute('href'));
      if (!target) return;
      e.preventDefault();
      const navH = document.querySelector('nav')?.offsetHeight || 70;
      window.scrollTo({
        top: target.offsetTop - navH,
        behavior: 'smooth',
      });
    });
  });

  // ----------------------------------------------------------
  // Datei-Upload UI (Drag & Drop + Click)
  // ----------------------------------------------------------
  const dropZone  = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');
  const fileList  = document.getElementById('file-list');

  if (!dropZone || !fileInput) return;

  const ALLOWED = ['stl', '3mf', 'pdf', 'jpg', 'jpeg', 'png'];
  let selectedFiles = []; // DataTransfer-Workaround für multi-source Files

  // Klick öffnet Dateiauswahl
  dropZone.addEventListener('click', () => fileInput.click());

  // Tastatur-Zugänglichkeit
  dropZone.setAttribute('tabindex', '0');
  dropZone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') fileInput.click();
  });

  // Drag-Events
  ['dragenter', 'dragover'].forEach(ev => {
    dropZone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropZone.classList.add('border-[#39FF14]', 'bg-[#39FF14]/5');
    });
  });
  ['dragleave', 'drop'].forEach(ev => {
    dropZone.addEventListener(ev, () => {
      dropZone.classList.remove('border-[#39FF14]', 'bg-[#39FF14]/5');
    });
  });
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    addFiles(Array.from(e.dataTransfer.files));
  });
  fileInput.addEventListener('change', () => {
    addFiles(Array.from(fileInput.files));
    fileInput.value = ''; // Reset damit gleiche Datei nochmal wählbar
  });

  function addFiles(newFiles) {
    newFiles.forEach(file => {
      const ext = file.name.split('.').pop().toLowerCase();
      if (!ALLOWED.includes(ext)) {
        showFileFeedback(`❌ Dateityp nicht erlaubt: ${file.name}`, 'error');
        return;
      }
      // Duplikate vermeiden
      if (!selectedFiles.find(f => f.name === file.name && f.size === file.size)) {
        selectedFiles.push(file);
      }
    });
    renderFileList();
  }

  function removeFile(index) {
    selectedFiles.splice(index, 1);
    renderFileList();
  }

  function renderFileList() {
    fileList.innerHTML = '';
    selectedFiles.forEach((file, i) => {
      const ext = file.name.split('.').pop().toUpperCase();
      const size = (file.size / 1024).toFixed(1);
      const li = document.createElement('li');
      li.className = 'flex items-center justify-between px-3 py-2 rounded-lg ' +
                     'bg-[#130820] border border-[#8B2FC9]/20 text-xs font-mono';
      li.innerHTML = `
        <div class="flex items-center gap-2 min-w-0">
          <span class="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold
                       bg-[#8B2FC9]/20 text-[#8B2FC9]">${ext}</span>
          <span class="text-gray-400 truncate">${file.name}</span>
          <span class="text-gray-600 flex-shrink-0">${size} KB</span>
        </div>
        <button type="button" onclick="removeFileByIndex(${i})"
                class="flex-shrink-0 ml-2 text-gray-600 hover:text-red-400 transition-colors"
                aria-label="Datei entfernen">✕</button>
      `;
      fileList.appendChild(li);
    });
  }

  // Global für inline onclick
  window.removeFileByIndex = removeFile;

  function showFileFeedback(msg, type) {
    const el = document.createElement('p');
    el.className = `text-xs font-mono mt-1 ${type === 'error' ? 'text-red-400' : 'text-[#39FF14]'}`;
    el.textContent = msg;
    fileList.appendChild(el);
    setTimeout(() => el.remove(), 3000);
  }

  // ----------------------------------------------------------
  // Kontaktformular — AJAX Absenden
  // ----------------------------------------------------------
  const form       = document.getElementById('contact-form');
  const submitBtn  = document.getElementById('submit-btn');
  const submitText = document.getElementById('submit-text');
  const submitSpinner = document.getElementById('submit-spinner');
  const feedback   = document.getElementById('form-feedback');

  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    // Pflichtfelder clientseitig prüfen
    const required = form.querySelectorAll('[required]');
    let valid = true;
    required.forEach(el => {
      if (!el.value.trim()) {
        el.classList.add('border-red-500');
        valid = false;
      } else {
        el.classList.remove('border-red-500');
      }
    });
    if (!valid) {
      showFeedback('Bitte alle Pflichtfelder ausfüllen.', 'error');
      return;
    }

    // FormData aufbauen
    const data = new FormData(form);
    // Eigene selectedFiles hinzufügen (statt dem leeren file-input)
    data.delete('files');
    selectedFiles.forEach(file => data.append('files', file));

    // UI: Loading-State
    submitBtn.disabled = true;
    submitText.classList.add('hidden');
    submitSpinner.classList.remove('hidden');
    hideFeedback();

    try {
      const res = await fetch('/kontakt/senden', {
        method: 'POST',
        body: data,
        headers: { 'X-CSRFToken': form.querySelector('[name=csrf_token]').value },
      });
      const json = await res.json();

      if (json.success) {
        showFeedback('✓ Anfrage gesendet! Ich melde mich innerhalb von 24h.', 'success');
        form.reset();
        selectedFiles = [];
        renderFileList();
      } else {
        showFeedback(json.error || 'Fehler beim Senden. Bitte erneut versuchen.', 'error');
      }
    } catch (err) {
      showFeedback('Verbindungsfehler. Bitte erneut versuchen.', 'error');
    } finally {
      submitBtn.disabled = false;
      submitText.classList.remove('hidden');
      submitSpinner.classList.add('hidden');
    }
  });

  function showFeedback(msg, type) {
    feedback.textContent = msg;
    feedback.className = `text-center py-3 rounded-lg text-sm font-mono border ${
      type === 'success'
        ? 'bg-green-900/40 border-[#39FF14]/50 text-[#39FF14]'
        : 'bg-red-900/40 border-red-500/50 text-red-400'
    }`;
    feedback.classList.remove('hidden');
    feedback.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function hideFeedback() {
    feedback.classList.add('hidden');
  }

});
