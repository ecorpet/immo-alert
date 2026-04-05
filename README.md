# Immo Alert Marseille

Scraper d'annonces immobilières avec alertes SMS et mini site web — 100% gratuit, hébergé sur GitHub.

## Fonctionnement

1. GitHub Actions scrape les sites toutes les heures
2. Les nouvelles annonces sont filtrées selon vos critères (Google Sheets)
3. Une alerte SMS est envoyée pour chaque match
4. Le site GitHub Pages est mis à jour automatiquement

## Installation

### 1. Google Sheets

1. Créer un Google Sheet avec deux onglets :
   - `criteres` (colonnes : critère | valeur | priorité)
   - `sites` (colonnes : site | url | actif)
2. **Partager publiquement** : Partager → « Toute personne disposant du lien » → Lecteur
3. Dans GitHub → Settings → Secrets :
   - `GOOGLE_SHEETS_ID` : l'ID du sheet (dans l'URL entre `/d/` et `/edit`)

### 2. SMS Free Mobile

1. Se connecter sur [mobile.free.fr](https://mobile.free.fr/account/mes-options)
2. Activer l'option **"Notifications par SMS"**
3. Récupérer l'identifiant et la clé API affichés
4. Dans GitHub → Secrets :
   - `FREE_SMS_USER` : votre identifiant Free Mobile
   - `FREE_SMS_PASS` : la clé API

### 3. GitHub Pages

1. Settings → Pages → Source : **"Deploy from a branch"**
2. Branche : `main`, dossier : `/docs`
3. Ajouter l'URL dans GitHub → Secrets :
   - `SITE_URL` : ex. `https://votre-user.github.io/immo-alert`

### 4. Telegram (optionnel)

1. Créer un bot via [@BotFather](https://t.me/BotFather) → récupérer le token
2. Envoyer un message à votre bot
3. Appeler `https://api.telegram.org/bot<TOKEN>/getUpdates` pour récupérer le `chat_id`
4. Dans GitHub → Secrets :
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

## Développement local

```bash
pip install -r requirements.txt

# Créer un fichier .env avec vos variables (voir CLAUDE.md)
cp .env.example .env  # adapter les valeurs

python -m scraper.main

# Tests
pytest tests/ -v
```

## Structure des critères (onglet `criteres`)

| critère | valeur | priorité |
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
| commerce_distance_max | 500 | optionnel |

## Structure des sites (onglet `sites`)

| site | url | actif |
|---|---|---|
| leboncoin | https://www.leboncoin.fr/recherche?... | oui |
| seloger | https://www.seloger.com/list.html?... | oui |
| pap | https://www.pap.fr/annonce/... | oui |
| bienici | https://www.bienici.com/recherche/... | oui |
