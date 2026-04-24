(function () {
  function selectRole(role) {
    var roleInput = document.getElementById('role-input');
    var signupForm = document.getElementById('signup-form');
    var clientFields = document.getElementById('client-fields');
    var catererFields = document.getElementById('caterer-fields');

    if (roleInput) roleInput.value = role === 'client' ? 'client_admin' : 'caterer';
    if (signupForm) signupForm.style.display = 'block';
    if (clientFields) clientFields.style.display = role === 'client' ? 'block' : 'none';
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

    var clientInputs = document.querySelectorAll('#client-fields input');
    var catererInputs = document.querySelectorAll('#caterer-fields input, #caterer-fields select');
    clientInputs.forEach(function (el) { el.required = (role === 'client'); });
    catererInputs.forEach(function (el) { el.required = (role === 'caterer'); });
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

  document.addEventListener('DOMContentLoaded', function () {
    var tabClient = document.getElementById('tab-client');
    var tabCaterer = document.getElementById('tab-caterer');
    if (tabClient) tabClient.style.color = '#6B7280';
    if (tabCaterer) tabCaterer.style.color = '#6B7280';
  });
})();
