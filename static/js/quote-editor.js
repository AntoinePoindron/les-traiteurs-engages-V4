var TVA_RATES = [
  { value: '5.5', label: '5,5%' },
  { value: '10', label: '10%' },
  { value: '20', label: '20%' },
];

var lineCounter = 0;

function createLineHTML(section, data) {
  lineCounter++;
  var id = 'line-' + lineCounter;
  var desc = data ? data.description || '' : '';
  var qty = data ? data.quantity || 1 : 1;
  var price = data ? data.unit_price_ht || 0 : 0;
  var tva = data ? String(data.tva_rate || '10') : '10';

  var tvaOptions = TVA_RATES.map(function(r) {
    var sel = r.value === tva ? ' selected' : '';
    return '<option value="' + r.value + '"' + sel + '>' + r.label + '</option>';
  }).join('');

  return '<div class="flex flex-wrap items-start gap-2 p-3 rounded-lg border border-cream-200 bg-cream-50" id="' + id + '" data-section="' + section + '">' +
    '<div class="flex-1 min-w-[200px]">' +
      '<label class="block text-xs text-navy-300 mb-1">Description</label>' +
      '<input type="text" value="' + desc.replace(/"/g, '&quot;') + '" oninput="recalculate()" class="line-desc w-full border border-cream-200 rounded px-2 py-1.5 text-sm text-navy focus:ring-1 focus:ring-terracotta focus:border-terracotta">' +
    '</div>' +
    '<div class="w-20">' +
      '<label class="block text-xs text-navy-300 mb-1">Qte</label>' +
      '<input type="number" value="' + qty + '" min="0" step="1" oninput="recalculate()" class="line-qty w-full border border-cream-200 rounded px-2 py-1.5 text-sm text-navy text-right focus:ring-1 focus:ring-terracotta focus:border-terracotta">' +
    '</div>' +
    '<div class="w-28">' +
      '<label class="block text-xs text-navy-300 mb-1">PU HT (&euro;)</label>' +
      '<input type="number" value="' + price + '" min="0" step="0.01" oninput="recalculate()" class="line-price w-full border border-cream-200 rounded px-2 py-1.5 text-sm text-navy text-right focus:ring-1 focus:ring-terracotta focus:border-terracotta">' +
    '</div>' +
    '<div class="w-24">' +
      '<label class="block text-xs text-navy-300 mb-1">TVA</label>' +
      '<select onchange="recalculate()" class="line-tva w-full border border-cream-200 rounded px-2 py-1.5 text-sm text-navy focus:ring-1 focus:ring-terracotta focus:border-terracotta">' + tvaOptions + '</select>' +
    '</div>' +
    '<div class="w-24 text-right">' +
      '<label class="block text-xs text-navy-300 mb-1">Total HT</label>' +
      '<p class="line-total text-sm font-medium text-navy py-1.5">0.00 &euro;</p>' +
    '</div>' +
    '<div class="pt-6">' +
      '<button type="button" onclick="removeLine(\'' + id + '\')" class="text-coral-red-400 hover:text-coral-red-500 transition-colors">' +
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>' +
      '</button>' +
    '</div>' +
  '</div>';
}

function addLine(section, data) {
  var container = document.querySelector('.lines-container[data-section="' + section + '"]');
  container.insertAdjacentHTML('beforeend', createLineHTML(section, data));
  recalculate();
}

function removeLine(id) {
  var el = document.getElementById(id);
  if (el) el.remove();
  recalculate();
}

function collectLines() {
  var lines = [];
  document.querySelectorAll('.lines-container > div').forEach(function(row) {
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

function fmt(n) {
  return n.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

function recalculate() {
  var lines = collectLines();
  var totalHT = 0;
  var totalTVA = 0;
  var sectionTotals = {};
  var tvaTotals = {};

  lines.forEach(function(line) {
    var lineHT = line.quantity * line.unit_price_ht;
    var lineTVA = lineHT * line.tva_rate / 100;
    totalHT += lineHT;
    totalTVA += lineTVA;

    if (!sectionTotals[line.section]) sectionTotals[line.section] = 0;
    sectionTotals[line.section] += lineHT;

    var tvaKey = String(line.tva_rate);
    if (!tvaTotals[tvaKey]) tvaTotals[tvaKey] = { base: 0, tva: 0 };
    tvaTotals[tvaKey].base += lineHT;
    tvaTotals[tvaKey].tva += lineTVA;
  });

  var totalTTC = totalHT + totalTVA;
  var perPerson = GUEST_COUNT > 0 ? totalTTC / GUEST_COUNT : 0;
  var feeHT = totalHT * 0.05;
  var feeTVA = feeHT * 0.20;
  var feeTTC = feeHT + feeTVA;

  // Update line totals
  document.querySelectorAll('.lines-container > div').forEach(function(row) {
    var qty = parseFloat(row.querySelector('.line-qty').value) || 0;
    var price = parseFloat(row.querySelector('.line-price').value) || 0;
    row.querySelector('.line-total').textContent = fmt(qty * price) + ' \u20ac';
  });

  // Section subtotals
  document.querySelectorAll('.section-subtotal').forEach(function(el) {
    var s = el.getAttribute('data-section');
    el.textContent = fmt(sectionTotals[s] || 0) + ' \u20ac HT';
  });

  // Grand totals
  document.getElementById('display-total-ht').innerHTML = fmt(totalHT) + ' &euro;';
  document.getElementById('display-total-ttc').innerHTML = fmt(totalTTC) + ' &euro;';
  document.getElementById('display-per-person').innerHTML = fmt(perPerson) + ' &euro;';
  document.getElementById('display-fee-ht').innerHTML = fmt(feeHT) + ' &euro;';
  document.getElementById('display-fee-tva').innerHTML = fmt(feeTVA) + ' &euro;';
  document.getElementById('display-fee-ttc').innerHTML = fmt(feeTTC) + ' &euro;';
  document.getElementById('display-agefiph').innerHTML = fmt(totalHT) + ' &euro;';

  // TVA breakdown
  var tvaHTML = '';
  Object.keys(tvaTotals).sort().forEach(function(rate) {
    tvaHTML += '<div class="flex justify-between"><dt class="text-navy-300">TVA ' + rate + '%</dt>' +
      '<dd class="text-navy">' + fmt(tvaTotals[rate].tva) + ' &euro;</dd></div>';
  });
  document.getElementById('tva-breakdown').innerHTML = tvaHTML;

  // Store JSON for form submission
  document.getElementById('details-field').value = JSON.stringify(lines);
}

// Init: load existing lines or add one empty line per section
document.addEventListener('DOMContentLoaded', function() {
  if (INITIAL_LINES && INITIAL_LINES.length > 0) {
    INITIAL_LINES.forEach(function(line) {
      addLine(line.section || 'principal', line);
    });
  } else {
    addLine('principal');
    addLine('boissons');
    addLine('extras');
  }
  recalculate();
});
