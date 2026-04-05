"""Génération du site statique docs/index.html via Jinja2."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
DOCS_DIR = Path(__file__).parent.parent / "docs"


def generer_site(annonces: list[dict]) -> None:
    """
    Génère docs/index.html à partir du template Jinja2.

    Args:
        annonces: liste de dicts d'annonces matchées (format issu de seen.json).
                  Champs attendus : id, titre, prix, prix_formate, surface, chambres,
                  pieces, adresse, code_postal, etage, photo, url, source, score,
                  tags, timestamp, date_detection, is_new.
    """
    DOCS_DIR.mkdir(exist_ok=True)
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("site_template.html")

    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff_24h = now_ts - 86400

    # Marquer les nouvelles annonces (< 24h)
    for a in annonces:
        a["is_new"] = a.get("timestamp", 0) > cutoff_24h

    # Trier par score décroissant
    annonces_triees = sorted(annonces, key=lambda x: x.get("score", 0), reverse=True)
    nouvelles = [a for a in annonces_triees if a.get("is_new")]

    derniere_maj = datetime.now(timezone.utc).strftime("%d/%m/%Y à %H:%M UTC")

    html = template.render(
        nouvelles_annonces=nouvelles,
        toutes_annonces=annonces_triees,
        nb_total=len(annonces_triees),
        derniere_maj=derniere_maj,
        annonces_json=json.dumps(annonces_triees, ensure_ascii=False, default=str),
    )

    output = DOCS_DIR / "index.html"
    output.write_text(html, encoding="utf-8")
    logger.info("Site généré : %s (%d annonces)", output, len(annonces_triees))
