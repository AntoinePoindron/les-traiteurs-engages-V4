document.addEventListener('DOMContentLoaded', function () {
  var totalSteps = 7;
  var currentStep = 1;
  var form = document.getElementById('wizard-form');

  var stepLabels = [
    'Type de service',
    'Evenement',
    'Budget',
    'Regimes alimentaires',
    'Boissons',
    'Services',
    'Recapitulatif',
  ];

  function showStep(step) {
    for (var i = 1; i <= totalSteps; i++) {
      var section = document.getElementById('step-' + i);
      if (section) {
        section.style.display = i === step ? 'block' : 'none';
        section.style.opacity = i === step ? '1' : '0';
      }
    }
    currentStep = step;
    updateProgressBar();
    updateButtons();
    if (step === totalSteps) populateSummary();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function updateProgressBar() {
    for (var i = 1; i <= totalSteps; i++) {
      var dot = document.getElementById('progress-dot-' + i);
      var label = document.getElementById('progress-label-' + i);
      var connector = document.getElementById('progress-connector-' + i);
      if (dot) {
        dot.classList.toggle('step-dot--done', i < currentStep);
        dot.classList.toggle('step-dot--current', i === currentStep);
      }
      if (label) {
        label.classList.toggle('step-label--current', i === currentStep);
      }
      if (connector) {
        connector.classList.toggle('step-connector--done', i < currentStep);
      }
    }
  }

  function updateButtons() {
    var prevBtn = document.getElementById('btn-prev');
    var nextBtn = document.getElementById('btn-next');
    var submitBtn = document.getElementById('btn-submit');
    if (prevBtn) prevBtn.style.display = currentStep > 1 ? 'inline-flex' : 'none';
    if (nextBtn) nextBtn.style.display = currentStep < totalSteps ? 'inline-flex' : 'none';
    if (submitBtn) submitBtn.style.display = currentStep === totalSteps ? 'inline-flex' : 'none';
  }

  function validateStep(step) {
    var section = document.getElementById('step-' + step);
    if (!section) return true;
    var required = section.querySelectorAll('[required]');
    var valid = true;
    required.forEach(function (field) {
      field.classList.remove('border-coral-red-400');
      if (field.type === 'radio') {
        var name = field.name;
        var checked = section.querySelector('input[name="' + name + '"]:checked');
        if (!checked) {
          var radios = section.querySelectorAll('input[name="' + name + '"]');
          radios.forEach(function (r) {
            r.closest('label').classList.add('ring-2', 'ring-coral-red-400');
          });
          valid = false;
        } else {
          var radios = section.querySelectorAll('input[name="' + name + '"]');
          radios.forEach(function (r) {
            r.closest('label').classList.remove('ring-2', 'ring-coral-red-400');
          });
        }
      } else if (!field.value.trim()) {
        field.classList.add('border-coral-red-400');
        valid = false;
      }
    });
    return valid;
  }

  var prevBtn = document.getElementById('btn-prev');
  var nextBtn = document.getElementById('btn-next');

  if (nextBtn) {
    nextBtn.addEventListener('click', function () {
      if (validateStep(currentStep)) {
        showStep(currentStep + 1);
      }
    });
  }

  if (prevBtn) {
    prevBtn.addEventListener('click', function () {
      if (currentStep > 1) showStep(currentStep - 1);
    });
  }

  // Budget sync: bidirectional between budget_global and budget_per_person
  var budgetGlobal = document.getElementById('budget_global');
  var budgetPerPerson = document.getElementById('budget_per_person');
  var guestCount = document.getElementById('guest_count');

  function syncBudgetFromGlobal() {
    var guests = parseInt(guestCount ? guestCount.value : 0);
    var total = parseFloat(budgetGlobal.value);
    if (guests > 0 && total > 0 && budgetPerPerson) {
      budgetPerPerson.value = (total / guests).toFixed(2);
    }
  }

  function syncBudgetFromPerPerson() {
    var guests = parseInt(guestCount ? guestCount.value : 0);
    var pp = parseFloat(budgetPerPerson.value);
    if (guests > 0 && pp > 0 && budgetGlobal) {
      budgetGlobal.value = (pp * guests).toFixed(2);
    }
  }

  if (budgetGlobal) budgetGlobal.addEventListener('input', syncBudgetFromGlobal);
  if (budgetPerPerson) budgetPerPerson.addEventListener('input', syncBudgetFromPerPerson);
  if (guestCount) {
    guestCount.addEventListener('input', function () {
      if (budgetGlobal && budgetGlobal.value) syncBudgetFromGlobal();
    });
  }

  // Dietary checkboxes: show/hide count input
  document.querySelectorAll('.dietary-toggle').forEach(function (cb) {
    cb.addEventListener('change', function () {
      var countInput = document.getElementById(cb.dataset.countTarget);
      if (countInput) {
        countInput.closest('.dietary-count-wrapper').style.display = cb.checked ? 'flex' : 'none';
        if (!cb.checked) countInput.value = '';
      }
    });
  });

  // Service en salle: show/hide details
  var waitstaffCb = document.getElementById('wants_waitstaff');
  var waitstaffDetails = document.getElementById('waitstaff-details-wrapper');
  if (waitstaffCb && waitstaffDetails) {
    waitstaffCb.addEventListener('change', function () {
      waitstaffDetails.style.display = waitstaffCb.checked ? 'block' : 'none';
    });
  }

  // Compare mode toggle
  var compareModeYes = document.getElementById('is_compare_mode_yes');
  var compareModeNo = document.getElementById('is_compare_mode_no');
  var catererSelect = document.getElementById('caterer-select-wrapper');
  if (compareModeYes && compareModeNo && catererSelect) {
    compareModeYes.addEventListener('change', function () {
      catererSelect.style.display = 'none';
    });
    compareModeNo.addEventListener('change', function () {
      catererSelect.style.display = 'block';
    });
  }

  // Populate summary (step 7)
  function populateSummary() {
    var mealTypeLabels = {
      petit_dejeuner: 'Petit-dejeuner',
      dejeuner: 'Dejeuner',
      diner: 'Diner',
      cocktail: 'Cocktail',
      autre: 'Autre',
    };

    var flexLabels = {
      exact: 'Exact',
      '5': '+/- 5%',
      '10': '+/- 10%',
    };

    function val(id) {
      var el = document.getElementById(id);
      return el ? el.value : '';
    }

    function radioVal(name) {
      var checked = form.querySelector('input[name="' + name + '"]:checked');
      return checked ? checked.value : '';
    }

    // Renamed mentally from setHtml: callers only pass plain text (form values,
    // joined labels). Using textContent closes audit VULN-45 (DOM-based XSS via
    // pre-filled fields decoded by the browser before injection).
    function setHtml(id, text) {
      var el = document.getElementById(id);
      if (el) el.textContent = text;
    }

    var mealType = radioVal('meal_type');
    setHtml('summary-meal-type', mealTypeLabels[mealType] || mealType);
    setHtml('summary-service-type', val('service_type') || '-');
    setHtml('summary-event-date', val('event_date') || '-');
    setHtml('summary-guest-count', val('guest_count') ? val('guest_count') + ' convives' : '-');
    setHtml('summary-event-address', [val('event_address'), val('event_zip_code'), val('event_city')].filter(Boolean).join(', ') || '-');

    var bg = val('budget_global');
    var bpp = val('budget_per_person');
    var flex = radioVal('budget_flexibility');
    var budgetText = '';
    if (bg) budgetText += bg + ' EUR total';
    if (bpp) budgetText += (budgetText ? ' (' : '') + bpp + ' EUR/pers.' + (budgetText ? ')' : '');
    if (flex) budgetText += ' - ' + (flexLabels[flex] || flex);
    setHtml('summary-budget', budgetText || '-');

    var diets = [];
    var dietaryItems = [
      { id: 'dietary_vegetarian', count: 'vegetarian_count', label: 'Vegetarien' },
      { id: 'dietary_vegan', count: 'vegan_count', label: 'Vegan' },
      { id: 'dietary_halal', count: 'halal_count', label: 'Halal' },
      { id: 'dietary_casher', count: 'casher_count', label: 'Casher' },
      { id: 'dietary_gluten_free', count: 'gluten_free_count', label: 'Sans gluten' },
      { id: 'dietary_lactose_free', count: 'lactose_free_count', label: 'Sans lactose' },
    ];
    dietaryItems.forEach(function (item) {
      var cb = document.getElementById(item.id);
      if (cb && cb.checked) {
        var count = val(item.count);
        diets.push(item.label + (count ? ' (' + count + ')' : ''));
      }
    });
    setHtml('summary-dietary', diets.length > 0 ? diets.join(', ') : 'Aucun');

    var drinkItems = [];
    document.querySelectorAll('.drink-checkbox:checked').forEach(function (cb) {
      drinkItems.push(cb.dataset.label);
    });
    var alcoholVal = radioVal('drinks_alcohol');
    if (alcoholVal === '1') drinkItems.push('Avec alcool');
    var drinksText = val('drinks_details');
    setHtml('summary-drinks', (drinkItems.length > 0 ? drinkItems.join(', ') : 'Aucune selection') + (drinksText ? ' - ' + drinksText : ''));

    var services = [];
    document.querySelectorAll('.service-checkbox:checked').forEach(function (cb) {
      services.push(cb.dataset.label);
    });
    setHtml('summary-services', services.length > 0 ? services.join(', ') : 'Aucun');
  }

  showStep(1);
});
