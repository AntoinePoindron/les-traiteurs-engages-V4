// Toggle for the client-side "Nouvelle demande" modal.
//
// Triggered by any button with [data-action="open-new-request-menu"]
// (the CTAs on the dashboard, the requests list header, and the empty
// state). Closes on the X button, on a click on the dimmed backdrop,
// or on the Escape key.
//
// External script because the project's CSP is `script-src 'self'`
// — inline scripts are blocked.
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var modal = document.getElementById('new-request-modal');
    if (!modal) return;

    function open() {
      modal.classList.remove('hidden');
      document.body.style.overflow = 'hidden';
      if (window.lucide) lucide.createIcons();
    }
    function close() {
      modal.classList.add('hidden');
      document.body.style.overflow = '';
    }

    document.addEventListener('click', function (ev) {
      if (ev.target.closest('[data-action="open-new-request-menu"]')) {
        open();
        return;
      }
      if (ev.target.closest('[data-action="close-new-request-menu"]')) {
        close();
        return;
      }
      // Click on the dim backdrop closes the modal.
      if (ev.target === modal) close();
    });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && !modal.classList.contains('hidden')) close();
    });
  });
})();
