# Tasks — Les Traiteurs Engagés

## Phase 1: Foundation

- [ ] Task 1: Créer le squelette du projet — `app.py` (factory Flask), `config.py` (env vars), `database.py` (engine SQLAlchemy), `requirements.txt`, `Dockerfile`, `docker-compose.yml`
- [ ] Task 2: Créer `models.py` — toutes les tables SQLAlchemy (users, companies, caterers, quote_requests, quotes, orders, payments, invoices, notifications, messages + enums) [P]
- [ ] Task 3: Créer le template de base Tailwind `templates/base.html` — sidebar role-aware, navigation, footer, messages flash, palette warm (cream/terracotta/navy), polices Fraunces/Marianne, Lucide icons, composants partials (StatusBadge, StructureTypeBadge, ConfirmDialog) [P]
- [ ] Task 4: Créer `blueprints/middleware.py` — décorateurs `login_required`, `role_required(role)`, helper `current_user`, gestion des sessions Flask

## Phase 2: Auth & Inscription

- [ ] Task 5: Créer `blueprints/auth.py` — routes login/logout/signup, formulaires d'inscription client (avec SIRET) et traiteur (depends on Tasks 1-4)
- [ ] Task 6: Créer les templates auth — `login.html`, `signup.html` avec choix client/traiteur, formulaire SIRET avec détection entreprise existante [P]
- [ ] Task 7: Logique inscription complète — détection SIRET (entreprise existante → adhésion pending, nouvelle → admin auto), création user + company/caterer, service "Direction" par défaut

## Phase 3: Dashboards & Navigation

- [ ] Task 8: Créer `blueprints/client.py` (squelette) — routes dashboard, profil, settings + templates de base
- [ ] Task 9: Créer `blueprints/caterer.py` (squelette) — routes dashboard, profil (édition), templates [P]
- [ ] Task 10: Créer `blueprints/admin.py` (squelette) — routes dashboard (KPIs basiques), gestion traiteurs (validation), gestion entreprises [P]
- [ ] Task 11: Navigation dynamique par rôle — sidebar/header avec liens adaptés au rôle, compteur notifications

## Phase 4: Gestion Équipe (Client)

- [ ] Task 12: Gestion équipe client_admin — liste des membres (pending/active/rejected), approbation/refus, gestion des services/départements, répertoire employés

## Phase 5: Profil Traiteur

- [ ] Task 13: Édition profil traiteur complet — description, spécialités, photos (upload), capacité, rayon de livraison, drapeaux alimentaires, configuration par type de prestation (service_config)

## Phase 6: Wizard Demande de Devis

- [ ] Task 14: Créer `static/js/wizard.js` — navigation multi-étapes côté client (afficher/cacher les sections, validation avant passage à l'étape suivante, progress bar)
- [ ] Task 15: Routes et templates wizard étapes 1-3 — type de service, détails événement (avec géocodage adresse via Nominatim), régimes alimentaires
- [ ] Task 16: Routes et templates wizard étapes 4-7 — boissons, services complémentaires, budget (sync global↔par personne), récapitulatif + soumission
- [ ] Task 17: Créer `services/geocoding.py` — proxy Nominatim pour géocodage adresse → lat/lng [P]
- [ ] Task 18: Mode direct vs comparaison — si traiteur ciblé → status `sent_to_caterers` direct ; si compare_mode → status `pending_review` en attente de qualification admin

## Phase 7: Matching & Qualification Admin

- [ ] Task 19: Créer `services/matching.py` — fonction haversine SQL, algorithme de matching (service_config, capacité, régimes, rayon géographique), tri par proximité
- [ ] Task 20: Qualification admin — page listing demandes `pending_review`, détail avec boutons approuver/rejeter, approbation lance le matching + crée les `quote_request_caterers` + notifie

## Phase 8: Devis

- [ ] Task 21: Créer `static/js/quote-editor.js` — éditeur de devis interactif (ajout/suppression lignes, calcul automatique sous-totaux par TVA, total HT, prix par personne)
- [ ] Task 22: Créer `services/quotes.py` — génération référence (DEVIS-YYYY-NNN), logique règle des 3 (response_rank, auto-transmission, auto-fermeture des restants)
- [ ] Task 23: Routes traiteur pour devis — voir demande, créer/éditer devis (brouillon ou envoi), template éditeur
- [ ] Task 24: Routes client pour devis — voir les devis reçus sur une demande, comparer, accepter (crée commande) ou refuser (avec raison)

## Phase 9: Commandes

- [ ] Task 25: Flux commandes complet — création à l'acceptation du devis, page listing et détail côté client et traiteur, mise à jour statut par le traiteur (confirmé → livré → facturé), page détail avec historique

## Phase 10: Paiements Stripe

- [ ] Task 26: Créer `services/stripe_service.py` — client Stripe via httpx (pas de SDK), fonctions : créer compte Connect, lien d'onboarding, créer facture, calculer commission
- [ ] Task 27: Onboarding traiteur Stripe — routes `/caterer/stripe/onboarding` et `/caterer/stripe/return`, suivi KYC
- [ ] Task 28: Génération facture Stripe — après livraison, créer facture avec lignes par TVA + commission plateforme, 30j de paiement, carte + SEPA
- [ ] Task 29: Webhook Stripe — `POST /api/webhooks/stripe` avec vérification HMAC, traitement events (invoice.paid, payment_intent, checkout.session), mise à jour table payments avec idempotence
- [ ] Task 30: Factures commission — génération automatique des `commission_invoices` (numéro séquentiel), affichage admin

## Phase 11: Messagerie & Notifications

- [ ] Task 31: Créer `services/notifications.py` — création de notifications aux bons moments (nouvelle demande, nouveau devis, devis accepté, commande livrée, etc.) [P]
- [ ] Task 32: Messagerie — `static/js/messages.js` pour chargement AJAX, routes API pour envoyer/lire messages, templates messagerie par rôle, threads par paire d'utilisateurs
- [ ] Task 33: API notifications — `GET /api/notifications` (non-lues), `POST /api/notifications/<id>/read`, affichage dans le header (badge)

## Phase 12: Recherche Traiteurs

- [ ] Task 34: Annuaire traiteurs publics — page recherche avec filtres (spécialité, localisation, capacité), fiches traiteurs, bouton "demander un devis" (crée demande en mode direct)

## Phase 13: Polish & Finitions

- [ ] Task 35: Responsive et UX — vérifier l'affichage mobile, améliorer les formulaires, ajouter les messages flash de confirmation/erreur partout
- [ ] Task 36: Dashboard admin complet — KPIs (nb demandes/devis/commandes/CA par période), graphiques basiques (barres), gestion paiements
- [ ] Task 37: Seed data — script de génération de données de test (2 entreprises, 3 traiteurs, demandes, devis, commandes à différents statuts)
- [ ] Task 38: Healthcheck et configuration production — route `/health`, configuration gunicorn, documentation déploiement
