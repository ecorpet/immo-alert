"""Lecture des critères et des URLs de recherche depuis Google Sheets (CSV public)."""

import csv
import io
import logging
import os

import httpx

logger = logging.getLogger(__name__)

CSV_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={onglet}"


def _lire_onglet(sheet_id: str, onglet: str) -> list[list[str]]:
    """Télécharge l'onglet au format CSV et retourne les lignes (sans en-tête)."""
    url = CSV_URL.format(sheet_id=sheet_id, onglet=onglet)
    resp = httpx.get(url, timeout=15, follow_redirects=True)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    return rows[1:]  # ignorer l'en-tête


def lire_criteres(sheet_id: str) -> dict[str, dict[str, str]]:
    """
    Lit l'onglet 'criteres' du Google Sheet public.

    Retourne un dict de la forme :
        {"prix_max": {"valeur": "350000", "priorite": "obligatoire"}, ...}
    """
    rows = _lire_onglet(sheet_id, "criteres")
    criteres: dict[str, dict[str, str]] = {}
    for row in rows:
        if len(row) >= 2 and row[0].strip():
            criteres[row[0].strip()] = {
                "valeur": row[1].strip(),
                "priorite": row[2].strip() if len(row) >= 3 and row[2].strip() else "obligatoire",
            }
    logger.info("Critères chargés : %s", list(criteres.keys()))
    return criteres


def lire_sites(sheet_id: str) -> list[dict[str, str]]:
    """
    Lit l'onglet 'sites' du Google Sheet public.

    Retourne une liste de dicts {site, url} pour les sites actifs uniquement.
    """
    rows = _lire_onglet(sheet_id, "sites")
    sites = []
    for row in rows:
        if len(row) >= 2 and row[0].strip() and row[1].strip():
            actif = (row[2].strip().lower() == "oui") if len(row) >= 3 else True
            if actif:
                sites.append({
                    "site": row[0].strip().lower(),
                    "url": row[1].strip(),
                })
    logger.info("Sites actifs : %s", [s["site"] for s in sites])
    return sites
