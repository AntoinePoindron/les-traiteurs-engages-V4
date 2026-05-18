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
    // The server pre-renders the count + visibility on every page load
    // via the `_inject_notifications` context processor; this poll
    // only refreshes the value live. A failed/non-JSON response leaves
    // the SSR value intact rather than wiping the badge to 0.
    fetch('/api/notifications', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || typeof data.unread_count !== 'number') return;
        var n = Math.max(0, data.unread_count);
        document.querySelectorAll('.notification-badge').forEach(function (badge) {
          // No-op short-circuit: avoid 4 DOM writes per tick when the
          // count hasn't moved (the common case on idle tabs).
          if (badge.dataset.count === String(n)) return;
          var plural = n === 1 ? '' : 's';
          badge.classList.toggle('hidden', n <= 0);
          badge.textContent = n > 99 ? '99+' : String(n);
          badge.setAttribute('data-count', String(n));
          badge.setAttribute('aria-label', n + ' notification' + plural + ' non lue' + plural);
        });
      })
      .catch(function () { /* leave the SSR value intact */ });
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
    'copy-to-clipboard': function (el) {
      // Copy `data-value` (or the textContent of #data-target) to the
      // user's clipboard. Briefly swaps the button label so they get a
      // visual confirmation.
      var text = el.dataset.value;
      if (!text && el.dataset.target) {
        var src = document.getElementById(el.dataset.target);
        if (src) text = src.value || src.textContent || '';
      }
      if (!text) return;
      var done = function () {
        var label = el.querySelector('[data-copy-label]') || el;
        var original = label.textContent;
        label.textContent = el.dataset.copiedLabel || 'Copié !';
        setTimeout(function () { label.textContent = original; }, 1500);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () {});
        return;
      }
      // execCommand fallback for older browsers / non-HTTPS contexts.
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); done(); } catch (e) {}
      document.body.removeChild(ta);
    },
  };

  document.addEventListener('click', function (ev) {
    var el = ev.target.closest('[data-action]');
    if (!el) return;
    var fn = ACTIONS[el.dataset.action];
    if (fn) fn(el, ev);
  });

  // Notifications dropdown: close on click outside the panel or its
  // trigger. Runs after the toggle-hidden action above, so opening the
  // dropdown via the bell isn't immediately undone by this handler.
  document.addEventListener('click', function (ev) {
    var dropdown = document.getElementById('notifications-modal');
    if (!dropdown || dropdown.classList.contains('hidden')) return;
    if (ev.target.closest('[data-target="notifications-modal"]')) return;
    if (ev.target.closest('#notifications-modal')) return;
    dropdown.classList.add('hidden');
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

  // Auto-dismiss flash toasts — different durations by category so an
  // error stays long enough to read while a success doesn't linger.
  // Hovering the toast pauses the timer; mouseleave restarts it from
  // scratch, so the user can read at their own pace.
  function initFlashToasts() {
    var FLASH_DURATIONS = { success: 4000, info: 5000, error: 7000 };
    var toasts = document.querySelectorAll('.flash-toast');
    toasts.forEach(function (toast) {
      var category = toast.dataset.flashCategory || 'info';
      var duration = FLASH_DURATIONS[category] || FLASH_DURATIONS.info;
      var timerId = null;

      function dismiss() {
        toast.classList.add('flash-toast-leaving');
        // Wait for the CSS opacity/transform transition before removing
        // so screen readers don't see the node disappear mid-flight.
        setTimeout(function () {
          if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 280);
      }
      function start() { timerId = setTimeout(dismiss, duration); }
      function clear() { if (timerId) { clearTimeout(timerId); timerId = null; } }

      toast.addEventListener('mouseenter', clear);
      toast.addEventListener('mouseleave', start);
      // Clicking the X button instantly removes the parent — no need
      // for the timer afterwards.
      toast.addEventListener('click', function (ev) {
        if (ev.target.closest('[data-action="dismiss-parent"]')) clear();
      });
      start();
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
      // Pause the poll while the tab is hidden — saves a request every
      // 30s on backgrounded tabs and runs a fresh fetch the moment the
      // user comes back, so the count is current at the first glance.
      var pollId = null;
      function startPolling() {
        if (pollId !== null) return;
        updateNotificationBadge();
        pollId = setInterval(updateNotificationBadge, 30000);
      }
      function stopPolling() {
        if (pollId === null) return;
        clearInterval(pollId);
        pollId = null;
      }
      if (!document.hidden) startPolling();
      document.addEventListener('visibilitychange', function () {
        if (document.hidden) stopPolling();
        else startPolling();
      });
    }
    initBackdropDismiss();
    initFlashToasts();
  });
})();
