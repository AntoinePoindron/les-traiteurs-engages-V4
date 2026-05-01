"""WTForms classes for the `client` blueprint.

Centralises validation and type-coercion of POST inputs. Each handler binds
`Form(request.form)` and calls `form.validate()` — invalid input is rejected
with a flash message + re-render rather than raising and 500ing.

Field names match the corresponding `<input name="...">` in the existing
templates so no template changes are required for the binding to work.
"""
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
    FloatField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import (
    Email,
    InputRequired,
    Length,
    NumberRange,
    Optional,
)

from models import MEAL_TYPE_LABELS

MEAL_TYPES = [(m.value, label) for m, label in MEAL_TYPE_LABELS.items()]


class QuoteRequestForm(FlaskForm):
    """Used by both POST /client/requests/new and POST /client/requests/<id>/edit."""

    company_service_id = StringField(validators=[Optional(), Length(max=36)])
    service_type = StringField(validators=[Optional(), Length(max=100)])
    meal_type = SelectField(choices=[("", "—")] + MEAL_TYPES, validators=[Optional()])
    event_date = DateField(format="%Y-%m-%d", validators=[Optional()])
    guest_count = IntegerField(validators=[Optional(), NumberRange(min=1, max=10000)])
    event_address = StringField(validators=[Optional(), Length(max=500)])
    event_city = StringField(validators=[Optional(), Length(max=255)])
    event_zip_code = StringField(validators=[Optional(), Length(max=10)])
    event_latitude = FloatField(validators=[Optional(), NumberRange(min=-90, max=90)])
    event_longitude = FloatField(validators=[Optional(), NumberRange(min=-180, max=180)])
    budget_global = DecimalField(places=2, validators=[Optional(), NumberRange(min=0)])
    budget_per_person = DecimalField(places=2, validators=[Optional(), NumberRange(min=0)])

    dietary_vegetarian = BooleanField()
    dietary_vegan = BooleanField()
    dietary_halal = BooleanField()
    dietary_gluten_free = BooleanField()
    dietary_lactose_free = BooleanField()

    vegetarian_count = IntegerField(validators=[Optional(), NumberRange(min=0, max=10000)])
    vegan_count = IntegerField(validators=[Optional(), NumberRange(min=0, max=10000)])
    halal_count = IntegerField(validators=[Optional(), NumberRange(min=0, max=10000)])
    gluten_free_count = IntegerField(validators=[Optional(), NumberRange(min=0, max=10000)])
    lactose_free_count = IntegerField(validators=[Optional(), NumberRange(min=0, max=10000)])

    drinks_alcohol = BooleanField()
    drinks_details = TextAreaField(validators=[Optional(), Length(max=5000)])

    wants_waitstaff = BooleanField()
    service_waitstaff_details = TextAreaField(validators=[Optional(), Length(max=5000)])
    wants_equipment = BooleanField()
    wants_decoration = BooleanField()
    wants_setup = BooleanField()
    wants_cleanup = BooleanField()

    is_compare_mode = BooleanField()
    message_to_caterer = TextAreaField(validators=[Optional(), Length(max=5000)])
    # Set when the wizard was launched from a specific caterer profile
    # (-> "Demander un devis" button on /caterers/<id>). Forces a
    # single-caterer flow that skips admin matching.
    target_caterer_id = StringField(validators=[Optional(), Length(max=36)])

    # The dietary checkboxes use value="1" in the templates; WTForms BooleanField
    # treats "1"/"true"/"on" as True, anything else as False. Matches existing UI.


class ServiceForm(FlaskForm):
    """Service CRUD: POST /client/team/services and /edit."""

    name = StringField(validators=[InputRequired(), Length(min=1, max=255)])
    description = TextAreaField(validators=[Optional(), Length(max=5000)])
    annual_budget = DecimalField(places=2, validators=[Optional(), NumberRange(min=0)])


class EmployeeForm(FlaskForm):
    """Employee CRUD: POST /client/team/employees and /edit."""

    first_name = StringField(validators=[InputRequired(), Length(min=1, max=255)])
    last_name = StringField(validators=[InputRequired(), Length(min=1, max=255)])
    email = StringField(validators=[InputRequired(), Email(), Length(max=255)])
    position = StringField(validators=[Optional(), Length(max=255)])
    service_id = StringField(validators=[Optional(), Length(max=36)])


class UserProfileForm(FlaskForm):
    """POST /client/profile."""

    first_name = StringField(validators=[Optional(), Length(max=255)])
    last_name = StringField(validators=[Optional(), Length(max=255)])
    email = StringField(validators=[Optional(), Email(), Length(max=255)])
    current_password = PasswordField(validators=[Optional()])


class CompanySettingsForm(FlaskForm):
    """POST /client/settings."""

    name = StringField(validators=[Optional(), Length(max=255)])
    siret = StringField(validators=[Optional(), Length(min=14, max=14, message="Le SIRET doit comporter exactement 14 caractères.")])
    address = StringField(validators=[Optional(), Length(max=500)])
    city = StringField(validators=[Optional(), Length(max=255)])
    zip_code = StringField(validators=[Optional(), Length(max=10)])
    oeth_eligible = BooleanField()
    budget_annual = DecimalField(places=2, validators=[Optional(), NumberRange(min=0)])
    # logo file is read via request.files (WTForms FileField is overkill for a single optional logo)


class QuoteAcceptForm(FlaskForm):
    """POST /client/requests/<id>/accept-quote."""

    quote_id = StringField(validators=[InputRequired(), Length(max=36)])


class QuoteRefuseForm(FlaskForm):
    """POST /client/requests/<id>/refuse-quote."""

    quote_id = StringField(validators=[InputRequired(), Length(max=36)])
    refusal_reason = TextAreaField(validators=[Optional(), Length(max=5000)])
