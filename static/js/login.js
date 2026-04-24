(function () {
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
    var el = ev.target.closest('[data-action="toggle-password"]');
    if (!el) return;
    togglePassword(el.dataset.target, el);
  });
})();
