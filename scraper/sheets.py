"""Lecture des critères et des URLs de recherche depuis Google Sheets."""

import json
import logging
import os

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _get_client() -> gspread.Client:
    """Crée un client Google Sheets authentifié via service account."""
    creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if not creds_json:
        raise ValueError("Variable d'environnement GOOGLE_SHEETS_CREDENTIALS manquante")
    creds_dict = json.loads(creds_json)
    credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(credentials)


def lire_criteres(sheet_id: str) -> dict[str, dict[str, str]]:
    """
    Lit l'onglet 'criteres' du Google Sheet.

    Retourne un dict de la forme :
        {"prix_max": {"valeur": "350000", "priorite": "obligatoire"}, ...}
    """
    client = _get_client()
    sh = client.open_by_key(sheet_id)
    ws = sh.worksheet("criteres")
    rows = ws.get_all_values()

    criteres: dict[str, dict[str, str]] = {}
    for row in rows[1:]:  # ignorer l'en-tête
        if len(row) >= 2 and row[0].strip():
            criteres[row[0].strip()] = {
                "valeur": row[1].strip(),
                "priorite": row[2].strip() if len(row) >= 3 and row[2].strip() else "obligatoire",
            }

    logger.info("Critères chargés : %s", list(criteres.keys()))
    return criteres


def lire_sites(sheet_id: str) -> list[dict[str, str]]:
    """
    Lit l'onglet 'sites' du Google Sheet.

    Retourne une liste de dicts {site, url, actif} pour les sites actifs uniquement.
    """
    client = _get_client()
    sh = client.open_by_key(sheet_id)
    ws = sh.worksheet("sites")
    rows = ws.get_all_values()

    sites = []
    for row in rows[1:]:  # ignorer l'en-tête
        if len(row) >= 2 and row[0].strip() and row[1].strip():
            actif = (row[2].strip().lower() == "oui") if len(row) >= 3 else True
            if actif:
                sites.append({
                    "site": row[0].strip().lower(),
                    "url": row[1].strip(),
                })

    logger.info("Sites actifs : %s", [s["site"] for s in sites])
    return sites
