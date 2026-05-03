(function () {
  function selectRole(role) {
    var roleInput = document.getElementById('role-input');
    var signupForm = document.getElementById('signup-form');
    var catererFields = document.getElementById('caterer-fields');

    if (roleInput) roleInput.value = role === 'client' ? 'client_admin' : 'caterer';
    if (signupForm) signupForm.style.display = 'block';
    if (catererFields) catererFields.style.display = role === 'caterer' ? 'block' : 'none';

    var tabClient = document.getElementById('tab-client');
    var tabCaterer = document.getElementById('tab-caterer');

    if (role === 'client') {
      if (tabClient) {
        tabClient.style.backgroundColor = 'white';
        tabClient.style.color = '#1A1A1A';
        tabClient.style.boxShadow = '0 1px 2px rgba(0,0,0,0.05)';
      }
      if (tabCaterer) {
        tabCaterer.style.backgroundColor = 'transparent';
        tabCaterer.style.color = '#6B7280';
        tabCaterer.style.boxShadow = 'none';
      }
    } else {
      if (tabCaterer) {
        tabCaterer.style.backgroundColor = 'white';
        tabCaterer.style.color = '#1A1A1A';
        tabCaterer.style.boxShadow = '0 1px 2px rgba(0,0,0,0.05)';
      }
      if (tabClient) {
        tabClient.style.backgroundColor = 'transparent';
        tabClient.style.color = '#6B7280';
        tabClient.style.boxShadow = 'none';
      }
    }

    var catererInputs = document.querySelectorAll('#caterer-fields input, #caterer-fields select');
    catererInputs.forEach(function (el) { el.required = (role === 'caterer'); });

    revalidate();
  }

  function togglePassword(inputId, btn) {
    var input = document.getElementById(inputId);
    if (!input) return;
    var icon = btn.querySelector('[data-lucide]');
    if (input.type === 'password') {
      input.type = 'text';
      if (icon) icon.setAttribute('data-lucide', 'eye-off');
    } else {
      input.type = 'password';
      if (icon) icon.setAttribute('data-lucide', 'eye');
    }
    if (window.lucide) lucide.createIcons();
  }

  // Mirror of blueprints/auth.py.validate_password — must stay in sync. Server
  // re-validates on POST so client tampering with this code can't bypass
  // policy; the client check exists only to disable the submit button and
  // explain failures inline.
  function passwordRules(pw) {
    pw = pw || '';
    var hasLower = /[a-z]/.test(pw);
    var hasUpper = /[A-Z]/.test(pw);
    var hasDigit = /\d/.test(pw);
    var hasSpecial = /[^A-Za-z0-9]/.test(pw);
    var categories = (hasLower ? 1 : 0) + (hasUpper ? 1 : 0) + (hasDigit ? 1 : 0) + (hasSpecial ? 1 : 0);
    return {
      length: pw.length >= 12,
      categories: categories >= 3,
    };
  }

  function paintRule(li, ok) {
    if (!li) return;
    li.classList.toggle('pw-rule-ok', ok);
    var icon = li.querySelector('[data-lucide]');
    if (icon) {
      icon.setAttribute('data-lucide', ok ? 'check-circle' : 'circle');
    }
  }

  function isFormValid() {
    var form = document.getElementById('signup-form');
    if (!form || form.style.display === 'none') return false;
    // Required fields: every visible required input must be non-empty.
    // `form.querySelectorAll('[required]')` returns hidden ones too, so
    // filter on `offsetParent !== null` (a quick "is visible" heuristic
    // that's good enough for our small fixed form).
    var fields = form.querySelectorAll('input[required], select[required]');
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i];
      if (f.offsetParent === null) continue; // hidden by role toggle
      if (!String(f.value || '').trim()) return false;
    }
    var rules = passwordRules(document.getElementById('password').value);
    return rules.length && rules.categories;
  }

  function revalidate() {
    var pw = document.getElementById('password');
    if (pw) {
      var rules = passwordRules(pw.value);
      paintRule(document.querySelector('#password-requirements [data-rule="length"]'), rules.length);
      paintRule(document.querySelector('#password-requirements [data-rule="categories"]'), rules.categories);
      if (window.lucide) lucide.createIcons();
    }
    var btn = document.getElementById('signup-submit');
    var hint = document.getElementById('signup-hint');
    if (btn) {
      var valid = isFormValid();
      btn.disabled = !valid;
      btn.classList.toggle('signup-submit-disabled', !valid);
      if (hint) hint.style.display = valid ? 'none' : 'block';
    }
  }

  document.addEventListener('click', function (ev) {
    var roleEl = ev.target.closest('[data-action="select-role"]');
    if (roleEl) {
      selectRole(roleEl.dataset.role);
      return;
    }
    var pwEl = ev.target.closest('[data-action="toggle-password"]');
    if (pwEl) {
      togglePassword(pwEl.dataset.target, pwEl);
    }
  });

  document.addEventListener('input', function (ev) {
    if (ev.target.closest('#signup-form')) revalidate();
  });
  document.addEventListener('change', function (ev) {
    if (ev.target.closest('#signup-form')) revalidate();
  });

  document.addEventListener('DOMContentLoaded', function () {
    // Pré-sélectionne "Entreprise" — c'est le parcours par défaut sur
    // la landing (CTA "S'inscrire" pointe vers ce formulaire). L'autre
    // onglet ("Traiteur") reste un clic simple pour les structures.
    selectRole('client');
    revalidate();
  });
})();
