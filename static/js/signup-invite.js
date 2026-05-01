(function () {
  // Mirror of static/js/signup.js's password-rule + submit-disabled logic,
  // stripped of the role / catering / company-name machinery the invite
  // form doesn't need. Server still re-validates password policy.
  function passwordRules(pw) {
    pw = pw || "";
    var hasLower = /[a-z]/.test(pw);
    var hasUpper = /[A-Z]/.test(pw);
    var hasDigit = /\d/.test(pw);
    var hasSpecial = /[^A-Za-z0-9]/.test(pw);
    var categories =
      (hasLower ? 1 : 0) +
      (hasUpper ? 1 : 0) +
      (hasDigit ? 1 : 0) +
      (hasSpecial ? 1 : 0);
    return {
      length: pw.length >= 12,
      categories: categories >= 3,
    };
  }

  function paintRule(li, ok) {
    if (!li) return;
    li.classList.toggle("pw-rule-ok", ok);
    var icon = li.querySelector("[data-lucide]");
    if (icon) icon.setAttribute("data-lucide", ok ? "check-circle" : "circle");
  }

  function togglePassword(inputId, btn) {
    var input = document.getElementById(inputId);
    if (!input) return;
    var icon = btn.querySelector("[data-lucide]");
    if (input.type === "password") {
      input.type = "text";
      if (icon) icon.setAttribute("data-lucide", "eye-off");
    } else {
      input.type = "password";
      if (icon) icon.setAttribute("data-lucide", "eye");
    }
    if (window.lucide) lucide.createIcons();
  }

  function revalidate() {
    var pw = document.getElementById("password");
    if (!pw) return;
    var rules = passwordRules(pw.value);
    paintRule(
      document.querySelector('#password-requirements [data-rule="length"]'),
      rules.length
    );
    paintRule(
      document.querySelector('#password-requirements [data-rule="categories"]'),
      rules.categories
    );
    if (window.lucide) lucide.createIcons();

    var btn = document.getElementById("signup-invite-submit");
    if (btn) {
      var valid = rules.length && rules.categories;
      btn.disabled = !valid;
      btn.classList.toggle("signup-submit-disabled", !valid);
    }
  }

  document.addEventListener("click", function (ev) {
    var pwEl = ev.target.closest('[data-action="toggle-password"]');
    if (pwEl) togglePassword(pwEl.dataset.target, pwEl);
  });
  document.addEventListener("input", function (ev) {
    if (ev.target.closest("#signup-invite-form")) revalidate();
  });
  document.addEventListener("DOMContentLoaded", revalidate);
})();
