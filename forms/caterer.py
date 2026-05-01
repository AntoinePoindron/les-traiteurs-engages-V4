"""WTForms classes for the `caterer` blueprint."""

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    IntegerField,
    StringField,
    TextAreaField,
)
from wtforms.validators import Length, NumberRange, Optional


class CatererProfileForm(FlaskForm):
    """POST /caterer/profile."""

    name = StringField(validators=[Optional(), Length(max=255)])
    description = TextAreaField(validators=[Optional(), Length(max=5000)])
    address = StringField(validators=[Optional(), Length(max=500)])
    city = StringField(validators=[Optional(), Length(max=255)])
    zip_code = StringField(validators=[Optional(), Length(max=10)])
    delivery_radius_km = IntegerField(
        validators=[Optional(), NumberRange(min=0, max=2000)]
    )
    dietary_vegetarian = BooleanField()
    dietary_vegan = BooleanField()
    dietary_halal = BooleanField()
    dietary_gluten_free = BooleanField()
    dietary_lactose_free = BooleanField()
    service_config = TextAreaField(validators=[Optional(), Length(max=10000)])
    # photos handled separately via request.files

    # service_offerings is read off request.form.getlist; per-offering
    # specs (capacity/price/délai per slug) are parsed manually in the
    # profile handler — WTForms has no clean primitive for the dynamic
    # `spec[<slug>][<field>]` shape.


class QuoteForm(FlaskForm):
    """POST /caterer/requests/<qr_id>/quote and /edit."""

    notes = TextAreaField(validators=[Optional(), Length(max=10000)])
    valid_until = DateField(format="%Y-%m-%d", validators=[Optional()])
    # `details` is JSON in a hidden input — validated separately because WTForms
    # has no first-class support for arbitrary JSON payloads.
    details = StringField(validators=[Optional(), Length(max=200000)])


class RejectionForm(FlaskForm):
    """Generic rejection-with-reason POST (used by admin qualification reject)."""

    rejection_reason = TextAreaField(validators=[Optional(), Length(max=5000)])
