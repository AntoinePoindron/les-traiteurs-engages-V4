// Send-message modal handler.
//
// Wires every <form data-send-message-form="<modal_id>"> rendered by the
// `send_message_modal` Jinja macro to /api/messages. On success, swaps
// the modal from compose → sent state and points the "Voir la
// conversation" link at the thread_id returned by the API.
//
// CSP : inline scripts are blocked, so this lives in a static file
// referenced from base.html (or per-page) via a normal <script> tag.
(function () {
  'use strict';

  // Sentinel UUID the macro embeds via url_for(thread_endpoint,
  // thread_id=<sentinel>). We substitute it with the real thread_id
  // returned by /api/messages. Keeping the mapping in Flask via url_for
  // means a route rename blows up at render time, not silently in JS.
  var THREAD_ID_SENTINEL = '00000000-0000-0000-0000-000000000000';

  function buildThreadUrl(dialog, threadId) {
    var tpl = dialog && dialog.dataset.threadUrlTemplate;
    if (!tpl || !threadId) return null;
    return tpl.replace(THREAD_ID_SENTINEL, threadId);
  }

  function showError(form, msg) {
    var box = form.querySelector('[data-modal-error]');
    if (!box) return;
    box.textContent = msg;
    box.classList.remove('hidden');
  }

  function clearError(form) {
    var box = form.querySelector('[data-modal-error]');
    if (!box) return;
    box.classList.add('hidden');
    box.textContent = '';
  }

  function swapToSentState(modalId, threadId) {
    var dialog = document.getElementById(modalId);
    if (!dialog) return;
    var compose = dialog.querySelector('[data-modal-state="compose"]');
    var sent = dialog.querySelector('[data-modal-state="sent"]');
    if (compose) compose.classList.add('hidden');
    if (sent) sent.classList.remove('hidden');

    if (threadId) {
      var link = dialog.querySelector('[data-modal-thread-link]');
      var href = buildThreadUrl(dialog, threadId);
      if (link && href) link.href = href;
    }
    if (window.lucide) lucide.createIcons();
  }

  function resetToComposeState(dialog) {
    // After the dialog closes we want the next open to start fresh:
    // cleared textarea, no error banner, compose pane visible again.
    var compose = dialog.querySelector('[data-modal-state="compose"]');
    var sent = dialog.querySelector('[data-modal-state="sent"]');
    if (compose) compose.classList.remove('hidden');
    if (sent) sent.classList.add('hidden');
    var form = dialog.querySelector('[data-send-message-form]');
    if (form) {
      var ta = form.querySelector('[name="body"]');
      if (ta) ta.value = '';
      clearError(form);
      var btn = form.querySelector('[data-modal-send]');
      if (btn) btn.disabled = false;
    }
  }

  function bindForm(form) {
    if (form.__sendMessageBound) return;
    form.__sendMessageBound = true;

    var modalId = form.dataset.sendMessageForm;
    var sendBtn = form.querySelector('[data-modal-send]');

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      clearError(form);

      var body = (form.querySelector('[name="body"]').value || '').trim();
      if (!body) {
        showError(form, 'Le message ne peut pas être vide.');
        return;
      }

      var payload = {
        recipient_id: form.querySelector('[name="recipient_id"]').value,
        body: body,
      };
      var orderInput = form.querySelector('[name="order_id"]');
      if (orderInput && orderInput.value) payload.order_id = orderInput.value;
      var qrInput = form.querySelector('[name="quote_request_id"]');
      if (qrInput && qrInput.value) payload.quote_request_id = qrInput.value;

      var csrfMeta = document.querySelector('meta[name="csrf-token"]');
      var csrfToken = csrfMeta ? csrfMeta.content : '';

      if (sendBtn) sendBtn.disabled = true;
      fetch('/api/messages', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify(payload),
      })
        .then(function (r) {
          return r.json().then(function (data) { return { ok: r.ok, data: data }; });
        })
        .then(function (res) {
          if (!res.ok) {
            showError(
              form,
              (res.data && res.data.error) || 'Erreur lors de l’envoi.'
            );
            if (sendBtn) sendBtn.disabled = false;
            return;
          }
          swapToSentState(modalId, res.data && res.data.thread_id);
        })
        .catch(function () {
          showError(form, 'Erreur réseau. Réessayez.');
          if (sendBtn) sendBtn.disabled = false;
        });
    });
  }

  function bindCloseReset(dialog) {
    if (dialog.__sendMessageCloseBound) return;
    dialog.__sendMessageCloseBound = true;
    // Native <dialog> fires a "close" event whether close() was called
    // explicitly (Annuler / Fermer buttons via dialog-close action) or
    // backdrop-dismiss kicked in. Single hook covers both paths.
    dialog.addEventListener('close', function () {
      resetToComposeState(dialog);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document
      .querySelectorAll('[data-send-message-form]')
      .forEach(bindForm);
    document
      .querySelectorAll('dialog[data-send-message-dialog]')
      .forEach(bindCloseReset);
  });
})();
