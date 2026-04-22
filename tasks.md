# Les Traiteurs Engages — Taches

## Phase 1 — Foundation

- [ ] T01: Creer le squelette Flask (app.py, config.py, blueprints vides, base.html Tailwind avec sidebar warm)
- [ ] T02: Definir tous les modeles SQLAlchemy (15 tables + enums) dans models.py
- [ ] T03: Script init_db.py pour creer les tables (create_all) + seed super_admin
- [ ] T04: Templates de base Tailwind (base.html avec palette warm/Fraunces/Marianne/Lucide, login.html, composants partials : StatusBadge 21 variantes, StructureTypeBadge, InfoChip, ConfirmDialog, flash messages)

## Phase 2 — Auth

- [ ] T05: Systeme d'auth (inscription 3 parcours, login, logout, sessions, decorateurs role)
- [ ] T06: Middleware : redirect par role apres login, protection routes, membership pending
- [ ] T07: Page login + page signup avec formulaire dynamique selon role choisi

## Phase 3 — Client core

- [ ] T08: Dashboard client (demandes actives, commandes recentes, suivi budget)
- [ ] T09: Wizard demande de devis 7 etapes (templates + JS multi-step + POST creation)
- [ ] T10: Liste des demandes avec filtres par statut (tabs)
- [ ] T11: Detail demande : visualisation devis recus, acceptation/refus
- [ ] T12: Edition de demande existante (statuts pre-devis)

## Phase 4 — Caterer core

- [ ] T13: Dashboard traiteur (demandes en attente, commandes a venir, stats revenus)
- [ ] T14: Formulaire profil traiteur complet (infos, dietary, services, photos, rayon livraison)
- [ ] T15: Liste des demandes recues avec filtres
- [ ] T16: Detail demande + creation/edition devis (editeur ligne par ligne JS)
- [ ] T17: Preview devis modale (totaux, TVA, frais plateforme, AGEFIPH)
- [ ] T18: Envoi devis (changement statut, trigger regle 3 repondants)

## Phase 5 — Matching et qualification

- [ ] T19: Service matching.py (haversine, filtres service/capacite/dietary, tri proximite)
- [ ] T20: Service geocoding.py (Nominatim via httpx, utilise a la creation demande + profil traiteur)
- [ ] T21: Admin qualification : liste pending, detail, approbation avec matching auto, rejet
- [ ] T22: Logique 3 premiers repondants (application-level : update QRC status + rang, lockout des restants)

## Phase 6 — Commandes

- [ ] T23: Creation commande depuis acceptation devis (client)
- [ ] T24: Liste et detail commandes (client + caterer)
- [ ] T25: Traiteur marque "livre" → passage statut delivered
- [ ] T26: Vue facture (client + caterer)

## Phase 7 — Stripe

- [ ] T27: stripe_service.py : onboarding Connect V2 (creation compte, lien dashboard, callback)
- [ ] T28: Pages Stripe caterer (statut onboarding, bouton demarrer, page complete)
- [ ] T29: Generation facture Stripe a la livraison (lignes groupees TVA + frais plateforme, destination charges, 30j)
- [ ] T30: Customer management (get_or_create Stripe Customer par user)
- [ ] T31: TaxRate cache Stripe
- [ ] T32: Webhook handler (/api/webhooks/stripe) : invoice.paid, invoice.payment_failed, capability updates
- [ ] T33: Table payments : tracking complet, refresh statut depuis Stripe

## Phase 8 — Messagerie et notifications

- [ ] T34: Messagerie : envoi/lecture messages, threads par paire, lie a commande/demande
- [ ] T35: Templates messagerie (layout client, caterer, admin)
- [ ] T36: Notifications : creation automatique aux changements de statut, compteur sidebar, marquer lu

## Phase 9 — Gestion equipe

- [ ] T37: CRUD services internes (company_services)
- [ ] T38: CRUD employes (company_employees) + invitation email
- [ ] T39: Auto-link employes invites a l'inscription + approbation membership
- [ ] T40: Backfill admin dans service "Direction"

## Phase 10 — Admin complet

- [ ] T41: Dashboard admin KPIs (demandes en attente, traiteurs en attente, entreprises, commandes mois)
- [ ] T42: Gestion traiteurs (liste, detail, validation/invalidation, commission, statut Stripe)
- [ ] T43: Gestion entreprises (liste, detail, employes, services, demandes, commandes)
- [ ] T44: Monitoring paiements (table Stripe avec statuts, montants, references)
- [ ] T45: Page statistiques (revenus/mois, top traiteurs, taux conversion, geo, service types)
- [ ] T46: Vue messages admin (tous les threads)

## Phase 11 — Catalogue et recherche

- [ ] T47: Catalogue traiteurs client : liste avec filtres (structure STPA/SIAE, dietary, capacite, service)
- [ ] T48: Fiche traiteur detaillee (galerie photos, description, capacites, specialites)

## Phase 12 — Landing page

- [ ] T49: Landing page publique (hero, etapes parcours, stats, CTA inscription)

## Phase 13 — References et finalisation

- [ ] T50: Systeme references devis/factures (slugs.py + quotes.py : DEVIS-/FAC-{prefix}-YYYY-NNN)
- [ ] T51: Upload fichiers (logo entreprise, photos traiteur) avec stockage local
- [ ] T52: Seed data realiste (entreprises, traiteurs, demandes, devis, commandes a differents statuts)
- [ ] T53: Tests de bout en bout manuels sur les 4 parcours
- [ ] T54: Healthcheck endpoint + README deploiement
