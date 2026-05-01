"""Smoke tests for the UI macros in templates/components/ui.html.

Renders each macro inside a minimal Jinja template and asserts the output
contains the structural markers that downstream pages rely on. Catches
broken macros before they ship to a real page that uses them.
"""

from flask import render_template_string


def _render(app, snippet: str) -> str:
    """Render a Jinja snippet inside the app context (so url_for works)."""
    with app.test_request_context("/"):
        return render_template_string(snippet)


def test_back_button_with_history(app):
    out = _render(
        app, '{% from "components/ui.html" import back_button %}{{ back_button() }}'
    )
    assert "history.back()" in out
    assert "Retour" in out
    assert "chevron-left" in out


def test_back_button_with_href(app):
    out = _render(
        app,
        '{% from "components/ui.html" import back_button %}'
        '{{ back_button(label="Tableau de bord", href="/admin/dashboard") }}',
    )
    assert 'href="/admin/dashboard"' in out
    assert "Tableau de bord" in out
    assert "history.back()" not in out  # uses <a> not <button>


def test_info_chip_with_label(app):
    out = _render(
        app,
        '{% from "components/ui.html" import info_chip %}'
        '{{ info_chip(icon="users", value="42 convives", label="Couverts") }}',
    )
    assert "Couverts" in out
    assert "42 convives" in out
    assert 'data-lucide="users"' in out


def test_info_chip_without_label(app):
    out = _render(
        app,
        '{% from "components/ui.html" import info_chip %}'
        '{{ info_chip(icon="calendar", value="12 mars") }}',
    )
    assert "12 mars" in out
    # Label paragraph should not be rendered when label arg is None
    assert "font-size:10px" not in out


def test_contact_card_caterer_full(app):
    out = _render(
        app,
        '{% from "components/ui.html" import contact_card %}'
        '{{ contact_card(entity_type="caterer", entity_name="ESAT Saveurs", '
        'contact_first_name="Jean", contact_last_name="Dupont", '
        'contact_email="jd@example.fr", contact_user_id="abc", '
        'messages_href="/client/messages") }}',
    )
    assert "TRAITEUR" in out
    assert "ESAT Saveurs" in out
    assert "Jean Dupont" in out
    assert "JD" in out  # initials
    assert 'href="/client/messages"' in out
    assert "chef-hat" in out  # fallback icon variant


def test_contact_card_client_no_logo(app):
    out = _render(
        app,
        '{% from "components/ui.html" import contact_card %}'
        '{{ contact_card(entity_type="client", entity_name="Acme Solutions", '
        'contact_email="bob@acme.fr") }}',
    )
    assert "CLIENT" in out
    assert "Acme Solutions" in out
    assert "building-2" in out  # client fallback icon
    # No message button when contact_user_id is None
    assert "Envoyer un message" not in out


def test_submit_button(app):
    out = _render(
        app,
        '{% from "components/ui.html" import submit_button %}'
        '{{ submit_button(label="Enregistrer", pending_label="Enregistrement…", class="btn-navy") }}',
    )
    assert 'type="submit"' in out
    assert "Enregistrer" in out
    assert 'data-pending-label="Enregistrement…"' in out
    assert "btn-navy" in out


def test_confirm_dialog_default_variant(app):
    out = _render(
        app,
        '{% from "components/confirm_dialog.html" import confirm_dialog %}'
        '{{ confirm_dialog(id="del-modal", title="Supprimer ?", '
        'message="Cette action est definitive.", action_url="/x") }}',
    )
    assert 'id="del-modal"' in out
    assert "help-circle" in out  # default variant icon
    assert "csrf_token" in out
    assert 'action="/x"' in out


def test_confirm_dialog_destructive_variant(app):
    out = _render(
        app,
        '{% from "components/confirm_dialog.html" import confirm_dialog %}'
        '{{ confirm_dialog(id="dz", title="Supprimer ?", message="...", '
        'action_url="/x", destructive=True) }}',
    )
    assert "alert-triangle" in out  # danger variant icon
    assert "#DC2626" in out  # danger color tokens inline
