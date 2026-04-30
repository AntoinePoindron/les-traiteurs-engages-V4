// Read-only PDF preview modal toggle.
//
// Used on the caterer's request detail page (`templates/caterer/requests/detail.html`)
// to open a modal showing the persisted Quote in its PDF-style layout.
//
// Looks for a single modal with id="pdf-preview-modal" on the page.
// Opens when any element matching [data-action="open-pdf-preview"] is
// clicked, closes on the X button, on a click on the dimmed backdrop,
// or on the Escape key.
//
// Lives in its own .js (rather than inline in the template) because
// the project's CSP is `script-src 'self'` — inline scripts are
// blocked unless we add a per-render nonce, which the harden audit
// (P2) explicitly chose to avoid.
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var modal = document.getElementById('pdf-preview-modal');
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
      if (ev.target.closest('[data-action="open-pdf-preview"]')) { open(); return; }
      if (ev.target.closest('[data-action="close-pdf-preview"]')) { close(); return; }
      // Click on the dim backdrop (the modal element itself, not its
      // content card) closes the modal too.
      if (ev.target === modal) close();
    });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && !modal.classList.contains('hidden')) close();
    });
  });
})();
