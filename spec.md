# Les Traiteurs Engages — Specification

## Vision

Marketplace B2B mettant en relation des entreprises avec des traiteurs inclusifs (ESAT, EA, EI, ACI) pour leurs evenements. Les entreprises soumettent des demandes de devis, la plateforme qualifie et matche geographiquement les traiteurs, les 3 premiers repondants sont transmis au client qui choisit, commande, et paie via facturation Stripe B2B a 30 jours.

## Utilisateurs et roles

| Role | Description |
|---|---|
| `client_admin` | Admin entreprise — gere l'equipe, les services, cree des demandes, accepte les devis, paie |
| `client_user` | Employe — cree des demandes pour son entreprise |
| `caterer` | Traiteur ESAT/EA/EI/ACI — gere son profil, repond aux demandes, cree des devis, facture |
| `super_admin` | Admin plateforme — qualifie les demandes, valide les traiteurs, monitore paiements et stats |

## Exigences fonctionnelles

### F01 — Inscription et authentification

Inscription email/mot de passe avec 3 parcours :
- **client_admin** : cree une entreprise (SIRET, adresse, OETH) + devient admin
- **client_user** : rejoint une entreprise existante. Si invite par email → auto-lien + membership `active`. Sinon → membership `pending` en attente d'approbation admin
- **caterer** : cree une fiche traiteur avec SIRET, type de structure (ESAT/EA/EI/ACI), adresse. Generation auto d'un `invoice_prefix` unique (slug 5→8→10 chars→numerique)

Login avec redirection vers le dashboard du role. Middleware verifie l'auth sur toutes les routes non-publiques.

### F02 — Gestion d'equipe (client_admin)

- CRUD services internes (nom, description, budget annuel)
- CRUD employes (prenom, nom, email, poste, service)
- Invitation par email → statut "En attente de reponse"
- Approbation/rejet des demandes d'adhesion (`membership_status`: pending → active/rejected)
- L'admin est auto-ajoute comme employe dans un service "Direction" (backfill)

### F03 — Profil entreprise (client_admin)

- Edition nom, SIRET, adresse, ville, code postal
- Upload logo (stockage fichier)
- Eligibilite OETH (boolean)
- Budget annuel

### F04 — Profil traiteur (caterer)

- Informations generales : nom, SIRET, type de structure (enum ESAT/EA/EI/ACI), description, specialites
- Capacite min/max couverts
- Rayon de livraison (km) + adresse avec geocodage (lat/lng)
- Options alimentaires : vegetarien, vegan, halal, casher, sans gluten, sans lactose
- Configuration de services (JSONB) : quels types de prestations sont proposes
- Photos (tableau URLs)
- Commission rate (defaut 5%)

### F05 — Wizard de demande de devis (7 etapes)

1. **Type de service** : dejeuner, diner, cocktail, petit-dejeuner, autre
2. **Evenement** : date, nombre de convives, adresse + geocodage, type de repas
3. **Budget** : budget global ou par personne (sync bidirectionnel via trigger)
4. **Regimes alimentaires** : vegetarien, vegan, halal, casher, sans gluten, sans lactose + nombre de personnes par regime
5. **Boissons** : avec/sans alcool, details (softs, bieres, vins, champagne, quantites)
6. **Services additionnels** : vaisselle, nappes, decoration, service/personnel (+ details waitstaff), livraison, installation, nettoyage
7. **Recapitulatif** : relecture, message au traiteur, choix mode compare (plusieurs devis) ou direct, selection du service interne

Edition possible tant que le statut est pre-devis. Assignation au service interne pour suivi budgetaire.

### F06 — Qualification admin (mode compare)

- Liste des demandes en attente de qualification (`pending_review`)
- Visualisation complete de la demande
- Approbation → matching automatique :
  - Filtrage par distance (haversine SQL, rayon livraison du traiteur vs localisation evenement)
  - Filtrage par type de service (via service_config)
  - Filtrage par capacite (min/max)
  - Filtrage par regimes alimentaires
  - Tri par proximite
- Insertion des `quote_request_caterers` (statut `selected`)
- Passage de la demande en `sent_to_caterers`
- Rejet possible avec raison

### F07 — Regle des 3 premiers repondants

Quand un traiteur envoie un devis :
- Son statut QRC passe a `responded`
- Si c'est le 1er, 2e ou 3e repondant → transmis au client (`transmitted_to_client`)
- Quand 3 devis sont transmis → trigger `lock_out_remaining_caterers()` passe les `selected` restants en `closed`
- Le `response_rank` est enregistre

### F08 — Editeur de devis (caterer)

- Creation/edition de devis avec reference structuree `DEVIS-{prefix}-YYYY-NNN`
- Lignes de detail par section : principal, boissons, extras
- Chaque ligne : description, quantite, prix unitaire HT, taux TVA (5.5%, 10%, 20%)
- Calcul automatique : sous-totaux par section, total HT, TVA, TTC
- Montant par personne et montant valorisable AGEFIPH
- Notes et conditions
- Date de validite
- Statuts : draft → sent → accepted/refused/expired
- Preview modale complete avec detail des frais plateforme (5% HT + 20% TVA)

### F09 — Comparaison et choix de devis (client)

- Visualisation de 1 a 3 devis recus
- Detail complet de chaque devis (lignes, totaux, TVA, AGEFIPH)
- Acceptation d'un devis → creation automatique d'une commande
- Refus d'un devis avec raison obligatoire
- Si tous refuses → statut demande `quotes_refused`

### F10 — Commandes et livraison

Flux de statuts : `confirmed` → `delivered` → `invoiced` → `paid`
- Client voit ses commandes avec statut, date livraison, adresse
- Traiteur marque la commande comme livree → declenche la generation de facture Stripe
- Chaque commande a un lien vers la facture Stripe hebergee
- Contestation possible (statut `disputed`)

### F11 — Paiements Stripe (Invoice-first)

- **Onboarding traiteur** : creation compte Stripe Connect V2 (`/v2/core/accounts`), dashboard Express
- **Flux invoice-first** :
  1. Traiteur marque "livre"
  2. Generation facture Stripe : lignes du devis groupees par TVA + ligne "Frais de mise en relation" (5% HT + 20% TVA)
  3. Destination charges : `application_fee_amount` + `transfer_data.destination`
  4. Modes de paiement : carte + virement SEPA (customer_balance)
  5. Echeance : 30 jours (`days_until_due: 30`)
  6. Reference facture : `FAC-{prefix}-YYYY-NNN` (derivee du devis)
  7. Champs personnalises : nom traiteur, SIRET, adresse
- **Customer management** : creation/reutilisation de Stripe Customers par utilisateur
- **TaxRate** : objets Stripe crees et caches pour affichage TVA correct
- **Table payments** : tracking complet (session, payment_intent, invoice, charge, montants en centimes, statuts)
- **Webhooks** : `invoice.paid`, `invoice.payment_failed`, `checkout.session.completed`, capability updates

### F12 — Messagerie

- Threads par paire d'utilisateurs (expediteur/destinataire)
- Lie a une commande ou une demande de devis
- Lecture/envoi depuis les dashboards client et traiteur
- Admin peut voir tous les messages
- Statut lu/non-lu

### F13 — Notifications

- Notifications internes (titre, corps, type)
- Liees a une entite (commande, demande, devis)
- Statut lu/non-lu
- Compteur dans la sidebar

### F14 — Dashboard admin

- **KPIs** : demandes en attente, traiteurs en attente, entreprises actives, commandes du mois
- **Qualification** : liste et traitement des demandes en mode compare
- **Traiteurs** : liste, detail, validation/invalidation, commission, statut Stripe
- **Entreprises** : liste, detail, employes, services, demandes, commandes
- **Paiements** : monitoring complet avec references Stripe, statuts, montants
- **Statistiques** : revenus par mois, top traiteurs, taux conversion, repartition geographique, repartition par type de service
- **Messages** : vue globale de tous les threads

### F15 — Catalogue traiteurs (client)

- Recherche/filtrage des traiteurs valides
- Filtres : type de structure (STPA = ESAT+EA, SIAE = EI+ACI), regimes alimentaires, capacite, type de service
- Fiche traiteur detaillee : galerie photos, description, capacite, specialites, rayon livraison

### F16 — Landing page

- Page marketing publique
- Hero, etapes du parcours (animation), screenshots, statistiques
- CTA inscription

## Contraintes techniques

- Stack cible : Flask + SQLAlchemy 2.0 + PostgreSQL + Jinja2 + Tailwind CSS 4 + JS vanilla
- Design system : palette warm du repo source (cream #FAF7F2, terracotta #C4714A, coral-red #FF5455, olive #6B7C4A, navy #1A3A52), polices Fraunces (titres) + Marianne (corps), icones Lucide (SVG inline)
- Composants UI custom : StatusBadge (21 variantes), StructureTypeBadge, InfoChip, ConfirmDialog, BackButton, SubmitButton, ContactCard
- Paiements via Stripe API directement (httpx, pas de SDK)
- Geocodage via API Nominatim (OpenStreetMap)
- App deployee comme app interactive dans `/app/data/interactive/`
- Auth geree par l'app (sessions Flask ou JWT simple)
- Fichiers uploades stockes localement ou S3

## Modele de donnees (15+ tables)

| Table | Role |
|---|---|
| `companies` | Entreprises clientes |
| `caterers` | Traiteurs (ESAT/EA/EI/ACI) |
| `users` | Profils utilisateurs lies a auth |
| `quote_requests` | Demandes de devis (40+ colonnes) |
| `quote_request_caterers` | Pivot traiteurs/demandes (matching, statut, rang) |
| `quotes` | Devis (reference, montants, details JSONB) |
| `quote_details` | Lignes de devis (si non JSONB) |
| `orders` | Commandes |
| `invoices` | Factures traiteur (reference) |
| `commission_invoices` | Factures commission plateforme |
| `payments` | Tracking paiements Stripe |
| `notifications` | Notifications internes |
| `messages` | Messagerie |
| `company_services` | Services internes entreprise |
| `company_employees` | Employes entreprise |
