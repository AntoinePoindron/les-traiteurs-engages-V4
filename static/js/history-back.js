// Global "Retour" handler.
//
// Any element with data-action="history-back" pops the current page
// off the browser history. If history is empty (the page was opened
// directly), we fall back to "/" so the user is never stranded.
//
// Lives in its own .js because CSP is `script-src 'self'` — the
// component used to use an inline onclick="history.back()" which the
// browser refused.
(function () {
  'use strict';

  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest('[data-action="history-back"]');
    if (!btn) return;
    ev.preventDefault();
    if (window.history.length > 1) {
      window.history.back();
    } else {
      window.location.href = '/';
    }
  });
})();
