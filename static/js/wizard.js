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

  // Validation visuelle des champs obligatoires — applique les classes
  // .wizard-field-error / .wizard-radio-error définies dans app.css.
  // Les classes Tailwind de l'ancienne version (border-coral-red-400 /
  // ring-coral-red-400) n'existaient pas dans le bundle curated du projet,
  // donc rien ne s'affichait. Aussi : insère un banner en haut de l'étape
  // et scrolle vers le premier champ invalide.
  function clearStepErrors(section) {
    section.querySelectorAll('.wizard-field-error').forEach(function (el) {
      el.classList.remove('wizard-field-error');
    });
    section.querySelectorAll('.wizard-radio-error').forEach(function (el) {
      el.classList.remove('wizard-radio-error');
    });
    var existingBanner = section.querySelector('.wizard-error-banner');
    if (existingBanner) existingBanner.remove();
  }

  function showErrorBanner(section, count) {
    var banner = document.createElement('div');
    banner.className = 'wizard-error-banner';
    var msg = count > 1
      ? 'Veuillez remplir les ' + count + ' champs obligatoires manquants.'
      : 'Veuillez remplir le champ obligatoire manquant.';
    banner.innerHTML =
      '<i data-lucide="alert-circle" class="w-4 h-4"></i>' +
      '<span></span>';
    banner.querySelector('span').textContent = msg;
    section.insertBefore(banner, section.firstChild);
    if (window.lucide) lucide.createIcons();
  }

  function validateStep(step) {
    var section = document.getElementById('step-' + step);
    if (!section) return true;
    clearStepErrors(section);

    var required = section.querySelectorAll('[required]');
    var invalidCount = 0;
    var firstInvalid = null;
    var seenRadioGroups = {};

    required.forEach(function (field) {
      if (field.type === 'radio') {
        // Un groupe de radios partage `name` — on ne veut compter le
        // groupe qu'une fois et ne styliser que si AUCUNE option n'est
        // cochée.
        var name = field.name;
        if (seenRadioGroups[name]) return;
        seenRadioGroups[name] = true;

        var checked = section.querySelector('input[name="' + name + '"]:checked');
        if (!checked) {
          var radios = section.querySelectorAll('input[name="' + name + '"]');
          radios.forEach(function (r) {
            var lbl = r.closest('label');
            if (lbl) lbl.classList.add('wizard-radio-error');
          });
          invalidCount++;
          if (!firstInvalid) firstInvalid = radios[0];
        }
      } else if (!field.value.trim()) {
        field.classList.add('wizard-field-error');
        invalidCount++;
        if (!firstInvalid) firstInvalid = field;
      }
    });

    // Validation des groupes "au moins un rempli" (data-required-group).
    // Utilisé par le step 3 (Budget) où soit budget_global soit
    // budget_per_person doit être renseigné — pas les deux. Si aucun
    // n'est rempli, on stylise tous les champs du groupe et on incrémente
    // invalidCount d'une seule unité (une erreur logique, pas une par
    // input).
    var groups = {};
    section.querySelectorAll('[data-required-group]').forEach(function (el) {
      var g = el.dataset.requiredGroup;
      if (!groups[g]) groups[g] = [];
      groups[g].push(el);
    });
    Object.keys(groups).forEach(function (g) {
      var anyFilled = groups[g].some(function (el) {
        return String(el.value || '').trim();
      });
      if (!anyFilled) {
        groups[g].forEach(function (el) { el.classList.add('wizard-field-error'); });
        invalidCount++;
        if (!firstInvalid) firstInvalid = groups[g][0];
      }
    });

    if (invalidCount > 0) {
      showErrorBanner(section, invalidCount);
      // Scroll en douceur vers le 1er champ invalide pour que l'utilisateur
      // voie immédiatement quoi corriger, puis focus pour activer
      // l'aide-saisie native du navigateur.
      if (firstInvalid && firstInvalid.scrollIntoView) {
        firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
        try { firstInvalid.focus({ preventScroll: true }); } catch (e) { /* IE/Safari */ }
      }
      return false;
    }
    return true;
  }

  // Auto-clear de l'erreur d'un champ dès que l'utilisateur tape ou
  // sélectionne quelque chose — sinon le rouge reste tant qu'on ne
  // re-clique pas Suivant, c'est anxiogène.
  if (form) {
    form.addEventListener('input', function (ev) {
      var t = ev.target;
      if (!t || !t.classList) return;
      // Cas standard : l'input rempli enlève l'erreur sur lui-même
      if (t.classList.contains('wizard-field-error') && String(t.value || '').trim()) {
        t.classList.remove('wizard-field-error');
      }
      // Cas groupe "au moins un" : un seul input rempli rend le groupe
      // valide → on enlève l'erreur sur TOUS les inputs du groupe.
      if (t.dataset && t.dataset.requiredGroup && String(t.value || '').trim()) {
        var g = t.dataset.requiredGroup;
        form.querySelectorAll('[data-required-group="' + g + '"]').forEach(function (el) {
          el.classList.remove('wizard-field-error');
        });
      }
    });
    form.addEventListener('change', function (ev) {
      var t = ev.target;
      if (!t) return;
      // Radio : si on coche une option, on enlève le ring d'erreur sur
      // tout le groupe.
      if (t.type === 'radio' && t.checked && t.name) {
        var group = form.querySelectorAll('input[name="' + t.name + '"]');
        group.forEach(function (r) {
          var lbl = r.closest('label');
          if (lbl) lbl.classList.remove('wizard-radio-error');
        });
      } else if (t.classList && t.classList.contains('wizard-field-error') && String(t.value || '').trim()) {
        t.classList.remove('wizard-field-error');
      }
    });
  }

  // Step 3 — affichage de la fourchette quand la flexibilité est ±5%
  // ou ±10%. On lit le budget global ET le budget par personne (les
  // deux étant souvent renseignés via le sync), on calcule le min et
  // le max correspondants, et on affiche dans #budget-range-display.
  // En mode "exact", on cache la zone.
  function formatEur(n) {
    // Pas de décimales si entier, 2 sinon. Espace fine entre chiffres
    // et symbole pour rester typographiquement propre.
    var rounded = Math.round(n * 100) / 100;
    if (Math.abs(rounded - Math.round(rounded)) < 0.005) {
      return String(Math.round(rounded));
    }
    return rounded.toFixed(2);
  }

  function updateBudgetRange() {
    var display = document.getElementById('budget-range-display');
    var text = document.getElementById('budget-range-text');
    if (!display || !text) return;

    var flexEl = form ? form.querySelector('input[name="budget_flexibility"]:checked') : null;
    var flex = flexEl ? flexEl.value : 'exact';
    if (flex !== '5' && flex !== '10') {
      display.classList.add('hidden');
      return;
    }
    var pct = parseInt(flex, 10) / 100; // 0.05 ou 0.10
    var bg = parseFloat(budgetGlobal && budgetGlobal.value);
    var bpp = parseFloat(budgetPerPerson && budgetPerPerson.value);

    // Format demandé :
    //   Budget global : 1425 € - 1575 €
    //   Budget par personne : 27 € - 33 €
    // Une ligne par dimension renseignée ; aucune ligne si rien n'est
    // saisi (zone cachée).
    var parts = [];
    if (bg > 0) {
      parts.push('Budget global : ' + formatEur(bg * (1 - pct)) + ' € - ' + formatEur(bg * (1 + pct)) + ' €');
    }
    if (bpp > 0) {
      parts.push('Budget par personne : ' + formatEur(bpp * (1 - pct)) + ' € - ' + formatEur(bpp * (1 + pct)) + ' €');
    }
    if (parts.length === 0) {
      // Pas encore de budget saisi → on cache la fourchette en attendant
      display.classList.add('hidden');
      return;
    }
    // Vide le wrapper et remplit avec une ligne par dimension. On évite
    // innerHTML pour rester sur du textContent (audit VULN-45) ; les
    // lignes sont des nodes <div> distincts.
    text.innerHTML = '';
    parts.forEach(function (line) {
      var div = document.createElement('div');
      div.textContent = line;
      text.appendChild(div);
    });
    display.classList.remove('hidden');
  }

  if (form) {
    form.addEventListener('change', function (ev) {
      if (ev.target && ev.target.name === 'budget_flexibility') {
        updateBudgetRange();
      }
    });
  }
  if (budgetGlobal) budgetGlobal.addEventListener('input', updateBudgetRange);
  if (budgetPerPerson) budgetPerPerson.addEventListener('input', updateBudgetRange);
  // Premier appel au chargement pour gérer les pre-fills (edit) +
  // le default `checked` sur "Exact" → la zone reste cachée.
  updateBudgetRange();

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

  // Installation / mise en place : on toggle la zone des précisions ET
  // on bascule l'attribut `required` sur l'input horaire en fonction
  // de l'état de la checkbox. Comme ça `validateStep` (qui filtre sur
  // [required]) déclenche l'erreur si la case est cochée mais qu'il
  // n'y a pas d'horaire, et passe sans broncher si la case est décochée.
  var setupCb = document.getElementById('wants_setup');
  var setupWrapper = document.getElementById('setup-details-wrapper');
  var setupTime = document.getElementById('service_setup_time');
  function syncSetupRequired() {
    if (!setupCb || !setupWrapper) return;
    if (setupCb.checked) {
      setupWrapper.classList.remove('hidden');
      if (setupTime) setupTime.required = true;
    } else {
      setupWrapper.classList.add('hidden');
      if (setupTime) {
        setupTime.required = false;
        // L'input reste rempli si l'utilisateur l'avait saisi puis
        // décoche — pas besoin de l'effacer, ça permet une coche/décoche
        // sans perdre la saisie. Les détails idem.
        setupTime.classList.remove('wizard-field-error');
      }
    }
  }
  if (setupCb) {
    setupCb.addEventListener('change', syncSetupRequired);
    // Premier appel pour gérer le pré-fill côté edit (qr.wants_setup
    // déjà coché à l'ouverture).
    syncSetupRequired();
  }

  // Demande ciblée avec offerings : la radio name="service_offering"
  // remplace les meal_types génériques. On miroir le choix dans le
  // champ caché #hidden-meal-type pour que le backend reçoive un
  // QuoteRequest.meal_type valide (data-meal-type est posé par le
  // template via la map OFFERING_TO_MEAL_TYPE côté Python).
  var hiddenMealType = document.getElementById('hidden-meal-type');
  if (hiddenMealType) {
    document.querySelectorAll('.wizard-offering-radio').forEach(function (r) {
      r.addEventListener('change', function () {
        if (r.checked && r.dataset.mealType) {
          hiddenMealType.value = r.dataset.mealType;
        }
      });
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

    // Recap : sur une demande ciblée, on a un radio service_offering
    // (avec label visible côté DOM) qui pilote le hidden meal_type.
    // On affiche le label de l'offering plutôt que le meal_type
    // générique pour rester cohérent avec ce que l'utilisateur vient
    // de cocher à l'étape 1.
    var offeringChecked = form.querySelector('input[name="service_offering"]:checked');
    if (offeringChecked) {
      var lbl = offeringChecked.closest('label');
      var span = lbl ? lbl.querySelector('span.font-bold') : null;
      setHtml('summary-meal-type', span ? span.textContent.trim() : offeringChecked.value);
    } else {
      var mealType = radioVal('meal_type');
      setHtml('summary-meal-type', mealTypeLabels[mealType] || mealType || '-');
    }
    setHtml('summary-service-type', val('service_type') || '-');
    setHtml('summary-event-date', val('event_date') || '-');
    // Horaires : "HH:MM – HH:MM" if at least one is set, with "?" for the
    // missing side; else "-". Mirrors the chip on the QR/order detail
    // pages so the wizard recap and the persisted display stay aligned.
    var startT = val('event_start_time');
    var endT = val('event_end_time');
    var timesText = '-';
    if (startT || endT) {
      timesText = (startT || '?') + ' – ' + (endT || '?');
    }
    setHtml('summary-event-times', timesText);
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
    // Le radio drinks_alcohol a été retiré de l'UI (redondant avec les
    // checkboxes Bières/Vins/Champagne). On ne l'affiche plus dans le
    // recap. La valeur reste tolérée côté backend pour les anciennes
    // demandes en BDD.
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
