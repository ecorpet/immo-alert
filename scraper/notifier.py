"""Notifications : SMS Free Mobile et Telegram."""

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


def envoyer_telegram(bot_token: str, chat_id: str, message: str, photo_url: str | None = None) -> bool:
    """Envoie un message via Telegram Bot API (aucune limite de longueur)."""
    try:
        base = f"https://api.telegram.org/bot{bot_token}"
        if photo_url:
            resp = httpx.post(
                f"{base}/sendPhoto",
                json={"chat_id": chat_id, "photo": photo_url, "caption": message[:1024], "parse_mode": "HTML"},
                timeout=10,
            )
        else:
            resp = httpx.post(
                f"{base}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                timeout=10,
            )
        if resp.status_code == 200:
            logger.info("Message Telegram envoyé")
            return True
        logger.warning("Erreur Telegram : %s — %s", resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.error("Exception Telegram : %s", e)
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


def formater_telegram(annonce: Annonce, score: int, tags: list[str]) -> str:
    """Formate un message Telegram riche pour une annonce."""
    details = " · ".join(filter(None, [
        f"{annonce.pieces} pièces" if annonce.pieces else None,
        f"{annonce.surface}m²" if annonce.surface else None,
        f"Étage {annonce.etage}" if annonce.etage is not None else None,
    ]))
    prix_formate = f"{annonce.prix:,}".replace(",", "\u202f") + " €" if annonce.prix else "N/A"
    tags_str = " · ".join(tags) if tags else ""

    lignes = [
        f"🏠 <b>{annonce.titre}</b>",
        f"💰 {prix_formate}",
        f"📐 {details}" if details else None,
        f"📍 {annonce.adresse}" if annonce.adresse else None,
        f"⭐ Score : {score}/100",
        f"✅ {tags_str}" if tags_str else None,
        f"\n🔗 <a href='{annonce.url}'>Voir l'annonce ({annonce.source})</a>",
    ]
    return "\n".join(l for l in lignes if l is not None)
