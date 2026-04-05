# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# Immo Alert Marseille

## Objectif
Créer un système automatisé qui scrape des annonces immobilières, les compare à mes critères (stockés dans Google Sheets), m'envoie des alertes SMS, et met à jour un mini site web. Le tout 100% gratuit, hébergé sur GitHub.

## Stack technique
- **Langage** : Python 3.11+
- **Scraping** : httpx + BeautifulSoup4 (+ playwright en fallback si anti-bot)
- **Google Sheets** : CSV public (httpx — aucun service account requis)
- **SMS** : API Free Mobile (GET https://smsapi.free-mobile.fr/sendmsg)
- **Notifications push** : ntfy.sh (POST https://ntfy.sh/{topic})
- **Site web** : HTML statique généré par le script → GitHub Pages (branche `gh-pages` ou dossier `docs/`)
- **Automatisation** : GitHub Actions (cron toutes les heures)
- **Déduplication** : fichier `data/seen.json` committé dans le repo

## Commands

```bash
# Installer les dépendances
pip install -r requirements.txt

# Lancer le scraper localement (nécessite un fichier .env)
python -m scraper.main

# Lancer les tests
pytest tests/ -v

# Lancer un test spécifique
pytest tests/test_matcher.py::test_prix_max_satisfait -v
```

## Variables d'environnement (.env local)

```
GOOGLE_SHEETS_ID=<id du sheet (entre /d/ et /edit dans l'URL)>
FREE_SMS_USER=<identifiant free mobile>
FREE_SMS_PASS=<clé API free mobile>
NTFY_TOPIC=<nom du topic ntfy.sh (ex: immo-alert-marseille-abc123)>
SITE_URL=<url github pages>
```

Le Google Sheet doit être **partagé publiquement** (« Toute personne disposant du lien peut consulter »).

## Architecture

**Flux d'exécution** (`scraper/main.py`) :
1. Lit les critères et URLs de recherche depuis Google Sheets (`sheets.py`)
2. Scrape chaque site actif avec le parser correspondant (`parsers/`)
3. Filtre les annonces déjà vues (`data/seen.json`)
4. Passe chaque nouvelle annonce dans le matcher (`matcher.py`)
5. Envoie des notifications pour les matches (`notifier.py`)
6. Régénère `docs/index.html` avec toutes les annonces matchées (`site_generator.py`)
7. Met à jour `data/seen.json` (committé par GitHub Actions)

**Parsers** (`scraper/parsers/`) :
- `base.py` : dataclass `Annonce` + classe abstraite `BaseParser`
- Chaque parser tente le HTML (JSON embarqué), puis fallback API interne si bloqué
- Timeout 15s, 3 retries avec backoff exponentiel (2s, 4s, 8s)
- Un parser qui plante ne bloque jamais les autres

**Matching** (`scraper/matcher.py`) :
- 3 niveaux : `obligatoire` (rejet si non satisfait), `optionnel` (+5 pts), `interdiction` (rejet immédiat si présent)
- Critères numériques : prix, chambres, photos (valeurs structurées)
- Critères textuels : bruit, étage élevé, vue dégagée, terrasse, exposition nord (mots-clés dans titre/description)
- Score seuil : 30 points
- Retourne `ResultatMatching(passe, score, tags_satisfaits, raisons_rejet)`

**seen.json** : dict `{annonce_id: {matched, score, tags, titre, prix, photo, url, timestamp, ...}}`. Les entrées `matched=True` sont rechargées à chaque run pour régénérer le site complet.

**Site** : Template Jinja2 → `docs/index.html`. Données JSON embarquées, filtres/tri client-side en vanilla JS. Servi par GitHub Pages depuis `/docs`.

## Google Sheets — Structure attendue

**Onglet `criteres`** : colonnes A (critère), B (valeur), C (priorité)

| Colonne A (critère) | Colonne B (valeur) | Colonne C (priorité) |
|---|---|---|
| prix_max | 350000 | obligatoire |
| chambres_min | 1 | obligatoire |
| arrondissements | 5,6,7 | obligatoire |
| photos_min | 5 | obligatoire |
| bruit | silencieux | obligatoire |
| etage | eleve | obligatoire |
| vue | degagee | obligatoire |
| exterieur | terrasse | optionnel |
| exposition_interdite | nord | interdiction |

**Onglet `sites`** : colonnes A (site), B (url), C (actif=oui/non)

Noms de sites reconnus : `leboncoin`, `seloger`, `bienici`, `pap`

## Parsers — Stratégies par site

**Leboncoin** : cherche `__NEXT_DATA__` JSON dans le HTML → fallback HTML classique → fallback API interne `api.leboncoin.fr/finder/search`

**SeLoger** : cherche `__NEXT_DATA__` → cherche `window["initialData"]` dans les balises `<script>`

**Bien'ici** : cherche `window.__INITIAL_STATE__` dans les balises `<script>`

**PAP** : BeautifulSoup direct sur le HTML (peu de protection anti-bot)

## Critères de matching — Logique

```python
# Numériques (données structurées)
prix_max:      annonce.prix <= critere.valeur
chambres_min:  annonce.chambres >= critere.valeur
photos_min:    len(annonce.photos) >= critere.valeur

# Géographique
arrondissements: code_postal in ["13005","13006","13007"]
                 OU patterns textuels "6e", "6ème", "marseille 6"

# Textuels (mots-clés dans titre + description)
bruit_silencieux:   "calme", "silencieux", "paisible"
                    INTERDIT "bruyant", "passant", "animé"
etage_eleve:        "dernier étage", ou etage >= 3, ou regex [4-9]e étage
vue_degagee:        "vue dégagée", "vue mer", "sans vis-à-vis"
exterieur_terrasse: "terrasse", "balcon", "rooftop"
exposition_nord:    REJET si "exposition nord", "plein nord", "orienté nord"
```

### Score
- Critère obligatoire satisfait : +10 pts
- Critère optionnel satisfait : +5 pts
- Critère non vérifiable (info absente) : +0, pas de rejet
- Seuil de passage : 30 pts
- Interdiction déclenchée ou critère obligatoire numérique raté : rejet immédiat (score = -1)

## Structure du repo

```
immo-alert/
├── .github/workflows/scrape.yml   # GitHub Actions cron toutes les heures
├── scraper/
│   ├── main.py                    # Point d'entrée
│   ├── sheets.py                  # Lecture Google Sheets
│   ├── matcher.py                 # Moteur de matching
│   ├── notifier.py                # SMS Free Mobile
│   ├── site_generator.py          # Génère docs/index.html
│   └── parsers/
│       ├── base.py                # Annonce dataclass + BaseParser ABC
│       ├── leboncoin.py
│       ├── seloger.py
│       ├── bienici.py
│       └── pap.py
├── templates/site_template.html   # Template Jinja2 du site
├── docs/index.html                # Site généré (GitHub Pages)
├── data/seen.json                 # IDs vus + données annonces matchées
└── tests/test_matcher.py          # Tests pytest du matcher
```
