// Star-rating input — visual layer only.
//
// Markup contract :
//   <div data-rating-input>
//     <label data-star-label data-star-value="1">
//       <input type="radio" name="rating" value="1" required ...visually-hidden...>
//       <span data-star-glyph><svg outline-star /></span>
//     </label>
//     ... (5 labels)
//   </div>
//
// The control works WITHOUT this script :
//   - clicking a label selects the radio (native behaviour);
//   - submitting the form posts the chosen `rating`;
//   - `required` triggers the browser's native validation tooltip if
//     no radio is selected.
//
// This script paints filled / outline stars based on hover + selection.
// CSP-safe (script-src 'self').
(function () {
  'use strict';

  var FILLED_FILL = '#F5A623';
  var EMPTY_STROKE = '#D1D5DB';

  function svgFilled() {
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="' + FILLED_FILL + '" style="width:1.75rem;height:1.75rem;display:block;">' +
      '<path d="M9.05 2.927c.3-.921 1.603-.921 1.902 0l1.286 3.957a1 1 0 00.95.69h4.16c.969 0 1.371 1.24.588 1.81l-3.366 2.446a1 1 0 00-.364 1.118l1.287 3.957c.299.921-.755 1.688-1.54 1.118l-3.366-2.446a1 1 0 00-1.176 0l-3.366 2.446c-.784.57-1.838-.197-1.54-1.118l1.287-3.957a1 1 0 00-.364-1.118L2.07 9.384c-.783-.57-.38-1.81.588-1.81h4.16a1 1 0 00.95-.69l1.287-3.957z"/>' +
      '</svg>';
  }
  function svgOutline() {
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none" stroke="' + EMPTY_STROKE + '" stroke-width="1.5" style="width:1.75rem;height:1.75rem;display:block;">' +
      '<path d="M9.05 2.927c.3-.921 1.603-.921 1.902 0l1.286 3.957a1 1 0 00.95.69h4.16c.969 0 1.371 1.24.588 1.81l-3.366 2.446a1 1 0 00-.364 1.118l1.287 3.957c.299.921-.755 1.688-1.54 1.118l-3.366-2.446a1 1 0 00-1.176 0l-3.366 2.446c-.784.57-1.838-.197-1.54-1.118l1.287-3.957a1 1 0 00-.364-1.118L2.07 9.384c-.783-.57-.38-1.81.588-1.81h4.16a1 1 0 00.95-.69l1.287-3.957z"/>' +
      '</svg>';
  }

  function paint(group, value) {
    group.querySelectorAll('[data-star-label]').forEach(function (label) {
      var v = parseInt(label.dataset.starValue, 10);
      var glyph = label.querySelector('[data-star-glyph]');
      if (!glyph) return;
      glyph.innerHTML = v <= value ? svgFilled() : svgOutline();
    });
  }

  function selectedValue(group) {
    var checked = group.querySelector('input[type="radio"]:checked');
    return checked ? parseInt(checked.value, 10) : 0;
  }

  function init(group) {
    paint(group, selectedValue(group));

    group.addEventListener('change', function () {
      paint(group, selectedValue(group));
    });

    group.addEventListener('mouseover', function (ev) {
      var label = ev.target.closest('[data-star-label]');
      if (!label) return;
      paint(group, parseInt(label.dataset.starValue, 10));
    });
    group.addEventListener('mouseleave', function () {
      paint(group, selectedValue(group));
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-rating-input]').forEach(init);
  });
})();
