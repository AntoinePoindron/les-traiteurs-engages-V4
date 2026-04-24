# Spec — Justesse monétaire et numérotation de facture

## Objectif

Éliminer deux bugs latents qui finiront par mordre :

1. **`float` pour des montants en euros** → arrondis silencieux, écarts d'un centime entre commande / facture / commission.
2. **Numérotation `max(invoice_number) + 1`** → race condition. En France, la numérotation des factures doit être strictement séquentielle, sans trou ni doublon (CGI art. 289 et BOI-TVA-DECLA-30-20-20). Deux livraisons simultanées font sauter cette garantie.

## Surface

### Colonnes affectées (toutes en `Numeric(...)` côté DB, donc le schéma reste — c'est le typage Python qui change)

`models.py` :
- `Company.budget_annual: float | None` → `Decimal | None`
- `CompanyService.annual_budget: float | None` → `Decimal | None`
- `QuoteRequest.budget_global: float | None` → `Decimal | None`
- `QuoteRequest.budget_per_person: float | None` → `Decimal | None`
- `Quote.total_amount_ht: float | None` → `Decimal | None`
- `Quote.amount_per_person: float | None` → `Decimal | None`
- `Quote.valorisable_agefiph: float | None` → `Decimal | None`
- `Caterer.commission_rate: float` → `Decimal`
- `Invoice.amount_ht: float` → `Decimal`
- `Invoice.tva_rate: float` → `Decimal`
- `Invoice.amount_ttc: float` → `Decimal`
- `Invoice.valorisable_agefiph: float | None` → `Decimal | None`
- `CommissionInvoice.amount_ht: float` → `Decimal`
- `CommissionInvoice.tva_rate: float` → `Decimal`
- `CommissionInvoice.amount_ttc: float` → `Decimal`

Les colonnes `Payment.amount_*_cents: int | None` restent `int` — elles sont déjà en cents (entiers), pas d'enjeu de précision.

### Calculs affectés (passage à arithmétique Decimal)

- `services/quotes.py`:`calculate_quote_totals` — somme + multiplication ligne par ligne, calcul TVA, fee plateforme.
- `services/stripe_service.py`:`create_invoice_for_order` — conversion en cents pour Stripe (`int(amount * 100)` → `int(amount * Decimal("100"))`), calcul `avg_tva_rate`.

### Numérotation de facture

`CommissionInvoice.invoice_number: int` :
- **Avant** : `max_num = session.scalar(select(func.max(CommissionInvoice.invoice_number))) or 0` puis `max_num + 1, max_num + 2`.
- **Après** : colonne avec `Sequence("commission_invoice_number_seq")`, `unique=True`. Postgres garantit l'unicité et l'incrément monotone même en concurrence.

## Plan de migration

### Côté code

Aucune migration de données nécessaire pour le typage Decimal — `Numeric` SQLAlchemy retourne déjà du `Decimal` à la lecture, le `float` du type-hint n'était qu'un mensonge. Le risque de précision vient des `float(...)` casts dans les calculs ; en les supprimant on récupère la justesse.

### Côté DB (migration Alembic)

Une seule migration :
- `CREATE SEQUENCE commission_invoice_number_seq`
- Initialiser à `MAX(invoice_number) + 1` pour ne pas réutiliser un numéro existant
- `ALTER TABLE commission_invoices ALTER COLUMN invoice_number SET DEFAULT nextval('commission_invoice_number_seq')`
- `ADD CONSTRAINT commission_invoices_invoice_number_key UNIQUE (invoice_number)`

Côté ORM, `CommissionInvoice.invoice_number = mapped_column(Integer, Sequence("commission_invoice_number_seq"), unique=True)`. Le code applicatif **n'assigne plus** `invoice_number=...` lors de la création — Postgres le calcule via `DEFAULT nextval(...)`.

## Compatibilité descendante

- Aucune rupture API.
- Templates : `{{ "%.2f" | format(amount) }}` fonctionne identiquement avec `Decimal` ou `float`. Aucun changement.
- JSON serialization (`Quote.details`) : les nombres restent stockés comme `float` dans le JSON blob (c'est du calcul intermédiaire, pas un montant fiscal). À voir plus tard si on veut tout migrer.

## Hors périmètre

- Migration de la TVA en `Decimal` également côté JSON `details` — peut être fait plus tard.
- Refactor du calcul TVA pour gérer plusieurs taux par devis sans le défaut silencieux à 10% (smell archi 2.2 partie 1) — préférable dans une PR séparée.
- Ajout d'index sur les colonnes financières fréquemment requêtées — séparé.

## Critères d'acceptation

- ✅ Tous les `float(...)` casts dans `services/quotes.py` et `services/stripe_service.py` sont supprimés.
- ✅ `models.py` ne mentionne plus `float` que pour les coordonnées géographiques (`latitude`, `longitude`) et le hint de `event_latitude/longitude`.
- ✅ Le `CommissionInvoice.invoice_number` est généré par Postgres, pas par le code Python.
- ✅ La migration Alembic seed la séquence à la valeur courante + 1 si des données existent déjà.
- ✅ L'app démarre, alembic upgrade head passe, login + dashboard fonctionnent.
- ✅ Une simulation de création de commission invoice depuis deux sessions parallèles produit des numéros distincts (smoke test ad-hoc).
