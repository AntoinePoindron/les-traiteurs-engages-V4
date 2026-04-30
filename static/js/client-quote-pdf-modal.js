// Read-only quote-PDF modal toggle for the client's request detail page.
//
// A single page can carry several quotes (one per caterer that
// responded to the demand), so this script supports opening any
// modal whose id is referenced via data-target on the trigger button:
//
//   <button data-action="open-quote-pdf" data-target="quote-pdf-modal-XYZ">
//   <div   id="quote-pdf-modal-XYZ" class="hidden ...">…</div>
//
// Closes via the X (data-action="close-quote-pdf"), Escape, or a
// click on the dimmed backdrop of whichever modal is currently open.
//
// External script because CSP is `script-src 'self'` — inline blocked.
(function () {
  'use strict';

  function open(modal) {
    if (!modal) return;
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    if (window.lucide) lucide.createIcons();
  }
  function close(modal) {
    if (!modal) return;
    modal.classList.add('hidden');
    // Only release the body scroll lock if no other modal is still open.
    var anyOpen = document.querySelector('[id^="quote-pdf-modal-"]:not(.hidden)');
    if (!anyOpen) document.body.style.overflow = '';
  }
  function findOpenModal() {
    return document.querySelector('[id^="quote-pdf-modal-"]:not(.hidden)');
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.addEventListener('click', function (ev) {
      var openBtn = ev.target.closest('[data-action="open-quote-pdf"]');
      if (openBtn) {
        var targetId = openBtn.getAttribute('data-target');
        if (targetId) open(document.getElementById(targetId));
        return;
      }
      var closeBtn = ev.target.closest('[data-action="close-quote-pdf"]');
      if (closeBtn) {
        var targetIdC = closeBtn.getAttribute('data-target');
        close(document.getElementById(targetIdC));
        return;
      }
      // Click on a dim backdrop (the modal element itself, not its
      // content card) closes that modal.
      if (ev.target && ev.target.id && ev.target.id.indexOf('quote-pdf-modal-') === 0) {
        close(ev.target);
      }
    });

    document.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape') return;
      var openModal = findOpenModal();
      if (openModal) close(openModal);
    });
  });
})();
