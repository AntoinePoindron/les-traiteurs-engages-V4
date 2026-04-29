/**
 * Lightbox photo generique. Convention :
 *   - Le conteneur de la galerie a `id="photos-gallery"` et porte
 *     `data-photos` = JSON array des URLs (ordre = ordre dans la galerie).
 *   - Chaque element cliquable porte `data-photo-index="N"` (0-based).
 *   - La modale doit etre dans le DOM avec `id="lightbox"` et les
 *     enfants attendus (lightbox-img, lightbox-counter, boutons
 *     data-action="close|prev|next").
 *
 * Clavier : Echap pour fermer, fleches gauche/droite pour naviguer.
 * Click hors de l'image (sur le backdrop) ferme la modale.
 *
 * Servi en statique pour respecter la CSP `script-src 'self'`.
 */
(function() {
  var gallery = document.getElementById('photos-gallery');
  var lightbox = document.getElementById('lightbox');
  if (!gallery || !lightbox) return;

  var photos;
  try {
    photos = JSON.parse(gallery.dataset.photos || '[]');
  } catch (e) {
    photos = [];
  }
  if (!photos.length) return;

  var current = 0;
  var img = document.getElementById('lightbox-img');
  var counter = document.getElementById('lightbox-counter');
  var prevBtn = lightbox.querySelector('[data-action="prev"]');
  var nextBtn = lightbox.querySelector('[data-action="next"]');

  function show(idx) {
    // Wrap-around : -1 -> derniere, length -> premiere.
    current = ((idx % photos.length) + photos.length) % photos.length;
    if (img) img.src = photos[current];
    if (counter) counter.textContent = (current + 1) + ' / ' + photos.length;
    // Cacher prev/next si une seule photo.
    var single = photos.length <= 1;
    if (prevBtn) prevBtn.style.display = single ? 'none' : '';
    if (nextBtn) nextBtn.style.display = single ? 'none' : '';
  }

  function open(idx) {
    show(idx);
    lightbox.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  }

  function close() {
    lightbox.style.display = 'none';
    document.body.style.overflow = '';
  }

  gallery.addEventListener('click', function(e) {
    var target = e.target.closest('[data-photo-index]');
    if (!target) return;
    var idx = parseInt(target.dataset.photoIndex, 10);
    if (!isNaN(idx)) open(idx);
  });

  lightbox.addEventListener('click', function(e) {
    var action = e.target.closest('[data-action]');
    if (action) {
      var act = action.dataset.action;
      if (act === 'close') close();
      else if (act === 'prev') show(current - 1);
      else if (act === 'next') show(current + 1);
      return;
    }
    // Click sur le backdrop (en dehors de l'image et des boutons) = fermer.
    if (e.target === lightbox) close();
  });

  document.addEventListener('keydown', function(e) {
    if (lightbox.style.display === 'none' || !lightbox.style.display) return;
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowLeft') show(current - 1);
    else if (e.key === 'ArrowRight') show(current + 1);
  });
})();
