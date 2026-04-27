"""payments.order_id UNIQUE

Revision ID: d5e8f1a2b3c4
Revises: c0ffee0fea7
Create Date: 2026-04-27

Au plus un `Payment` par `Order`. Cette contrainte sous-tend l'invariant
de la PR billing-two-phase : le `Payment` est créé *avant* l'appel Stripe
(phase 1, DB-only) et reflète l'intention de facturer cette commande.
S'il existait deux Payment pour le même Order, la phase 2 (envoi Stripe)
pourrait viser le mauvais ou créer deux factures Stripe pour une seule
commande.

Le cleanup défensif supprime d'anciennes Payment dupliquées sans
`stripe_invoice_id` (intentions abandonnées par retry HTTP avant le
durcissement) ; les Payment liées à une vraie facture Stripe sont
conservées prioritairement.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d5e8f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "c0ffee0fea7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Si plusieurs Payment partagent un order_id, garder celui qui a un
    # stripe_invoice_id non nul (s'il existe), supprimer les autres.
    op.execute(
        """
        DELETE FROM payments p1
        USING payments p2
        WHERE p1.order_id = p2.order_id
          AND p1.id <> p2.id
          AND p1.stripe_invoice_id IS NULL
          AND p2.stripe_invoice_id IS NOT NULL
        """
    )
    # Si plusieurs Payment partagent un order_id et qu'aucun n'a de
    # stripe_invoice_id, garder la plus ancienne (id le plus petit).
    op.execute(
        """
        DELETE FROM payments p1
        USING payments p2
        WHERE p1.order_id = p2.order_id
          AND p1.id > p2.id
          AND p1.stripe_invoice_id IS NULL
          AND p2.stripe_invoice_id IS NULL
        """
    )
    op.create_unique_constraint(
        "uq_payments_order_id",
        "payments",
        ["order_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_payments_order_id", "payments", type_="unique")
