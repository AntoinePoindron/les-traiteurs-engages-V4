# Règles front-end

Référence opérationnelle pour le HTML/CSS/JS de ce dépôt. À ouvrir avant
tout travail front, et à respecter avant de pousser une PR.

Hiérarchie : Tailwind utilities (en classes) → utilitaires de marque
définies dans `app.css` → macros Jinja dans `templates/components/ui.html`.
Pas de balises `<style>` inline. Pas de `style="…"` inline (sauf cas
explicitement listés ci-dessous).

---

## 1. Source unique de vérité

- **Tokens de marque** : `:root { --c-… }` dans `static/css/app.css`. C'est
  là que toute nouvelle couleur, dimension de layout, ou variable de type
  est ajoutée *en premier*. Avant d'introduire un token, vérifier qu'un
  existant ne couvre pas le besoin (palette `--c-coral / --c-navy /
  --c-cream / --c-text / --c-mute / --c-success / --c-warning /
  --c-danger`, etc. — voir le `:root` actuel).
- **Pas d'édition manuelle de `static/css/tailwind.css`** : c'est la sortie
  du build Tailwind, regénérable. Toute règle custom va dans `app.css`.
- **Aucune valeur de couleur en dur en dehors du bloc `:root`.** Pas de
  hex (`#1A3A52`), pas de `rgb(…)`, pas de `rgba(…)` — y compris pour les
  ombres et les overlays translucides. Si une nuance n'est pas couverte,
  ajouter un token : `--c-overlay-30: rgba(0,0,0,0.30)`,
  `--c-shadow-card: 0 4px 12px rgba(0,0,0,0.15)`, etc., puis l'utiliser
  via `var(--…)`. Le `:root` actuel a déjà des tokens d'overlay blanc
  (`--c-white-30`, `--c-white-50`, …) à reproduire en symétrie côté noir
  selon le besoin.

## 2. Inline styles (`style="…"`) — la règle

**Interdits dans les templates applicatifs** (`templates/**/*.html` hors
les exceptions ci-dessous). Si un style est nécessaire :

1. Si Tailwind a une classe utilitaire → l'utiliser.
2. Sinon, ajouter une classe sémantique dans `app.css` (`.btn-coral`,
   `.input-coral`, `.sidebar-link`, `.step-dot`, etc.).
3. Sinon, créer une macro Jinja dans `templates/components/ui.html`.

**Exceptions autorisées (et seulement celles-ci)** :

- **Templates email** (`templates/emails/*`) : les clients mail (Outlook
  notamment) suppriment `<style>`. Inline obligatoire.
- **Valeurs dynamiques bindées à Jinja** quand elles ne peuvent
  raisonnablement pas être pré-définies en classes : barre de progression
  `style="width: {{ pct }}%"`, image inline `style="background-image:
  url('{{ photo }}')"`, masquage conditionnel généré côté serveur
  `{% if hide %}style="display:none"{% endif %}`. Documenter brièvement
  pourquoi en commentaire au-dessus si c'est non évident.

**Pas d'autre exception.** Pas même les utilitaires dev (le bandeau
`dev_account_switcher` est sweepé comme le reste : classe dédiée
`.dev-switcher-…` dans `app.css`, jamais d'inline). Tout `style="…"`
dans un template hors les deux cas ci-dessus = à refactorer.

## 3. Inline scripts (`<script>`, `onclick=`, `onmouseover=`, …)

Interdits. La CSP en mode enforcing bloque `unsafe-inline` pour les
scripts. Conventions en place :

- Comportement attaché en JS via délégation `data-action` (cf.
  `static/js/app.js`).
- États visuels (hover, focus, active) gérés en CSS, pas en JS
  (`.btn-ghost-navy`, `.input-soft`, `.input-coral`, etc.).
- JS spécifique à une page : un fichier dédié dans `static/js/` chargé
  uniquement sur les routes concernées.

## 4. Classes vs macros — quand promouvoir

**Nommer dès la première occurrence non triviale**, pas à un seuil de
répétitions. La logique : un agent (humain ou IA) qui arrive sur la
codebase ne peut pas grepper le front entier pour vérifier qu'un pattern
existe déjà. **La classe nommée _est_ la documentation** — elle déclare
qu'un motif a un sens et qu'il est réutilisable.

Conséquences concrètes :

- **Une classe utilitaire** dès qu'un bloc Tailwind a un *rôle* identifiable :
  un type de bouton, un état d'input, un badge de statut, un dot de
  progression. Préférer `.btn-coral` à `bg-[--c-coral] hover:bg-[#8B4A3D]
  text-white transition-colors`.
- **Une macro Jinja** dès qu'un fragment HTML a une structure récurrente
  (carte, empty state, ligne de tableau, en-tête de page, stat tile,
  champ de formulaire). Voir `templates/components/ui.html`.
- Avant d'écrire un nouveau bloc, **lire `app.css` (`:root`, classes) et
  `templates/components/ui.html` (macros)** — c'est court et c'est le
  catalogue. Réutiliser avant de créer.
- Une seule règle de garde-fou contre l'abstraction prématurée : ne pas
  inventer de paramètres « pour plus tard » dans une macro. Démarrer avec
  les paramètres effectivement utilisés ; en ajouter quand le besoin
  apparaît. La nomination, oui ; la flexibilité spéculative, non.

Note : « non trivial » exclut les compositions purement spatiales
ponctuelles (ex. `flex gap-4 items-center` sur un seul site). Tailwind
reste le bon outil pour la mise en page unique. La règle vise les motifs
*sémantiques* — couleur de marque, état d'interaction, composant.

## 5. Conventions de nommage

- Tokens couleur : `--c-<role>` (`--c-coral`, `--c-success-bg`,
  `--c-text-soft`).
- Tokens layout : `--w-…` (largeur), `--h-…` (hauteur).
- Tokens type : `--font-display`, `--font-body`.
- Classes utilitaires de marque : `.btn-…`, `.input-…`, `.sidebar-link`,
  `.step-dot[--current|--done]` (BEM léger pour les modificateurs).
- Macros : verbe ou nom court (`card`, `page_header`, `empty_state`,
  `stat_tile`, `form_field`, `form_select`, …).

## 6. Parité visuelle pour les refactors

Un sweep de styles est censé être visuellement neutre.

- Annoncer explicitement qu'un refactor est « visuellement no-op ».
- Si le delta visuel n'est pas garanti à 100 %, **réduire le périmètre**
  plutôt que d'expédier un changement esthétique sous couvert de refactor.
- Indiquer dans la PR si l'UI n'a pas été ouverte dans un navigateur.
- Pas de mélange refactor + redesign dans la même PR. Si un alignement
  pixel diverge, soit le restaurer tel quel, soit ouvrir une PR `style:`
  séparée.

## 7. Checklist avant push

- [ ] Aucun nouveau `style="…"` hors exceptions §2 (`grep -rE
      'style="[^"]+"' templates/ | grep -v emails/`).
- [ ] Aucun nouveau `<style>` inline dans un template (sauf éventuellement
      du base si vraiment justifié — historiquement on les a tous sortis).
- [ ] Aucun `onclick=`, `onfocus=`, `onmouseover=`, etc.
- [ ] Aucune couleur en dur hors `:root` : pas de `#…`, `rgb(…)`,
      `rgba(…)` dans les templates ni dans le corps de `app.css`. Les
      ombres et overlays passent aussi par un token.
- [ ] `static/css/tailwind.css` n'apparaît pas dans le diff (sauf
      regénération volontaire et annoncée).
- [ ] Si nouvelle couleur ou ombre : token ajouté dans `:root` ; cherché
      un doublon existant avant.
- [ ] Tout motif sémantique (rôle de bouton, état d'input, badge,
      composant…) a une classe ou une macro nommée — lu `app.css` et
      `templates/components/ui.html` *avant* d'écrire du Tailwind ad hoc.

## 8. PR de sweep — gabarit

Une PR « sweep » nettoie l'existant sans changer l'UX :

- Titre : `refactor(templates): inline-style sweep — <scope>`
- Commits atomiques par scope (auth / landing / client / caterer / admin
  / shared / errors). Voir l'historique de `staging` (PR #20) pour le
  modèle.
- Description en français ; commits en anglais.
- Contre-vérification visuelle au moins sur les pages les plus visibles
  du scope.
