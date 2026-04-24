(function () {
  function renderIcons() { if (window.lucide) lucide.createIcons(); }

  function markActiveSidebar() {
    var path = window.location.pathname;
    document.querySelectorAll('.sidebar-link').forEach(function (link) {
      var href = link.getAttribute('href');
      if (href && (path === href || path.startsWith(href + '/'))) link.classList.add('active');
    });
  }

  function toggleMobileMenu() {
    var sidebar = document.getElementById('sidebar');
    var overlay = document.getElementById('sidebar-overlay');
    if (sidebar) sidebar.classList.toggle('-translate-x-full');
    if (overlay) overlay.classList.toggle('hidden');
  }

  function updateLayout() {
    var main = document.getElementById('main-content');
    if (!main) return;
    main.style.marginLeft = window.innerWidth >= 1024 ? '241px' : '0';
  }

  function updateNotificationBadge() {
    fetch('/api/notifications')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        document.querySelectorAll('.notification-badge').forEach(function (badge) {
          badge.classList.toggle('hidden', !(data.unread_count > 0));
        });
      })
      .catch(function () {});
  }

  var ACTIONS = {
    'toggle-mobile-menu': function () { toggleMobileMenu(); },
    'dialog-open': function (el) {
      var d = document.getElementById(el.dataset.target);
      if (d && d.showModal) d.showModal();
      else if (d) { d.classList.remove('hidden'); d.classList.add('flex'); }
    },
    'dialog-close': function (el) {
      var d = document.getElementById(el.dataset.target);
      if (d && d.close) d.close();
      else if (d) { d.classList.add('hidden'); d.classList.remove('flex'); }
    },
    'dismiss-parent': function (el) {
      var target = el.closest(el.dataset.target || '[data-dismissable]') || el.parentElement;
      if (target) target.remove();
    },
    'toggle-hidden': function (el) {
      var d = document.getElementById(el.dataset.target);
      if (d) d.classList.toggle('hidden');
    },
    'submit-form': function (el) {
      var f = document.getElementById(el.dataset.target);
      if (f) f.submit();
    },
    'confirm-submit': function (el, ev) {
      if (!window.confirm(el.dataset.confirm || 'Confirmer ?')) ev.preventDefault();
    },
  };

  document.addEventListener('click', function (ev) {
    var el = ev.target.closest('[data-action]');
    if (!el) return;
    var fn = ACTIONS[el.dataset.action];
    if (fn) fn(el, ev);
  });

  function initBackdropDismiss() {
    document.querySelectorAll('[data-backdrop-dismiss]').forEach(function (el) {
      if (el.__bdInit) return;
      el.__bdInit = true;
      el.addEventListener('click', function (ev) {
        if (ev.target !== el) return;
        if (el.close) el.close();
        else { el.classList.add('hidden'); el.classList.remove('flex'); }
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    renderIcons();
    markActiveSidebar();
    var mobileBtn = document.getElementById('mobile-menu-btn');
    if (mobileBtn) mobileBtn.addEventListener('click', toggleMobileMenu);
    updateLayout();
    window.addEventListener('resize', updateLayout);
    if (document.querySelector('.notification-badge')) {
      updateNotificationBadge();
      setInterval(updateNotificationBadge, 30000);
    }
    initBackdropDismiss();
  });
})();
