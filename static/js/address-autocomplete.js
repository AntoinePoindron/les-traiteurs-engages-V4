// Address autocomplete using the BAN (Base Adresse Nationale) free API.
//
// Markup contract:
//   <div data-address-autocomplete>
//     <input data-address-input id="event_address" name="event_address">
//     <ul data-address-suggestions class="hidden ..."></ul>
//   </div>
//   <input id="event_zip_code"  name="event_zip_code">
//   <input id="event_city"      name="event_city">
//   <input id="event_latitude"  name="event_latitude" type="hidden">
//   <input id="event_longitude" name="event_longitude" type="hidden">
//
// On every keystroke (debounced 200ms), if the input is ≥ 3 chars we
// query api-adresse.data.gouv.fr/search and render up to 6 suggestions.
// Clicking a suggestion fills:
//   - event_address  → housenumber + street ("12 rue de Rivoli")
//   - event_zip_code → postcode
//   - event_city     → city
//   - event_latitude / event_longitude → from the result's geometry
//
// CORS is enabled by BAN; no proxy needed. The CSP carries
// `https://api-adresse.data.gouv.fr` in connect-src (cf. app.py).
//
// CSP-safe: external script only, no inline JS.
(function () {
  'use strict';

  var BAN_ENDPOINT = 'https://api-adresse.data.gouv.fr/search/';
  var DEBOUNCE_MS = 200;
  var MIN_QUERY_LEN = 3;
  var MAX_RESULTS = 6;

  function debounce(fn, ms) {
    var t = null;
    return function () {
      var ctx = this;
      var args = arguments;
      if (t) clearTimeout(t);
      t = setTimeout(function () { fn.apply(ctx, args); }, ms);
    };
  }

  function escapeHtml(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  function init(container) {
    var input = container.querySelector('[data-address-input]');
    var list = container.querySelector('[data-address-suggestions]');
    if (!input || !list) return;

    // Sibling fields outside the container — looked up by id since
    // the wizard already names them event_zip_code / event_city /
    // event_latitude / event_longitude.
    var zip = document.getElementById('event_zip_code');
    var city = document.getElementById('event_city');
    var lat = document.getElementById('event_latitude');
    var lng = document.getElementById('event_longitude');

    function close() {
      list.innerHTML = '';
      list.classList.add('hidden');
    }

    function render(features) {
      list.innerHTML = '';
      if (!features.length) {
        close();
        return;
      }
      features.forEach(function (f, idx) {
        var p = f.properties || {};
        var li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.setAttribute('data-result-index', String(idx));
        li.style.cursor = 'pointer';
        li.className = 'px-3 py-2 text-sm text-text hover:bg-cream';
        li.style.borderBottom = '1px solid rgba(26,58,82,0.06)';
        var line1 = (p.housenumber ? p.housenumber + ' ' : '') + (p.street || p.name || '');
        var line2 = (p.postcode || '') + ' ' + (p.city || '');
        li.innerHTML =
          '<div style="font-weight:600;">' + escapeHtml(line1.trim()) + '</div>' +
          '<div style="font-size:0.75rem;color:#5A6F80;">' + escapeHtml(line2.trim()) + '</div>';
        li.addEventListener('mousedown', function (ev) {
          // mousedown (not click) so the input's blur listener doesn't
          // hide the dropdown before we get a chance to read the value.
          ev.preventDefault();
          select(f);
        });
        list.appendChild(li);
      });
      list.classList.remove('hidden');
    }

    function select(feature) {
      var p = feature.properties || {};
      var coords = (feature.geometry && feature.geometry.coordinates) || [null, null];
      var line = (p.housenumber ? p.housenumber + ' ' : '') + (p.street || p.name || '');
      input.value = line.trim() || (p.label || '');
      if (zip) zip.value = p.postcode || '';
      if (city) city.value = p.city || '';
      if (lng && coords[0] != null) lng.value = String(coords[0]);
      if (lat && coords[1] != null) lat.value = String(coords[1]);
      close();
    }

    var fetchSuggestions = debounce(function (q) {
      // BAN sometimes errors on very short or punctuation-only queries;
      // we already guard with MIN_QUERY_LEN.
      var url = BAN_ENDPOINT + '?q=' + encodeURIComponent(q) +
        '&limit=' + MAX_RESULTS + '&autocomplete=1';
      fetch(url, { credentials: 'omit' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data || !Array.isArray(data.features)) {
            close();
            return;
          }
          render(data.features);
        })
        .catch(function () { close(); });
    }, DEBOUNCE_MS);

    input.addEventListener('input', function () {
      var q = (input.value || '').trim();
      // Reset the geocoded coordinates on every edit — the user is
      // diverging from the previously-selected suggestion.
      if (lat) lat.value = '';
      if (lng) lng.value = '';
      if (q.length < MIN_QUERY_LEN) {
        close();
        return;
      }
      fetchSuggestions(q);
    });

    input.addEventListener('blur', function () {
      // 150ms grace so a click on a suggestion still registers before
      // the dropdown is hidden by the blur.
      setTimeout(close, 150);
    });

    input.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') close();
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-address-autocomplete]').forEach(init);
  });
})();
