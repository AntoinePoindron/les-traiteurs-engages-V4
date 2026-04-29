/**
 * caterer/profile.html — preview immediat du logo + grid photos
 * (drag-drop reorder, drop zone d'ajout, delete par photo).
 *
 * Servi en statique pour respecter la CSP `script-src 'self'` (audit
 * VULN-105) — pas d'inline script. Lu par le browser via `<script src>`.
 *
 * Le quota de photos n'est pas hardcode ici : il est passe via l'attribut
 * `data-photos-max` sur le `#photos-grid`, lui-meme alimente par Jinja.
 */
(function() {
  // === Logo preview === Affiche immediatement le logo selectionne via
  // URL.createObjectURL, sans attendre l'enregistrement.
  var logoInput = document.getElementById('logo');
  var logoPreview = document.getElementById('logo-preview');
  if (logoInput && logoPreview) {
    logoInput.addEventListener('change', function() {
      var file = logoInput.files && logoInput.files[0];
      if (!file) return;
      var url = URL.createObjectURL(file);
      logoPreview.innerHTML =
        '<img src="' + url + '" alt="Apercu logo" style="width:100%;height:100%;object-fit:contain;padding:0.25rem;">';
    });
  }

  // === Photos grid === Drag-drop pour reorganiser, drop zone pour ajouter,
  // preview immediat des fichiers selectionnes/droppes.
  var grid = document.getElementById('photos-grid');
  if (!grid) return;
  var PHOTOS_MAX = parseInt(grid.dataset.photosMax || '10', 10);
  var dragged = null;

  function getPreviewItems() {
    return Array.prototype.slice.call(grid.querySelectorAll('.photo-preview-item'));
  }

  function syncInputFiles() {
    // Reconstruit input.files dans l'ordre exact des .photo-preview-item
    // dans le DOM. Le serveur consomme les fichiers dans cet ordre via
    // les sentinelles "__NEW__" du champ photos_order.
    var input = document.getElementById('photos-upload');
    if (!input) return;
    var dt = new DataTransfer();
    getPreviewItems().forEach(function(el) {
      if (el._file) dt.items.add(el._file);
    });
    input.files = dt.files;
  }

  function refreshVitrineStyling() {
    var items = grid.querySelectorAll('.photo-item');
    items.forEach(function(el, idx) {
      el.style.boxShadow = (idx < 3)
        ? '0 0 0 3px var(--c-coral)'
        : '0 0 0 1px var(--c-border)';
      var badge = el.querySelector('.vitrine-badge');
      if (idx < 3) {
        if (!badge) {
          badge = document.createElement('span');
          badge.className = 'vitrine-badge';
          badge.style.cssText = 'position:absolute;top:0.375rem;left:0.375rem;background:var(--c-coral);color:white;font-size:0.625rem;font-weight:700;padding:2px 6px;border-radius:4px;text-transform:uppercase;letter-spacing:0.04em;';
          el.appendChild(badge);
        }
        badge.textContent = 'Vitrine ' + (idx + 1);
      } else if (badge) {
        badge.remove();
      }
    });
  }

  function refreshRemainingCounter() {
    var remaining = PHOTOS_MAX - grid.querySelectorAll('.photo-item').length;
    var el = document.getElementById('photos-remaining');
    if (el) el.textContent = remaining;
    var input = document.getElementById('photos-upload');
    if (input) input.disabled = (remaining <= 0);
    var wrapper = document.getElementById('photo-drop-wrapper');
    if (wrapper) wrapper.style.display = (remaining <= 0) ? 'none' : '';
  }

  // Cree une .photo-preview-item dans la grille pour un fichier en attente
  // d'upload. La preview ressemble a une vraie photo (drag-drop pour reorder
  // + bouton delete) mais l'attribut data-url vaut "" et le hidden
  // photos_order vaut "__NEW__" — le serveur consomme alors le prochain
  // fichier de input.files dans cet ordre.
  function addPreviewItem(file) {
    var item = document.createElement('div');
    item.className = 'photo-item photo-preview-item';
    item.draggable = true;
    item.dataset.url = '';
    item.style.cssText = 'position:relative;cursor:grab;border-radius:0.5rem;overflow:hidden;box-shadow:0 0 0 1px var(--c-border);';
    item._file = file;

    var orderInput = document.createElement('input');
    orderInput.type = 'hidden';
    orderInput.name = 'photos_order';
    orderInput.value = '__NEW__';
    item.appendChild(orderInput);

    var img = document.createElement('img');
    img.src = URL.createObjectURL(file);
    img.alt = '';
    img.draggable = false;
    img.style.cssText = 'display:block;width:100%;height:8rem;object-fit:cover;pointer-events:none;';
    item.appendChild(img);

    var newBadge = document.createElement('span');
    newBadge.className = 'preview-badge';
    newBadge.style.cssText = 'position:absolute;top:0.375rem;right:1.875rem;background:var(--c-navy);color:white;font-size:0.625rem;font-weight:700;padding:2px 6px;border-radius:4px;text-transform:uppercase;letter-spacing:0.04em;';
    newBadge.textContent = 'Nouveau';
    item.appendChild(newBadge);

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.dataset.action = 'delete-photo';
    btn.title = 'Retirer cette photo';
    btn.style.cssText = 'position:absolute;top:0.375rem;right:0.375rem;width:1.5rem;height:1.5rem;border:none;border-radius:9999px;background:rgba(0,0,0,0.5);color:white;font-size:1rem;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;';
    btn.textContent = '×';
    item.appendChild(btn);

    grid.appendChild(item);
  }

  function ingestFiles(fileList) {
    var existingCount = grid.querySelectorAll('.photo-item').length;
    var remaining = PHOTOS_MAX - existingCount;
    var files = Array.prototype.slice.call(fileList, 0, remaining);
    files.forEach(addPreviewItem);
    syncInputFiles();
    refreshVitrineStyling();
    refreshRemainingCounter();
  }

  // Drop zone : drag-drop de fichiers depuis le bureau + retour visuel.
  // Le label est deja un proxy de l'input file pour le clic.
  var dropZone = document.getElementById('photo-drop-zone');
  var fileInput = document.getElementById('photos-upload');
  var selectedCountLabel = document.getElementById('photos-selected-count');
  if (dropZone && fileInput) {
    function setDropActive(active) {
      dropZone.style.borderColor = active ? 'var(--c-navy)' : 'var(--c-border)';
      dropZone.style.background  = active ? 'var(--c-navy-soft)' : 'var(--c-cream-page)';
    }
    ['dragenter', 'dragover'].forEach(function(ev) {
      dropZone.addEventListener(ev, function(e) {
        e.preventDefault();
        if (e.dataTransfer && e.dataTransfer.types &&
            Array.prototype.indexOf.call(e.dataTransfer.types, 'Files') !== -1) {
          setDropActive(true);
        }
      });
    });
    ['dragleave', 'drop'].forEach(function(ev) {
      dropZone.addEventListener(ev, function(e) {
        if (ev === 'drop') e.preventDefault();
        setDropActive(false);
      });
    });
    dropZone.addEventListener('drop', function(e) {
      if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
      ingestFiles(e.dataTransfer.files);
      updateSelectedCount();
    });
    fileInput.addEventListener('change', function() {
      if (fileInput.files && fileInput.files.length) {
        var picked = Array.prototype.slice.call(fileInput.files);
        fileInput.value = '';
        ingestFiles(picked);
      }
      updateSelectedCount();
    });
    function updateSelectedCount() {
      var n = grid.querySelectorAll('.photo-preview-item').length;
      if (selectedCountLabel) {
        if (n > 0) {
          selectedCountLabel.style.display = '';
          selectedCountLabel.textContent = n + ' photo(s) en attente d\'envoi.';
        } else {
          selectedCountLabel.style.display = 'none';
        }
      }
    }
  }

  // Drag-drop reorder
  grid.addEventListener('dragstart', function(e) {
    var item = e.target.closest('.photo-item');
    if (!item) return;
    dragged = item;
    item.style.opacity = '0.4';
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', item.dataset.url || '');
    }
  });
  grid.addEventListener('dragend', function(e) {
    var item = e.target.closest('.photo-item');
    if (item) item.style.opacity = '1';
    dragged = null;
  });
  grid.addEventListener('dragover', function(e) {
    e.preventDefault();
  });
  grid.addEventListener('drop', function(e) {
    e.preventDefault();
    var target = e.target.closest('.photo-item');
    if (!dragged || !target || dragged === target) return;
    var items = Array.from(grid.querySelectorAll('.photo-item'));
    var draggedIdx = items.indexOf(dragged);
    var targetIdx = items.indexOf(target);
    if (draggedIdx < targetIdx) target.after(dragged);
    else target.before(dragged);
    syncInputFiles();
    refreshVitrineStyling();
  });

  grid.addEventListener('click', function(e) {
    var btn = e.target.closest('[data-action="delete-photo"]');
    if (!btn) return;
    var item = btn.closest('.photo-item');
    if (!item) return;
    if (item.classList.contains('photo-preview-item')) {
      item.remove();
      syncInputFiles();
    } else {
      var hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.name = 'photo_delete';
      hidden.value = item.dataset.url;
      item.parentNode.parentNode.appendChild(hidden);
      item.remove();
    }
    refreshVitrineStyling();
    refreshRemainingCounter();
  });
})();
