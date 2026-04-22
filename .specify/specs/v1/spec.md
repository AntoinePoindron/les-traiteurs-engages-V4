# Les Traiteurs Engagés

Marketplace B2B mettant en relation des entreprises avec des traiteurs inclusifs (ESAT, EA, EI, ACI) — structures employant des personnes en situation de handicap ou en parcours d'insertion. L'app aide les entreprises à remplir leurs obligations OETH/AGEFIPH en commandant auprès de ces structures.

## User Stories

### Inscription & Authentification
- En tant que visiteur, je veux créer un compte entreprise (client) ou traiteur pour accéder à la plateforme.
- En tant que client, je veux rejoindre mon entreprise via son SIRET — si elle existe déjà, je demande à rejoindre l'équipe ; sinon, je deviens admin.
- En tant que traiteur, je veux m'inscrire avec mes informations ESAT/EA/EI/ACI et attendre la validation d'un super_admin.
- En tant que client_admin, je veux approuver ou refuser les demandes d'adhésion de mes collaborateurs.

### Demande de devis (wizard 7 étapes)
- En tant que client, je veux créer une demande de devis en renseignant : type de prestation, détails de l'événement, régimes alimentaires, boissons, services complémentaires, budget, et un message optionnel.
- En tant que client, je veux envoyer ma demande directement à un traiteur spécifique ou en mode « comparer 3 devis ».
- En tant que super_admin, je veux qualifier les demandes en mode comparaison et lancer le matching automatique avec les traiteurs compatibles.

### Devis & Commandes
- En tant que traiteur, je veux recevoir les demandes qui correspondent à mes capacités (zone géographique, régimes, capacité, type de prestation).
- En tant que traiteur, je veux construire un devis ligne par ligne (prestations, boissons, extras) avec calcul automatique des sous-totaux par taux de TVA.
- En tant que client, je veux comparer les devis reçus et en accepter un (ce qui crée la commande).
- En tant que traiteur, je veux suivre l'avancement de mes commandes (confirmée → livrée → facturée → payée).

### Paiements (Stripe Connect)
- En tant que traiteur, je veux onboarder mon compte Stripe Connect pour recevoir des paiements.
- En tant que client, je veux payer une commande par carte ou virement SEPA via une facture Stripe.
- En tant que plateforme, je veux prélever une commission de 5% sur chaque transaction.

### Messagerie
- En tant qu'utilisateur, je veux échanger des messages avec les autres parties (client ↔ traiteur, avec le super_admin).

### Administration
- En tant que super_admin, je veux valider les traiteurs, gérer les entreprises, voir les statistiques et suivre les paiements.
- En tant que client_admin, je veux gérer mon équipe (employés, services/départements).

### Profil traiteur
- En tant que traiteur, je veux gérer mon profil public (description, spécialités, photos, rayon de livraison, capacité, régimes alimentaires proposés).

## Functional Requirements

### FR1 — Authentification & Rôles
- 4 rôles : `client_admin`, `client_user`, `caterer`, `super_admin`
- Inscription avec email/mot de passe
- Détection SIRET à l'inscription (entreprise existante → adhésion, nouvelle → admin auto)
- Système de membership (pending/active/rejected) pour les client_user
- Middleware de routage par rôle (chaque rôle a son dashboard)

### FR2 — Gestion des entreprises
- CRUD entreprise (nom, SIRET, adresse, éligibilité OETH, budget annuel, logo)
- Gestion des services/départements au sein de l'entreprise
- Gestion des employés (répertoire)
- Premier utilisateur = client_admin, les suivants rejoignent en pending

### FR3 — Gestion des traiteurs
- Inscription avec type de structure (ESAT, EA, EI, ACI)
- Profil complet : description, spécialités, photos, capacité min/max, rayon de livraison (km)
- Configuration par type de prestation (service_config JSONB)
- Drapeaux alimentaires (végétarien, vegan, halal, casher, sans gluten, bio)
- Validation par super_admin requise avant visibilité publique

### FR4 — Wizard de demande de devis (7 étapes)
1. Type de service (petit-déjeuner, pause gourmande, plateaux repas, cocktail) + journée complète
2. Détails événement (date, horaires, adresse géocodée, nombre de convives)
3. Régimes alimentaires (drapeaux + comptages)
4. Boissons (eau, soft, alcool, boissons chaudes)
5. Services complémentaires (service en salle, matériel, décoration, installation)
6. Budget (global ou par personne, sync automatique, flexibilité)
7. Récapitulatif + message optionnel → soumission

Deux modes : direct (1 traiteur ciblé) et comparaison (matching automatique).

### FR5 — Matching géographique des traiteurs
- Fonction haversine pour calcul de distance
- Filtrage : service_config actif, capacité min/max, régimes couverts, rayon de livraison
- Tri par proximité puis alphabétique

### FR6 — Règle des 3 premiers répondants
- En mode comparaison, les traiteurs répondent dans l'ordre
- Les 3 premiers devis sont transmis au client automatiquement
- Au 3e devis transmis, les traiteurs restants sont fermés automatiquement

### FR7 — Éditeur de devis
- Lignes détaillées (label, quantité, prix unitaire HT, taux TVA)
- 3 sections : prestations, boissons, extras
- Sous-totaux par tranche de TVA (5.5%, 10%, 20%)
- Prix par personne calculé automatiquement
- Référence auto-générée (DEVIS-YYYY-NNN)
- Brouillon ou envoi

### FR8 — Commandes
- Créée à l'acceptation d'un devis
- Statuts : confirmée → en cours → livrée → facturée → payée → litige
- Suivi côté client et traiteur

### FR9 — Paiements Stripe Connect
- Onboarding traiteur via Stripe Connect V2 (express)
- Facture Stripe après livraison (ligne par taux TVA + commission plateforme)
- Modes de paiement : carte + virement SEPA
- Webhook Stripe pour traitement asynchrone (checkout, invoice, payment_intent)
- Commission 5% côté traiteur + 5% ajouté à la facture client
- Table payments avec montants en centimes, idempotence

### FR10 — Facturation
- Factures traiteur (invoices) — numéro fourni par le traiteur
- Factures commission plateforme (commission_invoices) — numéro séquentiel auto
- Montant valorisable AGEFIPH affiché

### FR11 — Messagerie
- Threads par paire d'utilisateurs
- Lié à une commande ou une demande de devis
- Marquage lu/non-lu

### FR12 — Notifications
- Notifications internes (type, titre, corps, lu/non-lu)
- Liées à une entité (commande, demande, devis)

### FR13 — Dashboard admin
- KPIs : nombre de demandes, devis, commandes, CA
- Gestion traiteurs (validation)
- Gestion entreprises
- Suivi paiements
- Qualification des demandes en mode comparaison

### FR14 — Recherche de traiteurs
- Annuaire des traiteurs validés
- Filtrage par spécialité, localisation, capacité
- Fiche traiteur publique avec envoi de demande directe

## Non-Functional Requirements

### NFR1 — Stack technique
- Backend : Python (Flask ou FastAPI) + SQLAlchemy 2.0 + PostgreSQL
- Frontend : HTML/CSS/JS avec templates Jinja2 ou pages statiques
- Design : Tailwind CSS 4 avec palette warm du repo source (cream #FAF7F2, terracotta #C4714A, coral-red #FF5455, olive #6B7C4A, navy #1A3A52), polices Fraunces (titres) + Marianne (corps), icônes Lucide (SVG inline)
- Déploiement : Docker (Dockerfile + docker-compose.yml)
- HTTP : httpx uniquement (pas de requests)

### NFR2 — Sécurité
- Authentification par sessions (cookies sécurisés)
- Autorisation par rôle sur chaque endpoint
- Pas de SQL dynamique — paramètres nommés uniquement
- Validation SIRET côté serveur
- Webhook Stripe vérifié par signature HMAC

### NFR3 — Performance
- Pages principales < 2s
- Matching géographique en SQL (haversine)
- Pagination sur les listes

### NFR4 — Géocodage
- API Nominatim (gratuite) pour convertir adresses → lat/lng
- Pas de clé API requise

### NFR5 — LLM
- Pas d'utilisation de LLM prévue dans le MVP. Le skill expert_llm peut être ajouté plus tard pour des fonctionnalités comme la suggestion de menus ou l'aide à la rédaction de devis.

## Acceptance Checklist

### Inscription
- [ ] Un visiteur peut créer un compte client (avec SIRET)
- [ ] Un visiteur peut créer un compte traiteur
- [ ] La détection SIRET fonctionne (entreprise existante → adhésion)
- [ ] Un client_admin peut approuver/refuser les demandes d'adhésion
- [ ] Un super_admin peut valider un traiteur

### Demande de devis
- [ ] Le wizard 7 étapes fonctionne de bout en bout
- [ ] Le mode direct envoie à un traiteur spécifique
- [ ] Le mode comparaison passe par la qualification admin
- [ ] Le matching géographique sélectionne les bons traiteurs
- [ ] La règle des 3 premiers répondants ferme les traiteurs restants

### Devis & Commandes
- [ ] Un traiteur peut construire un devis ligne par ligne
- [ ] Les sous-totaux par TVA sont corrects
- [ ] L'acceptation d'un devis crée une commande
- [ ] Le flux de statuts commande fonctionne

### Paiements
- [ ] L'onboarding Stripe Connect fonctionne
- [ ] La génération de facture Stripe est correcte (lignes, TVA, commission)
- [ ] Le webhook met à jour les paiements
- [ ] Les montants en centimes sont cohérents

### Messagerie & Notifications
- [ ] Les messages s'échangent entre utilisateurs
- [ ] Les notifications apparaissent au bon moment

### Admin
- [ ] Le dashboard affiche les KPIs
- [ ] La qualification des demandes fonctionne
- [ ] La gestion des traiteurs/entreprises est opérationnelle
