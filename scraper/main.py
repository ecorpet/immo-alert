"""Point d'entrée du scraper immo-alert."""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Charger les variables .env en développement local
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .parsers.leboncoin import LeboncoinParser
from .parsers.seloger import SeLogerParser
from .parsers.bienici import BieniciParser
from .parsers.pap import PAPParser
from .parsers.base import Annonce
from .sheets import lire_criteres, lire_sites
from .matcher import matcher_annonce
from .notifier import envoyer_sms, envoyer_ntfy, formater_sms
from .site_generator import generer_site

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
SEEN_FILE = DATA_DIR / "seen.json"

PARSERS: dict[str, type] = {
    "leboncoin": LeboncoinParser,
    "seloger": SeLogerParser,
    "bienici": BieniciParser,
    "pap": PAPParser,
}


def _charger_seen() -> dict[str, dict]:
    """Charge le fichier seen.json (dict {id: données enrichies})."""
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("seen.json corrompu — réinitialisation")
    return {}


def _sauvegarder_seen(seen: dict[str, dict]) -> None:
    """Sauvegarde le fichier seen.json."""
    DATA_DIR.mkdir(exist_ok=True)
    SEEN_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")


def _annonce_to_dict(annonce: Annonce, score: int, tags: list[str], timestamp: float) -> dict:
    """Sérialise une Annonce en dict pour seen.json et le site."""
    prix_formate = f"{annonce.prix:,}".replace(",", "\u202f") + " €" if annonce.prix else "N/A"
    return {
        "id": annonce.id,
        "titre": annonce.titre,
        "prix": annonce.prix,
        "prix_formate": prix_formate,
        "surface": annonce.surface,
        "chambres": annonce.chambres,
        "pieces": annonce.pieces,
        "adresse": annonce.adresse,
        "code_postal": annonce.code_postal,
        "etage": annonce.etage,
        "photo": annonce.photos[0] if annonce.photos else None,
        "url": annonce.url,
        "source": annonce.source,
        "score": score,
        "tags": tags,
        "timestamp": timestamp,
        "date_detection": datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%d/%m/%Y %H:%M"),
        "matched": True,
        "is_new": False,  # sera recalculé par site_generator
    }


def main() -> None:
    """Orchestre le scraping, le matching, les notifications et la génération du site."""
    logger.info("=== Démarrage immo-alert ===")

    sheet_id = os.environ.get("GOOGLE_SHEETS_ID")
    if not sheet_id:
        logger.error("GOOGLE_SHEETS_ID manquant")
        sys.exit(1)

    # --- Chargement des critères et sites ---
    try:
        criteres = lire_criteres(sheet_id)
        sites = lire_sites(sheet_id)
    except Exception as e:
        logger.error("Erreur lecture Google Sheets : %s", e)
        sys.exit(1)

    seen = _charger_seen()

    # Annonces matchées lors de cette exécution
    nouvelles: list[dict] = []

    # --- Scraping de chaque site actif ---
    for site_info in sites:
        site_nom = site_info["site"]
        site_url = site_info["url"]

        parser_class = PARSERS.get(site_nom)
        if not parser_class:
            logger.warning("Pas de parser pour le site : %s", site_nom)
            continue

        logger.info("Scraping %s → %s", site_nom, site_url)
        try:
            annonces_brutes: list[Annonce] = parser_class().parse(site_url)
        except Exception as e:
            logger.error("Erreur critique scraping %s : %s", site_nom, e, exc_info=True)
            continue

        logger.info("%s : %d annonces récupérées", site_nom, len(annonces_brutes))
        for a in annonces_brutes[:3]:
            logger.info("  • [%s] %s — %s € — %s", a.id, a.titre[:50], a.prix, a.url[:60])

        for annonce in annonces_brutes:
            if annonce.id in seen:
                continue  # Déjà traitée

            try:
                resultat = matcher_annonce(annonce, criteres)
            except Exception as e:
                logger.error("Erreur matching %s : %s", annonce.id, e)
                continue

            if resultat.passe:
                ts = time.time()
                data = _annonce_to_dict(annonce, resultat.score, resultat.tags_satisfaits, ts)
                seen[annonce.id] = data
                nouvelles.append(data)
                logger.info("✅ Match : %s — %d € (score %d)", annonce.titre[:50], annonce.prix, resultat.score)
            else:
                # Enregistrer comme vue mais non matchée (évite de la retraiter)
                seen[annonce.id] = {"matched": False, "timestamp": time.time()}
                logger.debug("❌ Rejeté %s : %s", annonce.id, resultat.raisons_rejet)

    _sauvegarder_seen(seen)

    # --- Notifications ---
    if nouvelles:
        _notifier(nouvelles)
    else:
        logger.info("Aucune nouvelle annonce matchée")

    # --- Génération du site (toutes les annonces matchées, pas seulement les nouvelles) ---
    toutes_matchees = [v for v in seen.values() if v.get("matched") and v.get("titre")]
    try:
        generer_site(toutes_matchees)
    except Exception as e:
        logger.error("Erreur génération site : %s", e)

    logger.info("=== Fin : %d nouvelles | %d au total ===", len(nouvelles), len(toutes_matchees))


def _notifier(annonces: list[dict]) -> None:
    """Envoie les notifications (Free Mobile SMS et/ou ntfy) pour les nouvelles annonces."""
    free_user = os.environ.get("FREE_SMS_USER")
    free_pass = os.environ.get("FREE_SMS_PASS")
    ntfy_topic = os.environ.get("NTFY_TOPIC")
    site_url = os.environ.get("SITE_URL", "https://votre-user.github.io/immo-alert")

    nb = len(annonces)

    if nb == 1:
        a = annonces[0]
        ann = Annonce(
            id=a["id"], titre=a["titre"], prix=a["prix"],
            surface=a.get("surface"), chambres=a.get("chambres"),
            pieces=a.get("pieces"), adresse=a.get("adresse", ""),
            code_postal=a.get("code_postal"), description="",
            photos=[a["photo"]] if a.get("photo") else [],
            url=a["url"], etage=a.get("etage"),
            source=a.get("source", ""), date_publication=None,
        )
        sms = formater_sms(ann, a["score"])
        if free_user and free_pass:
            envoyer_sms(free_user, free_pass, sms)
        if ntfy_topic:
            pieces = f"{a['pieces']}P " if a.get("pieces") else ""
            surface = f"{int(a['surface'])}m² " if a.get("surface") else ""
            prix_k = f"{a['prix'] // 1000}k€" if a.get("prix") else "?"
            title = f"🏠 {pieces}{surface}{prix_k} — score {a['score']}"
            body = f"{a.get('adresse') or a.get('titre', '')}\n{a['url']}"
            envoyer_ntfy(ntfy_topic, title, body, url=a["url"])
    else:
        scores = ", ".join(str(a["score"]) for a in annonces[:3])
        msg = f"🏠 {nb} nouvelles annonces !\nScores : {scores}\n→ {site_url}"
        if free_user and free_pass:
            envoyer_sms(free_user, free_pass, msg[:160])
        if ntfy_topic:
            envoyer_ntfy(ntfy_topic, f"🏠 {nb} nouvelles annonces", msg, url=site_url)


if __name__ == "__main__":
    main()
