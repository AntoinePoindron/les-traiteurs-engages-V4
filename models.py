import datetime
import uuid
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    Sequence,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Strictly sequential, no gaps, no duplicates — required by French
# tax law for commission invoice numbering. Postgres SEQUENCE owns it.
commission_invoice_seq = Sequence("commission_invoice_number_seq", start=1)


class Base(DeclarativeBase):
    pass


# --- Enums ---


class UserRole(str, Enum):
    client_admin = "client_admin"
    client_user = "client_user"
    caterer = "caterer"
    super_admin = "super_admin"


class MembershipStatus(str, Enum):
    pending = "pending"
    active = "active"
    rejected = "rejected"


class CatererStructureType(str, Enum):
    ESAT = "ESAT"
    EA = "EA"
    EI = "EI"
    ACI = "ACI"


class QuoteRequestStatus(str, Enum):
    draft = "draft"
    pending_review = "pending_review"
    approved = "approved"
    sent_to_caterers = "sent_to_caterers"
    completed = "completed"
    cancelled = "cancelled"
    quotes_refused = "quotes_refused"


class QRCStatus(str, Enum):
    selected = "selected"
    responded = "responded"
    transmitted_to_client = "transmitted_to_client"
    rejected = "rejected"
    closed = "closed"


class QuoteStatus(str, Enum):
    draft = "draft"
    sent = "sent"
    accepted = "accepted"
    refused = "refused"
    expired = "expired"


class OrderStatus(str, Enum):
    confirmed = "confirmed"
    delivered = "delivered"
    # Phase 1 done, phase 2 (Stripe API) enqueued in dramatiq.
    # Worker promotes to `invoiced` on success or leaves in `invoicing` on
    # failure so the retry CLI can pick it up. (P3.4)
    invoicing = "invoicing"
    invoiced = "invoiced"
    paid = "paid"
    disputed = "disputed"


class MealType(str, Enum):
    dejeuner = "dejeuner"
    diner = "diner"
    cocktail = "cocktail"
    petit_dejeuner = "petit_dejeuner"
    autre = "autre"


MEAL_TYPE_LABELS: dict[MealType, str] = {
    MealType.petit_dejeuner: "Petit-déjeuner",
    MealType.dejeuner: "Déjeuner",
    MealType.diner: "Dîner",
    MealType.cocktail: "Cocktail",
    MealType.autre: "Autre",
}


class PaymentStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"
    canceled = "canceled"


# --- Models ---


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    siret: Mapped[str] = mapped_column(String(14), unique=True)
    address: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(255))
    zip_code: Mapped[str | None] = mapped_column(String(10))
    oeth_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    budget_annual: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="company")
    services: Mapped[list["CompanyService"]] = relationship(back_populates="company")
    employees: Mapped[list["CompanyEmployee"]] = relationship(back_populates="company")
    quote_requests: Mapped[list["QuoteRequest"]] = relationship(back_populates="company")


class Caterer(Base):
    __tablename__ = "caterers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    siret: Mapped[str] = mapped_column(String(14))
    structure_type: Mapped[CatererStructureType] = mapped_column(String(10))
    address: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(255))
    zip_code: Mapped[str | None] = mapped_column(String(10))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text)
    specialties: Mapped[list | None] = mapped_column(JSON)
    photos: Mapped[list | None] = mapped_column(JSON)
    capacity_min: Mapped[int | None] = mapped_column(Integer)
    capacity_max: Mapped[int | None] = mapped_column(Integer)
    is_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.05"))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    delivery_radius_km: Mapped[int | None] = mapped_column(Integer)
    dietary_vegetarian: Mapped[bool] = mapped_column(Boolean, default=False)
    dietary_vegan: Mapped[bool] = mapped_column(Boolean, default=False)
    dietary_halal: Mapped[bool] = mapped_column(Boolean, default=False)
    dietary_casher: Mapped[bool] = mapped_column(Boolean, default=False)
    dietary_gluten_free: Mapped[bool] = mapped_column(Boolean, default=False)
    dietary_lactose_free: Mapped[bool] = mapped_column(Boolean, default=False)
    service_config: Mapped[dict | None] = mapped_column(JSON)
    stripe_account_id: Mapped[str | None] = mapped_column(String(255))
    stripe_onboarded_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    stripe_charges_enabled: Mapped[bool | None] = mapped_column(Boolean)
    stripe_payouts_enabled: Mapped[bool | None] = mapped_column(Boolean)
    invoice_prefix: Mapped[str | None] = mapped_column(String(10), unique=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="caterer")
    quote_request_caterers: Mapped[list["QuoteRequestCaterer"]] = relationship(back_populates="caterer")
    quotes: Mapped[list["Quote"]] = relationship(back_populates="caterer")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="caterer")
    payments: Mapped[list["Payment"]] = relationship(back_populates="caterer")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(255))
    last_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(String(20))
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("companies.id"))
    caterer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("caterers.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    membership_status: Mapped[MembershipStatus | None] = mapped_column(String(20))
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    company: Mapped[Company | None] = relationship(back_populates="users")
    caterer: Mapped[Caterer | None] = relationship(back_populates="users")
    quote_requests: Mapped[list["QuoteRequest"]] = relationship(back_populates="user")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user")
    sent_messages: Mapped[list["Message"]] = relationship(foreign_keys="Message.sender_id", back_populates="sender")
    received_messages: Mapped[list["Message"]] = relationship(foreign_keys="Message.recipient_id", back_populates="recipient")


class CompanyService(Base):
    __tablename__ = "company_services"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    annual_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    company: Mapped[Company] = relationship(back_populates="services")
    employees: Mapped[list["CompanyEmployee"]] = relationship(back_populates="service")
    quote_requests: Mapped[list["QuoteRequest"]] = relationship(back_populates="company_service")


class CompanyEmployee(Base):
    __tablename__ = "company_employees"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"))
    service_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("company_services.id"))
    first_name: Mapped[str] = mapped_column(String(255))
    last_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    position: Mapped[str | None] = mapped_column(String(255))
    invited_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))

    company: Mapped[Company] = relationship(back_populates="employees")
    service: Mapped[CompanyService | None] = relationship(back_populates="employees")
    user: Mapped[User | None] = relationship()


class QuoteRequest(Base):
    __tablename__ = "quote_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    company_service_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("company_services.id"))
    status: Mapped[QuoteRequestStatus] = mapped_column(String(30), default=QuoteRequestStatus.draft)
    service_type: Mapped[str | None] = mapped_column(String(100))
    meal_type: Mapped[MealType | None] = mapped_column(String(20))
    event_date: Mapped[datetime.date | None] = mapped_column(Date)
    guest_count: Mapped[int | None] = mapped_column(Integer)
    event_address: Mapped[str | None] = mapped_column(String(500))
    event_city: Mapped[str | None] = mapped_column(String(255))
    event_zip_code: Mapped[str | None] = mapped_column(String(10))
    event_latitude: Mapped[float | None] = mapped_column(Float)
    event_longitude: Mapped[float | None] = mapped_column(Float)
    budget_global: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    budget_per_person: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    dietary_vegetarian: Mapped[bool] = mapped_column(Boolean, default=False)
    dietary_vegan: Mapped[bool] = mapped_column(Boolean, default=False)
    dietary_halal: Mapped[bool] = mapped_column(Boolean, default=False)
    dietary_casher: Mapped[bool] = mapped_column(Boolean, default=False)
    dietary_gluten_free: Mapped[bool] = mapped_column(Boolean, default=False)
    dietary_lactose_free: Mapped[bool] = mapped_column(Boolean, default=False)
    vegetarian_count: Mapped[int | None] = mapped_column(Integer)
    vegan_count: Mapped[int | None] = mapped_column(Integer)
    halal_count: Mapped[int | None] = mapped_column(Integer)
    casher_count: Mapped[int | None] = mapped_column(Integer)
    gluten_free_count: Mapped[int | None] = mapped_column(Integer)
    lactose_free_count: Mapped[int | None] = mapped_column(Integer)
    drinks_alcohol: Mapped[bool] = mapped_column(Boolean, default=False)
    drinks_details: Mapped[str | None] = mapped_column(Text)
    wants_waitstaff: Mapped[bool] = mapped_column(Boolean, default=False)
    service_waitstaff_details: Mapped[str | None] = mapped_column(Text)
    wants_equipment: Mapped[bool] = mapped_column(Boolean, default=False)
    wants_decoration: Mapped[bool] = mapped_column(Boolean, default=False)
    wants_setup: Mapped[bool] = mapped_column(Boolean, default=False)
    wants_cleanup: Mapped[bool] = mapped_column(Boolean, default=False)
    is_compare_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    message_to_caterer: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    company: Mapped[Company] = relationship(back_populates="quote_requests")
    user: Mapped[User] = relationship(back_populates="quote_requests")
    company_service: Mapped[CompanyService | None] = relationship(back_populates="quote_requests")
    caterers: Mapped[list["QuoteRequestCaterer"]] = relationship(back_populates="quote_request")
    quotes: Mapped[list["Quote"]] = relationship(back_populates="quote_request")
    messages: Mapped[list["Message"]] = relationship(back_populates="quote_request")


class QuoteRequestCaterer(Base):
    __tablename__ = "quote_request_caterers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    quote_request_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("quote_requests.id"))
    caterer_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("caterers.id"))
    status: Mapped[QRCStatus] = mapped_column(String(30), default=QRCStatus.selected)
    responded_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    response_rank: Mapped[int | None] = mapped_column(Integer)

    quote_request: Mapped[QuoteRequest] = relationship(back_populates="caterers")
    caterer: Mapped[Caterer] = relationship(back_populates="quote_request_caterers")


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    quote_request_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("quote_requests.id"))
    caterer_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("caterers.id"))
    reference: Mapped[str] = mapped_column(String(50), unique=True)
    total_amount_ht: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    amount_per_person: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    valorisable_agefiph: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    valid_until: Mapped[datetime.date | None] = mapped_column(Date)
    status: Mapped[QuoteStatus] = mapped_column(String(20), default=QuoteStatus.draft)
    refusal_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    quote_request: Mapped[QuoteRequest] = relationship(back_populates="quotes")
    caterer: Mapped[Caterer] = relationship(back_populates="quotes")
    order: Mapped["Order | None"] = relationship(back_populates="quote")
    lines: Mapped[list["QuoteLine"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", order_by="QuoteLine.position"
    )


class QuoteLine(Base):
    __tablename__ = "quote_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    quote_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("quotes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    section: Mapped[str] = mapped_column(String(50), default="principal")
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))
    unit_price_ht: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    tva_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("10"))

    quote: Mapped[Quote] = relationship(back_populates="lines")

    def as_dict(self) -> dict:
        return {
            "section": self.section,
            "description": self.description or "",
            "quantity": float(self.quantity),
            "unit_price_ht": float(self.unit_price_ht),
            "tva_rate": float(self.tva_rate),
        }


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    quote_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("quotes.id"), unique=True)
    client_admin_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    status: Mapped[OrderStatus] = mapped_column(String(20), default=OrderStatus.confirmed)
    delivery_date: Mapped[datetime.date | None] = mapped_column(Date)
    delivery_address: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(255))
    stripe_hosted_invoice_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    quote: Mapped[Quote] = relationship(back_populates="order")
    client_admin: Mapped[User] = relationship()
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="order")
    commission_invoices: Mapped[list["CommissionInvoice"]] = relationship(back_populates="order")
    payments: Mapped[list["Payment"]] = relationship(back_populates="order")
    messages: Mapped[list["Message"]] = relationship(back_populates="order")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id"))
    caterer_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("caterers.id"))
    reference: Mapped[str | None] = mapped_column(String(50))
    amount_ht: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tva_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    amount_ttc: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    valorisable_agefiph: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    esat_mention: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    order: Mapped[Order] = relationship(back_populates="invoices")
    caterer: Mapped[Caterer] = relationship(back_populates="invoices")


class CommissionInvoice(Base):
    __tablename__ = "commission_invoices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Numbered by Postgres sequence — strictly monotonic, unique, no gaps.
    # French fiscal compliance: callers do NOT pass invoice_number explicitly.
    invoice_number: Mapped[int] = mapped_column(
        Integer, commission_invoice_seq, server_default=commission_invoice_seq.next_value(), unique=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id"))
    party: Mapped[str] = mapped_column(String(20))
    amount_ht: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tva_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.20"))
    amount_ttc: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    order: Mapped[Order] = relationship(back_populates="commission_invoices")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id"))
    caterer_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("caterers.id"))
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(255))
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255))
    # UNIQUE: a single Stripe invoice maps to exactly one Payment row.
    # Without this, a race on POST /caterer/orders/<id>/deliver can create
    # duplicate Payment rows pointing at the same invoice, of which the
    # webhook updates only one. Audit finding #6 (2026-04-24).
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    stripe_charge_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[PaymentStatus] = mapped_column(String(20), default=PaymentStatus.pending)
    amount_total_cents: Mapped[int | None] = mapped_column(Integer)
    application_fee_cents: Mapped[int | None] = mapped_column(Integer)
    amount_to_caterer_cents: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    order: Mapped[Order] = relationship(back_populates="payments")
    caterer: Mapped[Caterer] = relationship(back_populates="payments")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    related_entity_type: Mapped[str | None] = mapped_column(String(50))
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="notifications")


class AuditLog(Base):
    """Append-only journal of sensitive admin actions.

    Written by services.audit.log_admin_action(). Never modified or deleted
    by application code — that's the whole point. Operationally, the table
    can be archived (move rows older than N years to cold storage) but never
    edited in place.

    Captures who did what to which entity, when, with optional metadata
    (e.g. rejection reason, before/after snapshots) plus IP + user-agent
    for forensics. The actor's email is snapshotted alongside actor_id so
    that deleting a user does not erase the audit trail.

    Audit reference: P3 / "audit logging des actions admin sensibles".
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    actor_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(60), index=True)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    extra: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class StripeEvent(Base):
    """Deduplication table for Stripe webhook events.

    Primary key is Stripe's `event.id` (a string like `evt_...`). Inserting
    it inside the webhook handler gives us atomic deduplication: a UNIQUE
    violation means "already processed this event, ignore it". Closes audit
    finding #3 (2026-04-24): events can be replayed within the 300s signature
    tolerance window, and Stripe itself re-delivers on network failures.
    """

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    received_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    sender_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    recipient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("orders.id"))
    quote_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("quote_requests.id"))
    body: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    sender: Mapped[User] = relationship(foreign_keys=[sender_id], back_populates="sent_messages")
    recipient: Mapped[User] = relationship(foreign_keys=[recipient_id], back_populates="received_messages")
    order: Mapped[Order | None] = relationship(back_populates="messages")
    quote_request: Mapped[QuoteRequest | None] = relationship(back_populates="messages")
