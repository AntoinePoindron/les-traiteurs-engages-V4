(function () {
  'use strict';

  var TVA_RATES = [
    { value: '5.5', label: '5,5%' },
    { value: '10', label: '10%' },
    { value: '20', label: '20%' },
  ];
  var PLATFORM_FEE_RATE = 0.05;     // 5% commission added to the quote
  var PLATFORM_FEE_TVA_RATE = 0.20; // 20% VAT on the platform fee itself

  var GUEST_COUNT = 0;
  var INITIAL_LINES = [];
  var lineCounter = 0;

  // ---- Formatting helpers ------------------------------------------------

  // French money formatter: "1 234,56 €". Falls back to a manual fixed-2
  // implementation if Intl is unavailable (very old browsers).
  var moneyFormatter = (typeof Intl !== 'undefined' && Intl.NumberFormat)
    ? new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : null;

  function fmt(n) {
    if (!isFinite(n)) n = 0;
    if (moneyFormatter) return moneyFormatter.format(n) + ' €';
    return n.toFixed(2).replace('.', ',').replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' €';
  }

  function escapeHtml(str) {
    if (str == null) return '';
    return String(str).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // ---- Line management ---------------------------------------------------

  function createLineHTML(section, data) {
    lineCounter++;
    var id = 'line-' + lineCounter;
    var desc = data ? data.description || '' : '';
    var qty = data ? data.quantity || 1 : 1;
    var price = data ? data.unit_price_ht || 0 : 0;
    var tva = data ? String(data.tva_rate || '10') : '10';

    var tvaOptions = TVA_RATES.map(function (r) {
      var sel = r.value === tva ? ' selected' : '';
      return '<option value="' + r.value + '"' + sel + '>' + r.label + '</option>';
    }).join('');

    return '<div class="flex flex-wrap items-start gap-2 p-3 rounded-lg border border-soft" id="' + id + '" data-section="' + section + '">' +
      '<div class="flex-1 min-w-[200px]">' +
        '<label class="block text-xs text-mute mb-1">Description</label>' +
        '<input type="text" value="' + escapeHtml(desc).replace(/"/g, '&quot;') + '" class="line-desc w-full px-2 py-1.5 rounded text-sm input-soft">' +
      '</div>' +
      '<div class="w-20">' +
        '<label class="block text-xs text-mute mb-1">Qté</label>' +
        '<input type="number" value="' + qty + '" min="0" step="1" class="line-qty w-full px-2 py-1.5 rounded text-sm text-right input-soft">' +
      '</div>' +
      '<div class="w-28">' +
        '<label class="block text-xs text-mute mb-1">PU HT (€)</label>' +
        '<input type="number" value="' + price + '" min="0" step="0.01" class="line-price w-full px-2 py-1.5 rounded text-sm text-right input-soft">' +
      '</div>' +
      '<div class="w-24">' +
        '<label class="block text-xs text-mute mb-1">TVA</label>' +
        '<select class="line-tva w-full px-2 py-1.5 rounded text-sm input-soft">' + tvaOptions + '</select>' +
      '</div>' +
      '<div class="w-28 text-right">' +
        '<label class="block text-xs text-mute mb-1">Total HT</label>' +
        '<p class="line-total text-sm font-bold text-text py-1.5">0,00 €</p>' +
      '</div>' +
      '<div class="pt-6">' +
        '<button type="button" data-action="remove-line" data-target="' + id + '" ' +
        'class="text-mute hover:text-danger transition-colors">' +
          '<i data-lucide="trash-2" class="w-4 h-4"></i>' +
        '</button>' +
      '</div>' +
    '</div>';
  }

  function addLine(section, data) {
    var container = document.querySelector('.lines-container[data-section="' + section + '"]');
    if (!container) return;
    container.insertAdjacentHTML('beforeend', createLineHTML(section, data));
    if (window.lucide) lucide.createIcons();
    recalculate();
  }

  function removeLine(id) {
    var el = document.getElementById(id);
    if (el) el.remove();
    recalculate();
  }

  function collectLines() {
    var lines = [];
    document.querySelectorAll('.lines-container > div').forEach(function (row) {
      var desc = row.querySelector('.line-desc').value;
      var qty = parseFloat(row.querySelector('.line-qty').value) || 0;
      var price = parseFloat(row.querySelector('.line-price').value) || 0;
      var tva = row.querySelector('.line-tva').value;
      var section = row.getAttribute('data-section');
      lines.push({
        description: desc,
        quantity: qty,
        unit_price_ht: price,
        tva_rate: parseFloat(tva),
        section: section,
      });
    });
    return lines;
  }

  // ---- Totals computation (pure, also used by the preview renderer) ------

  function computeTotals(lines) {
    var totalHT = 0;
    var totalTVA = 0;
    var sectionTotals = {};
    var tvaTotals = {};

    lines.forEach(function (line) {
      var lineHT = line.quantity * line.unit_price_ht;
      var lineTVA = lineHT * line.tva_rate / 100;
      totalHT += lineHT;
      totalTVA += lineTVA;

      sectionTotals[line.section] = (sectionTotals[line.section] || 0) + lineHT;

      var tvaKey = String(line.tva_rate);
      if (!tvaTotals[tvaKey]) tvaTotals[tvaKey] = { base: 0, tva: 0 };
      tvaTotals[tvaKey].base += lineHT;
      tvaTotals[tvaKey].tva += lineTVA;
    });

    var totalTTC = totalHT + totalTVA;
    var feeHT = totalHT * PLATFORM_FEE_RATE;
    var feeTVA = feeHT * PLATFORM_FEE_TVA_RATE;
    var feeTTC = feeHT + feeTVA;
    var grandTotal = totalTTC + feeTTC;

    return {
      totalHT: totalHT,
      totalTVA: totalTVA,
      totalTTC: totalTTC,
      sectionTotals: sectionTotals,
      tvaTotals: tvaTotals,
      feeHT: feeHT,
      feeTVA: feeTVA,
      feeTTC: feeTTC,
      grandTotal: grandTotal,
    };
  }

  function recalculate() {
    var lines = collectLines();
    var totals = computeTotals(lines);

    // Per-line totals
    document.querySelectorAll('.lines-container > div').forEach(function (row) {
      var qty = parseFloat(row.querySelector('.line-qty').value) || 0;
      var price = parseFloat(row.querySelector('.line-price').value) || 0;
      row.querySelector('.line-total').textContent = fmt(qty * price);
    });

    // Section subtotals (kept hidden by default but updated for completeness)
    document.querySelectorAll('.section-subtotal').forEach(function (el) {
      var s = el.getAttribute('data-section');
      var v = totals.sectionTotals[s] || 0;
      el.textContent = fmt(v) + ' HT';
      el.hidden = v === 0;
    });

    // Sidebar totals
    setText('display-total-ht', fmt(totals.totalHT));
    setText('display-total-ttc', fmt(totals.totalTTC));
    setText('display-fee-ht', fmt(totals.feeHT));
    setText('display-fee-tva', fmt(totals.feeTVA));
    setText('display-fee-ttc', fmt(totals.feeTTC));
    setText('display-grand-total', fmt(totals.grandTotal));

    // Enable "Save & send" only when there's something worth sending.
    var sendBtn = document.getElementById('btn-send');
    if (sendBtn) sendBtn.disabled = lines.length === 0 || totals.totalHT <= 0;

    // Sync the hidden field for the form submission.
    var detailsField = document.getElementById('details-field');
    if (detailsField) detailsField.value = JSON.stringify(lines);
  }

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  // ---- Form submission ---------------------------------------------------

  function submitWithAction(action) {
    var actionField = document.getElementById('action-field');
    if (actionField) actionField.value = action;
    document.getElementById('quote-form').submit();
  }

  // ---- Preview overlay ---------------------------------------------------

  var SECTION_LABELS = {
    principal: 'PRESTATIONS PRINCIPALES',
    boissons:  'BOISSONS',
    extras:    'PRESTATIONS COMPLÉMENTAIRES',
  };

  function renderPreview() {
    var cfg = document.getElementById('quote-editor-config');
    var lines = collectLines();
    var totals = computeTotals(lines);

    var html = '';

    // Title
    html += '<div class="text-right mb-6">';
    html += '<h3 class="font-display font-bold text-lg text-text">DEVIS N° ' + escapeHtml(cfg.dataset.quoteReference) + '</h3>';
    html += '</div>';

    // Plateforme + Prestataire
    html += '<div class="grid grid-cols-2 gap-6 mb-6 text-xs">';
    html += '<div>';
    html += '<p class="uppercase font-bold text-mute mb-2">Plateforme</p>';
    html += '<p class="font-bold text-text">Les Traiteurs Engagés</p>';
    html += '<p class="text-text">GIP Plateforme de l\'inclusion</p>';
    html += '<p class="text-text">6, boulevard Saint-Denis 75010 Paris</p>';
    html += '<p class="text-mute mt-1">SIRET : 13003013300016</p>';
    html += '</div>';
    html += '<div>';
    html += '<p class="uppercase font-bold text-mute mb-2">Prestataire</p>';
    html += '<p class="font-bold text-text">' + escapeHtml(cfg.dataset.catererName) + '</p>';
    html += '<p class="text-text">' + escapeHtml(cfg.dataset.catererAddress) + '</p>';
    if (cfg.dataset.catererSiret) {
      html += '<p class="text-mute mt-1">SIRET : ' + escapeHtml(cfg.dataset.catererSiret) + '</p>';
    }
    html += '</div>';
    html += '</div>';

    // Client
    html += '<div class="mb-6 text-xs">';
    html += '<p class="uppercase font-bold text-mute mb-2">Client</p>';
    html += '<p class="font-bold text-text">' + escapeHtml(cfg.dataset.clientName) + '</p>';
    if (cfg.dataset.clientContact && cfg.dataset.clientContact.trim()) {
      html += '<p class="text-text">' + escapeHtml(cfg.dataset.clientContact) + '</p>';
    }
    if (cfg.dataset.clientCity) {
      html += '<p class="text-text">' + escapeHtml(cfg.dataset.clientCity) + '</p>';
    }
    if (cfg.dataset.clientSiret) {
      html += '<p class="text-mute mt-1">SIRET : ' + escapeHtml(cfg.dataset.clientSiret) + '</p>';
    }
    html += '</div>';

    // Évènement
    html += '<div class="mb-6 p-4 rounded-lg" style="background-color:var(--c-cream);">';
    html += '<p class="uppercase font-bold text-mute mb-2 text-xs">Événement</p>';
    html += '<div class="grid grid-cols-2 gap-2 text-sm">';
    html += '<p class="text-text"><span class="font-bold">Type :</span> ' + escapeHtml(cfg.dataset.mealLabel) + '</p>';
    html += '<p class="text-text"><span class="font-bold">Date :</span> ' + escapeHtml(cfg.dataset.eventDate || '-') + '</p>';
    html += '<p class="text-text"><span class="font-bold">Lieu :</span> ' + escapeHtml(cfg.dataset.eventLocation || '-') + '</p>';
    html += '<p class="text-text"><span class="font-bold">Convives :</span> ' + escapeHtml(cfg.dataset.guestCountLabel) + ' personnes</p>';
    html += '</div>';
    html += '</div>';

    // Lines table
    html += '<table class="w-full text-sm mb-6"><thead><tr style="background-color:var(--c-navy);color:#fff;">';
    html += '<th class="text-left px-3 py-2 font-bold uppercase text-xs">Désignation</th>';
    html += '<th class="text-right px-3 py-2 font-bold uppercase text-xs">Qté</th>';
    html += '<th class="text-right px-3 py-2 font-bold uppercase text-xs">PU HT</th>';
    html += '<th class="text-right px-3 py-2 font-bold uppercase text-xs">TVA</th>';
    html += '<th class="text-right px-3 py-2 font-bold uppercase text-xs">Total HT</th>';
    html += '</tr></thead><tbody>';

    var bySection = {};
    lines.forEach(function (l) {
      bySection[l.section] = bySection[l.section] || [];
      bySection[l.section].push(l);
    });

    ['principal', 'boissons', 'extras'].forEach(function (sect) {
      if (!bySection[sect] || bySection[sect].length === 0) return;
      html += '<tr><td colspan="5" class="font-bold uppercase text-mute text-xs px-3 py-2" style="background-color:var(--c-cream);">' + SECTION_LABELS[sect] + '</td></tr>';
      bySection[sect].forEach(function (l) {
        var lineTotal = l.quantity * l.unit_price_ht;
        html += '<tr class="border-t border-soft">';
        html += '<td class="px-3 py-2 font-bold text-text">' + escapeHtml(l.description) + '</td>';
        html += '<td class="px-3 py-2 text-right text-text">' + l.quantity + '</td>';
        html += '<td class="px-3 py-2 text-right text-text">' + fmt(l.unit_price_ht) + '</td>';
        html += '<td class="px-3 py-2 text-right text-text">' + l.tva_rate + ' %</td>';
        html += '<td class="px-3 py-2 text-right font-bold text-text">' + fmt(lineTotal) + '</td>';
        html += '</tr>';
      });
    });

    html += '</tbody></table>';

    // Subtotal block (right-aligned)
    html += '<div class="mb-6 ml-auto" style="max-width:400px;">';
    html += '<dl class="space-y-1 text-sm">';
    html += '<div class="flex justify-between"><dt class="text-mute">Montant HT</dt><dd class="font-bold text-text">' + fmt(totals.totalHT) + '</dd></div>';
    Object.keys(totals.tvaTotals).sort().forEach(function (rate) {
      html += '<div class="flex justify-between"><dt class="text-mute">TVA ' + rate + ' %</dt><dd class="font-bold text-text">' + fmt(totals.tvaTotals[rate].tva) + '</dd></div>';
    });
    html += '<div class="flex justify-between border-t border-soft pt-1"><dt class="font-bold text-text">Sous-total TTC</dt><dd class="font-bold text-text">' + fmt(totals.totalTTC) + '</dd></div>';
    html += '</dl>';
    html += '</div>';

    // Platform fee
    html += '<div class="mb-6">';
    html += '<p class="uppercase font-bold text-mute mb-2 text-xs">Frais de mise en relation (5% ajoutés)</p>';
    html += '<dl class="space-y-1 text-sm ml-auto" style="max-width:400px;">';
    html += '<div class="flex justify-between"><dt class="text-mute">Montant HT</dt><dd class="font-bold text-text">' + fmt(totals.feeHT) + '</dd></div>';
    html += '<div class="flex justify-between"><dt class="text-mute">TVA 20 %</dt><dd class="font-bold text-text">' + fmt(totals.feeTVA) + '</dd></div>';
    html += '<div class="flex justify-between border-t border-soft pt-1"><dt class="font-bold text-text">Sous-total TTC</dt><dd class="font-bold text-text">' + fmt(totals.feeTTC) + '</dd></div>';
    html += '</dl>';
    html += '</div>';

    // Grand total banner
    html += '<div class="p-4 rounded-lg flex items-center justify-between" style="background-color:var(--c-cream);">';
    html += '<div>';
    html += '<p class="font-display font-bold text-lg text-text">Total à payer</p>';
    var guestN = parseInt(GUEST_COUNT, 10) || 0;
    if (guestN > 0) {
      html += '<p class="text-xs text-mute mt-1">soit ' + fmt(totals.grandTotal / guestN) + ' / personne</p>';
    }
    html += '</div>';
    html += '<p class="font-display font-bold text-2xl text-text">' + fmt(totals.grandTotal) + '</p>';
    html += '</div>';

    // Legal footer
    html += '<div class="mt-6 text-xs text-mute space-y-1">';
    html += '<p>Devis émis par la plateforme Les Traiteurs Engagés, agissant en qualité de mandataire du Traiteur ' + escapeHtml(cfg.dataset.catererName) + '.</p>';
    html += '<p>La prestation de restauration sera réalisée par le Traiteur ' + escapeHtml(cfg.dataset.catererName) + ', seul responsable de son exécution.</p>';
    html += '<p>Ce devis est soumis aux conditions générales de vente du traiteur.</p>';
    html += '<p>Les frais de service plateforme correspondent aux services de mise en relation, coordination et gestion administrative.</p>';
    html += '</div>';

    document.getElementById('preview-content').innerHTML = html;
  }

  function openPreviewOverlay() {
    if (collectLines().length === 0) return;
    renderPreview();
    var overlay = document.getElementById('quote-preview-overlay');
    overlay.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    if (window.lucide) lucide.createIcons();
  }

  function closePreviewOverlay() {
    var overlay = document.getElementById('quote-preview-overlay');
    overlay.classList.add('hidden');
    document.body.style.overflow = '';
  }

  // ---- Event wiring ------------------------------------------------------

  document.addEventListener('click', function (ev) {
    var addBtn = ev.target.closest('[data-action="add-line"]');
    if (addBtn) { addLine(addBtn.dataset.section); return; }

    var rmBtn = ev.target.closest('[data-action="remove-line"]');
    if (rmBtn) { removeLine(rmBtn.dataset.target); return; }

    var closeBtn = ev.target.closest('[data-action="close-preview"]');
    if (closeBtn) { closePreviewOverlay(); return; }

    var pdfBtn = ev.target.closest('[data-action="download-pdf"]');
    if (pdfBtn) {
      // Browser-native print is the simplest path; the user can pick
      // "Save as PDF" in the print dialog. A real PDF export route can
      // come later if we want a deterministic backend-rendered PDF.
      window.print();
      return;
    }

    var confirmBtn = ev.target.closest('[data-action="confirm-send"]');
    if (confirmBtn) { submitWithAction('send'); return; }
  });

  document.addEventListener('input', function (ev) {
    if (ev.target.closest('.lines-container')) recalculate();
  });
  document.addEventListener('change', function (ev) {
    if (ev.target.closest('.lines-container')) recalculate();
  });

  // Close overlay on Escape for keyboard accessibility.
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') {
      var overlay = document.getElementById('quote-preview-overlay');
      if (overlay && !overlay.classList.contains('hidden')) closePreviewOverlay();
    }
  });

  document.addEventListener('DOMContentLoaded', function () {
    var cfg = document.getElementById('quote-editor-config');
    if (cfg) {
      GUEST_COUNT = parseInt(cfg.dataset.guestCount || '0', 10) || 0;
      try { INITIAL_LINES = JSON.parse(cfg.dataset.initialLines || '[]'); }
      catch (e) { INITIAL_LINES = []; }
    }

    if (INITIAL_LINES && INITIAL_LINES.length > 0) {
      INITIAL_LINES.forEach(function (line) {
        addLine(line.section || 'principal', line);
      });
    }
    recalculate();

    // Sidebar buttons
    var btnDraft = document.getElementById('btn-draft');
    if (btnDraft) btnDraft.addEventListener('click', function () { submitWithAction('draft'); });

    var btnSend = document.getElementById('btn-send');
    if (btnSend) btnSend.addEventListener('click', function () {
      if (btnSend.disabled) return;
      openPreviewOverlay();
    });

    if (window.lucide) lucide.createIcons();
  });
})();
