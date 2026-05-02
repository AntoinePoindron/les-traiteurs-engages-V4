// Star-rating input for the order-detail review form.
//
// Markup contract :
//   <div data-rating-input data-target="<input-id>">
//     <button type="button" data-rating-value="1"></button>
//     ... (5 buttons)
//   </div>
//   <input type="hidden" id="<input-id>" name="rating" value="">
//
// Each button is filled or outlined depending on the current value.
// Submit button is disabled until a value is set.
//
// CSP-safe (script-src 'self'). No inline JS.
(function () {
  'use strict';

  var FILLED_FILL = '#F5A623';
  var EMPTY_STROKE = '#D1D5DB';

  function svgFor(filled) {
    if (filled) {
      return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="' + FILLED_FILL + '" class="w-7 h-7">' +
        '<path d="M9.05 2.927c.3-.921 1.603-.921 1.902 0l1.286 3.957a1 1 0 00.95.69h4.16c.969 0 1.371 1.24.588 1.81l-3.366 2.446a1 1 0 00-.364 1.118l1.287 3.957c.299.921-.755 1.688-1.54 1.118l-3.366-2.446a1 1 0 00-1.176 0l-3.366 2.446c-.784.57-1.838-.197-1.54-1.118l1.287-3.957a1 1 0 00-.364-1.118L2.07 9.384c-.783-.57-.38-1.81.588-1.81h4.16a1 1 0 00.95-.69l1.287-3.957z"/>' +
        '</svg>';
    }
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none" stroke="' + EMPTY_STROKE + '" stroke-width="1.5" class="w-7 h-7">' +
      '<path d="M9.05 2.927c.3-.921 1.603-.921 1.902 0l1.286 3.957a1 1 0 00.95.69h4.16c.969 0 1.371 1.24.588 1.81l-3.366 2.446a1 1 0 00-.364 1.118l1.287 3.957c.299.921-.755 1.688-1.54 1.118l-3.366-2.446a1 1 0 00-1.176 0l-3.366 2.446c-.784.57-1.838-.197-1.54-1.118l1.287-3.957a1 1 0 00-.364-1.118L2.07 9.384c-.783-.57-.38-1.81.588-1.81h4.16a1 1 0 00.95-.69l1.287-3.957z"/>' +
      '</svg>';
  }

  function paint(group, value) {
    var btns = group.querySelectorAll('[data-rating-value]');
    btns.forEach(function (btn) {
      var v = parseInt(btn.dataset.ratingValue, 10);
      btn.innerHTML = svgFor(v <= value);
    });
  }

  function init(group) {
    var targetId = group.dataset.target;
    var input = document.getElementById(targetId);
    if (!input) return;
    var formEl = group.closest('form');
    var submitBtn = formEl ? formEl.querySelector('[type="submit"]') : null;

    function setValue(v) {
      input.value = v;
      paint(group, v);
      if (submitBtn) submitBtn.disabled = !v;
    }

    paint(group, parseInt(input.value, 10) || 0);
    if (submitBtn) submitBtn.disabled = !input.value;

    group.addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-rating-value]');
      if (!btn) return;
      ev.preventDefault();
      setValue(parseInt(btn.dataset.ratingValue, 10));
    });

    // Light hover preview without committing the value.
    group.addEventListener('mouseover', function (ev) {
      var btn = ev.target.closest('[data-rating-value]');
      if (!btn) return;
      paint(group, parseInt(btn.dataset.ratingValue, 10));
    });
    group.addEventListener('mouseleave', function () {
      paint(group, parseInt(input.value, 10) || 0);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-rating-input]').forEach(init);
  });
})();
