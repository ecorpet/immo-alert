"""Notifications : SMS Free Mobile."""

import logging

import httpx

from .parsers.base import Annonce

logger = logging.getLogger(__name__)


def envoyer_sms(user: str, password: str, message: str) -> bool:
    """Envoie un SMS via l'API Free Mobile (max 160 caractères)."""
    try:
        resp = httpx.get(
            "https://smsapi.free-mobile.fr/sendmsg",
            params={"user": user, "pass": password, "msg": message[:160]},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("SMS envoyé avec succès")
            return True
        logger.warning("Erreur SMS Free Mobile : %s", resp.status_code)
        return False
    except Exception as e:
        logger.error("Exception envoi SMS : %s", e)
        return False


def formater_sms(annonce: Annonce, score: int) -> str:
    """Formate un SMS condensé pour une annonce (respecte la limite 160 chars)."""
    pieces = f"{annonce.pieces}P " if annonce.pieces else ""
    surface = f"{int(annonce.surface)}m² " if annonce.surface else ""
    prix_k = f"{annonce.prix // 1000}k€" if annonce.prix else "?"
    adresse = (annonce.adresse or "")[:25]
    lien = annonce.url[:55]
    msg = f"🏠 {pieces}{surface}{prix_k}\n{adresse}\nScore:{score}/100\n{lien}"
    return msg[:160]
