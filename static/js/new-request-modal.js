// Toggle for the client-side "Nouvelle demande" dropdown.
//
// Triggered by any button with [data-action="open-new-request-menu"]
// (the CTAs on the dashboard, the requests list header, and the empty
// states). The dropdown is positioned with `position: fixed` below the
// clicked trigger, right-aligned to its right edge by default and
// clamped to the viewport so it never spills off-screen.
//
// Closes on:
//   - click outside the dropdown
//   - Escape key
//   - window scroll / resize (cheap repositioning skipped for simplicity)
//
// External script because the project's CSP is `script-src 'self'`
// — inline scripts are blocked.
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var menu = document.getElementById('new-request-modal');
    if (!menu) return;

    var currentTrigger = null;

    function position(trigger) {
      var rect = trigger.getBoundingClientRect();
      // Right-align dropdown to the trigger's right edge.
      // Reveal first so offsetWidth is measurable.
      menu.style.visibility = 'hidden';
      menu.classList.remove('hidden');
      var menuWidth = menu.offsetWidth;
      var left = rect.right - menuWidth;
      var minLeft = 8;
      var maxLeft = window.innerWidth - menuWidth - 8;
      if (left < minLeft) left = minLeft;
      if (left > maxLeft) left = Math.max(minLeft, maxLeft);
      menu.style.top = (rect.bottom + 8) + 'px';
      menu.style.left = left + 'px';
      menu.style.visibility = '';
    }

    function open(trigger) {
      currentTrigger = trigger;
      position(trigger);
      if (window.lucide) lucide.createIcons();
    }
    function close() {
      menu.classList.add('hidden');
      currentTrigger = null;
    }
    function isOpen() {
      return !menu.classList.contains('hidden');
    }

    document.addEventListener('click', function (ev) {
      var trigger = ev.target.closest('[data-action="open-new-request-menu"]');
      if (trigger) {
        if (isOpen() && currentTrigger === trigger) {
          close();
        } else {
          open(trigger);
        }
        return;
      }
      // Click anywhere else (including outside the dropdown) closes it.
      if (isOpen() && !ev.target.closest('#new-request-modal')) {
        close();
      }
    });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && isOpen()) close();
    });

    // Reposition would be nicer, but closing on scroll/resize is
    // simpler and avoids the dropdown drifting away from its trigger.
    window.addEventListener('scroll', function () {
      if (isOpen()) close();
    }, true);
    window.addEventListener('resize', function () {
      if (isOpen()) close();
    });
  });
})();
