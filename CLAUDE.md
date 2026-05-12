# CLAUDE.md

Instructions pour les agents (Claude Code et équivalents) qui travaillent
sur ce dépôt. À lire en début de session, avant d'éditer du code.

## Documents de référence — à ouvrir selon le contexte

- **`docs/frontend-rules.md`** — règles opérationnelles HTML/CSS/JS :
  tokens, inline styles + exceptions, scripts, classes vs macros,
  checklist push, gabarit de PR sweep. **À lire avant tout travail
  front.**

Ce doc fait foi. En cas de conflit avec un comportement par défaut ou une
convention « habituelle », c'est lui qui prime.

## Non-négociables (synthèse)

Détails et exceptions dans les docs liés ci-dessus. Ces points reviennent
souvent — les avoir en tête évite les allers-retours.

### Communication
- Réponses dans la langue du dernier message de l'utilisateur (pas celle
  du projet). En français → vouvoiement.
- Direct et concis. Pas de récap final qui répète le diff.

### Git / PR
- Commits **atomiques**, message d'**une ligne**, en **anglais**.
- Description de PR en **français**.
- **Pas** de `Co-Authored-By: Claude` ni mention d'Anthropic.
- Brancher depuis `staging` (sauf instruction contraire), viser `staging`.
- Ne pas faire `git add -A` aveugle ; choisir les fichiers explicitement.

### Sécurité
- Penser comme un attaquant. Statique d'abord, dynamique ensuite.
- Réutiliser l'écosystème (CSRF, CORS, Stripe SDK, rate-limiting, etc.) —
  ne pas réinventer.
- Vérifier les correctifs en red/green dans des vrais tests, pas des
  mocks qui ne testent rien.

### Front-end
- Pas d'inline `style="…"` (exceptions : templates email, valeurs
  bindées à du Jinja dynamique).
- Pas d'inline scripts ni `onclick=` / `onmouseover=` (CSP enforcing).
- Tokens couleur/ombre/layout dans `:root` de `static/css/app.css`. Pas
  de hex/rgb/rgba ailleurs.
- `static/css/tailwind.css` est généré : ne pas l'éditer à la main.
- Tout motif sémantique (rôle de bouton, état d'input, badge,
  composant…) → classe nommée dans `app.css` ou macro dans
  `templates/components/ui.html`. **La classe nommée est la
  documentation** : on nomme dès la première occurrence non triviale,
  pas à partir d'un seuil de répétitions.

### Refactor
- Pour un refactor « visuellement no-op », vérifier la parité avant de
  déclarer terminé. Sinon, réduire le périmètre.
- Pas de mélange refactor + redesign dans une même PR.

## Vérification avant de dire « terminé »

- Ai-je *vraiment* exécuté les commandes de vérification, ou est-ce que
  j'affirme ?
- Si claim UI : ai-je ouvert un navigateur ? Sinon, le dire.
- Si claim sécurité : ai-je relancé le scanner concerné et vérifié le
  delta ?
- Résumé de fin de tour : une ou deux phrases. Ce qui a changé, ce qui
  vient ensuite.
