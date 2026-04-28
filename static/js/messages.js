document.addEventListener('DOMContentLoaded', function () {
  var container = document.getElementById('messages-container');
  var form = document.getElementById('message-form');
  if (!container || !form) return;

  var threadId = container.dataset.threadId;
  var currentUserId = container.dataset.currentUserId;

  function scrollToBottom() {
    container.scrollTop = container.scrollHeight;
  }

  function renderMessage(msg) {
    var isSent = msg.sender_id === currentUserId;
    var div = document.createElement('div');
    div.className = 'flex ' + (isSent ? 'justify-end' : 'justify-start') + ' mb-3';
    var bubble = document.createElement('div');
    bubble.className = 'max-w-[70%] rounded-2xl px-4 py-2 text-sm ' +
      (isSent ? 'bg-terracotta text-white rounded-br-sm' : 'bg-cream-200 text-navy rounded-bl-sm');
    bubble.innerHTML = '<p>' + escapeHtml(msg.body) + '</p>' +
      '<p class="text-xs mt-1 ' + (isSent ? 'text-terracotta-100' : 'text-navy-200') + '">' +
      escapeHtml(msg.sender_name) + ' — ' + escapeHtml(formatTime(msg.created_at)) + '</p>';
    div.appendChild(bubble);
    return div;
  }

  function escapeHtml(text) {
    var d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }

  function formatTime(iso) {
    var d = new Date(iso);
    return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' }) +
      ' ' + d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  }

  function loadMessages() {
    fetch('/api/messages/' + threadId)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        container.innerHTML = '';
        data.messages.forEach(function (msg) {
          container.appendChild(renderMessage(msg));
        });
        scrollToBottom();
      });
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var bodyInput = form.querySelector('[name="body"]');
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

    var csrfToken = document.querySelector('meta[name="csrf-token"]').content;
    fetch('/api/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      body: JSON.stringify(payload),
    })
      .then(function (r) { return r.json(); })
      .then(function () {
        bodyInput.value = '';
        loadMessages();
      });
  });

  loadMessages();
  setInterval(loadMessages, 10000);
});
