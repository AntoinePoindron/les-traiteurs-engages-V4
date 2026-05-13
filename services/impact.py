"""Aggregations pour le bloc « Impact social » du tableau de bord client.

On compte uniquement les commandes effectivement payées (`OrderStatus.paid`)
pour rester aligné avec la définition « achat réalisé » : tant qu'une
commande n'est pas réglée, son montant n'a pas encore quitté la
trésorerie de l'acheteur — il ne compte donc pas comme un achat
inclusif réalisé.

`Quote.total_amount_ht` ne contient que la prestation traiteur (somme
des lignes du devis). Les 5% de frais de mise en relation sont
calculés à part (`platform_fee_ht = total_ht × commission_rate`) et
facturés via un `CommissionInvoice` distinct lié à l'`Order` — ils
n'entrent donc **pas** dans le total impact affiché côté client. Si
un futur refactor déplace la commission dans `Quote.total_amount_ht`,
il faudra soustraire `Caterer.commission_rate × total_amount_ht` ici
pour conserver la sémantique « achat inclusif » du chiffre.

Le découpage SIAE / STPA suit la nomenclature des structures du
marché de l'inclusion :

* SIAE (Structures d'Insertion par l'Activité Économique) :
  EI (Entreprise d'Insertion) + ACI (Atelier Chantier d'Insertion).
* STPA (Secteur du Travail Protégé et Adapté) :
  ESAT (Établissement et Service d'Aide par le Travail) + EA
  (Entreprise Adaptée).

Le ratio « heures financées » reproduit la formule publiée par la
plateforme du marché de l'inclusion :

    https://lemarche.inclusion.gouv.fr/calculer-impact-social-achat-inclusif/

dont le code (open source, repo `gip-inclusion/le-marche`) calcule
`round(montant / 26)` pour des montants en dessous de 3 700€ (≈ 1
ETP-mois à ~3 700€). On garde le même ratio pour toutes les bornes —
le résultat reste exprimé en heures, ce qui est l'unité demandée
côté UI. La conversion en ETP-mois faite par la plateforme officielle
est un effet de présentation qu'on n'a pas besoin d'embarquer ici.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select

from models import (
    Caterer,
    CatererStructureType,
    Order,
    OrderStatus,
    Quote,
    QuoteRequest,
)

# Ratio €/heure utilisé par la plateforme officielle (cf. docstring).
# Exposé comme constante pour qu'un test puisse l'asserter — la valeur
# vient d'une source externe et un changement silencieux fausserait
# tous les chiffres affichés.
HOURS_FINANCED_DIVISOR_EUR: int = 26

SIAE_STRUCTURE_TYPES: frozenset[CatererStructureType] = frozenset(
    {CatererStructureType.EI, CatererStructureType.ACI}
)
STPA_STRUCTURE_TYPES: frozenset[CatererStructureType] = frozenset(
    {CatererStructureType.ESAT, CatererStructureType.EA}
)


@dataclass(frozen=True)
class SocialImpact:
    """Snapshot pré-calculé pour le bloc dashboard.

    Tous les montants sont des `Decimal` HT en euros. `hours_financed`
    est arrondi à l'unité — l'unité affichée est l'heure, pas le
    centième d'heure.
    """

    total_ht: Decimal
    siae_ht: Decimal
    stpa_ht: Decimal
    hours_financed: int


def compute_social_impact(
    db,
    *,
    company_id: uuid.UUID,
    requester_user_id: uuid.UUID | None = None,
) -> SocialImpact:
    """Agrège l'impact social pour une entreprise (et, optionnellement,
    pour un utilisateur précis de cette entreprise).

    `requester_user_id` reflète le scoping client_admin / client_user
    déjà appliqué ailleurs sur la dashboard : `None` côté admin
    (vue entreprise complète), `user.id` côté client_user (vue
    individuelle, restreinte aux QR créées par cet utilisateur). On le
    propage ici pour que les chiffres correspondent à ce que le bloc
    « budget consommé » affiche au même endroit — sinon un client_user
    verrait un total impact incohérent avec son propre KPI budget.
    """
    # Une seule requête par bucket : on aurait pu faire un GROUP BY
    # structure_type et reconstruire côté Python, mais avec 4 valeurs
    # d'enum stables et un découpage SIAE/STPA fixé, trois sommes
    # ciblées restent lisibles et évitent d'avoir à mapper le résultat.
    base_stmt = (
        select(func.coalesce(func.sum(Quote.total_amount_ht), 0))
        .select_from(Order)
        .join(Quote, Order.quote_id == Quote.id)
        .join(QuoteRequest, Quote.quote_request_id == QuoteRequest.id)
        .join(Caterer, Quote.caterer_id == Caterer.id)
        .where(
            Order.status == OrderStatus.paid,
            QuoteRequest.company_id == company_id,
        )
    )
    if requester_user_id is not None:
        base_stmt = base_stmt.where(QuoteRequest.user_id == requester_user_id)

    total_ht = Decimal(str(db.execute(base_stmt).scalar_one() or 0))

    siae_ht = Decimal(
        str(
            db.execute(
                base_stmt.where(Caterer.structure_type.in_(SIAE_STRUCTURE_TYPES))
            ).scalar_one()
            or 0
        )
    )
    stpa_ht = Decimal(
        str(
            db.execute(
                base_stmt.where(Caterer.structure_type.in_(STPA_STRUCTURE_TYPES))
            ).scalar_one()
            or 0
        )
    )

    # `int(total_ht)` tronque côté Decimal ; on veut un arrondi propre
    # à l'heure entière comme la plateforme officielle (round Python
    # par défaut suit banker's rounding, ce qui colle pour de l'affichage
    # statistique grossier).
    hours_financed = (
        int(round(total_ht / HOURS_FINANCED_DIVISOR_EUR)) if total_ht > 0 else 0
    )

    return SocialImpact(
        total_ht=total_ht,
        siae_ht=siae_ht,
        stpa_ht=stpa_ht,
        hours_financed=hours_financed,
    )
