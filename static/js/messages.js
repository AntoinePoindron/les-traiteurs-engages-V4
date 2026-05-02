// Messagerie chat pane.
//
// Two responsibilities:
//   1. Poll /api/messages/<thread_id> and render the bubble list inside
//      #messages-container. The script no-ops cleanly if the container
//      isn't on the page (e.g. when the right pane shows the empty
//      state, or for the read-only super_admin view without an input).
//   2. Wire the input form: Enter-to-send, paperclip stub, send-button
//      enabled state mirroring the input value, and Pieces jointes /
//      Conversation tab toggling.
//
// CSP : everything lives in this external file; no inline JS.
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    setupTabs();

    var container = document.getElementById('messages-container');
    if (!container) return;

    var threadId = container.dataset.threadId;
    var currentUserId = container.dataset.currentUserId;
    var otherAvatarUrl = container.dataset.otherAvatarUrl || '';

    function escapeHtml(text) {
      var d = document.createElement('div');
      d.textContent = text;
      return d.innerHTML;
    }

    function formatDate(iso) {
      // "23 avril" or "23 avril 14:32" depending on whether it's today
      var d = new Date(iso);
      var months = ['janvier','février','mars','avril','mai','juin',
                    'juillet','août','septembre','octobre','novembre','décembre'];
      var day = d.getDate();
      var month = months[d.getMonth()];
      var hh = ('0' + d.getHours()).slice(-2);
      var mm = ('0' + d.getMinutes()).slice(-2);
      var today = new Date();
      var sameDay = d.toDateString() === today.toDateString();
      return sameDay ? (hh + ':' + mm) : (day + ' ' + month + ' · ' + hh + ':' + mm);
    }

    function receivedAvatarHtml() {
      // Match the tile-style avatar from the messagerie panes. Only used
      // on received messages; sent messages skip the avatar entirely
      // (justify-end pushes the bubble flush to the right edge).
      if (otherAvatarUrl) {
        return '<div class="w-8 h-8 rounded-lg flex items-center justify-center bg-cream flex-shrink-0" style="overflow:hidden;">' +
          '<img src="' + escapeHtml(otherAvatarUrl) + '" alt="" style="width:100%;height:100%;object-fit:contain;padding:0.0625rem;">' +
          '</div>';
      }
      return '<div class="w-8 h-8 rounded-lg flex items-center justify-center bg-cream flex-shrink-0">' +
        '<i data-lucide="building-2" class="w-4 h-4 text-text-soft"></i>' +
        '</div>';
    }

    function renderMessage(msg) {
      var isSent = msg.sender_id === currentUserId;
      var row = document.createElement('div');
      // `flex-row-reverse` would be cleaner, but the project ships a
      // pre-built Tailwind CSS that the JIT scanner can't see through
      // (these bubbles are JS-rendered). `justify-end` is in the bundle
      // because static templates use it; that's enough to push the
      // sent-side group flush to the right.
      row.className = 'flex items-start gap-2 mb-4 ' + (isSent ? 'justify-end' : '');

      var bubbleWrap = document.createElement('div');
      bubbleWrap.className = 'max-w-[70%] flex flex-col ' + (isSent ? 'items-end' : 'items-start');
      bubbleWrap.innerHTML =
        '<div class="rounded-2xl px-4 py-2.5 text-sm ' +
          (isSent ? 'bg-navy text-white' : 'bg-cream text-text') +
        '"><p class="whitespace-pre-line">' + escapeHtml(msg.body) + '</p></div>' +
        '<p class="text-xs mt-1 text-mute">' + escapeHtml(formatDate(msg.created_at)) + '</p>';

      // Received: avatar (left) + bubble.
      // Sent: bubble only — pushed right by justify-end. We skip the
      // empty-avatar spacer that used to be there; with justify-end it
      // would just push the bubble away from the right edge.
      if (!isSent) {
        var avatar = document.createElement('div');
        avatar.innerHTML = receivedAvatarHtml();
        var firstChild = avatar.firstChild;
        if (firstChild) row.appendChild(firstChild);
      }
      row.appendChild(bubbleWrap);
      return row;
    }

    function scrollToBottom() {
      container.scrollTop = container.scrollHeight;
    }

    function loadMessages() {
      fetch('/api/messages/' + threadId)
        .then(function (r) { return r.json(); })
        .then(function (data) {
          container.innerHTML = '';
          (data.messages || []).forEach(function (msg) {
            container.appendChild(renderMessage(msg));
          });
          if (window.lucide) lucide.createIcons();
          scrollToBottom();
        });
    }

    var form = document.getElementById('message-form');
    if (form) {
      var bodyInput = form.querySelector('[name="body"]');
      var sendBtn = document.getElementById('message-send-btn');

      function refreshSendBtn() {
        var enabled = bodyInput.value.trim().length > 0;
        sendBtn.disabled = !enabled;
        if (enabled) {
          sendBtn.classList.remove('bg-disabled', 'opacity-60');
          sendBtn.classList.add('bg-navy');
        } else {
          sendBtn.classList.add('bg-disabled', 'opacity-60');
          sendBtn.classList.remove('bg-navy');
        }
      }

      bodyInput.addEventListener('input', refreshSendBtn);
      refreshSendBtn();

      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var body = bodyInput.value.trim();
        if (!body) return;
        var payload = {
          recipient_id: form.querySelector('[name="recipient_id"]').value,
          body: body,
        };
        var orderId = form.querySelector('[name="order_id"]');
        if (orderId && orderId.value) payload.order_id = orderId.value;
        var qrId = form.querySelector('[name="quote_request_id"]');
        if (qrId && qrId.value) payload.quote_request_id = qrId.value;

        var csrfMeta = document.querySelector('meta[name="csrf-token"]');
        var csrfToken = csrfMeta ? csrfMeta.content : '';
        sendBtn.disabled = true;
        fetch('/api/messages', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
          body: JSON.stringify(payload),
        })
          .then(function (r) {
            return r.json().then(function (data) { return { ok: r.ok, data: data }; });
          })
          .then(function (res) {
            if (!res.ok) {
              // Render an inline banner above the input so failures
              // aren't swallowed silently — the messagerie has no flash
              // surface of its own.
              showErrorBanner(res.data && res.data.error ? res.data.error : 'Erreur lors de l’envoi.');
              refreshSendBtn();
              return;
            }
            clearErrorBanner();
            bodyInput.value = '';
            refreshSendBtn();
            loadMessages();
          })
          .catch(function () {
            showErrorBanner('Erreur reseau. Reessayez.');
            refreshSendBtn();
          });
      });

      function showErrorBanner(text) {
        var existing = document.getElementById('messagerie-error-banner');
        if (existing) existing.remove();
        var div = document.createElement('div');
        div.id = 'messagerie-error-banner';
        div.className = 'mx-4 mb-2 px-3 py-2 rounded-lg text-xs bg-danger-soft text-danger';
        div.textContent = text;
        form.parentNode.insertBefore(div, form);
      }
      function clearErrorBanner() {
        var existing = document.getElementById('messagerie-error-banner');
        if (existing) existing.remove();
      }
    }

    loadMessages();
    setInterval(loadMessages, 10000);
  });

  function setupTabs() {
    // Conversation / Pieces jointes toggle. Each tab button has
    // data-target pointing to a sibling pane id.
    document.addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-action="messagerie-tab"]');
      if (!btn) return;
      var targetId = btn.dataset.target;
      var allBtns = document.querySelectorAll('[data-action="messagerie-tab"]');
      allBtns.forEach(function (b) {
        var active = b === btn;
        b.classList.toggle('border-navy', active);
        b.classList.toggle('text-navy', active);
        b.classList.toggle('border-transparent', !active);
        b.classList.toggle('text-mute', !active);
      });
      var panes = document.querySelectorAll('.messagerie-tab-pane');
      panes.forEach(function (p) {
        p.classList.toggle('hidden', p.id !== targetId);
      });
    });
  }
})();
