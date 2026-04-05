"""Parser pour PAP — scraping HTML classique (BeautifulSoup direct, peu de protection anti-bot)."""

import logging
import re
import time

import httpx
from bs4 import BeautifulSoup

from .base import Annonce, BaseParser

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": "https://www.pap.fr/",
}

BASE_URL = "https://www.pap.fr"


class PAPParser(BaseParser):
    """Parser pour PAP."""

    SOURCE = "pap"

    def parse(self, url: str) -> list[Annonce]:
        """Parse une URL de recherche PAP et retourne les annonces."""
        for attempt in range(self.MAX_RETRIES):
            try:
                with httpx.Client(headers=HEADERS, timeout=self.TIMEOUT, follow_redirects=True) as client:
                    logger.info("[pap] GET %s (tentative %d)", url[:80], attempt + 1)
                    resp = client.get(url)
                    logger.info("[pap] HTTP %s — %d octets", resp.status_code, len(resp.content))
                    resp.raise_for_status()
                    html = resp.text
                    if any(kw in html.lower() for kw in ["captcha", "are you a robot", "accès refusé", "access denied"]):
                        logger.warning("[pap] Blocage anti-bot détecté dans la réponse HTML")
                    return self._parse_html(html)
            except httpx.HTTPStatusError as e:
                logger.warning("[pap] HTTP %s — bloqué ? (tentative %d/%d)", e.response.status_code, attempt + 1, self.MAX_RETRIES)
            except Exception as e:
                logger.error("[pap] Erreur tentative %d : %s", attempt + 1, e, exc_info=True)
            if attempt < self.MAX_RETRIES - 1:
                time.sleep(2 ** attempt * 2)
        logger.error("[pap] Échec après %d tentatives", self.MAX_RETRIES)
        return []

    def _parse_html(self, html: str) -> list[Annonce]:
        """Parse la page de résultats PAP."""
        soup = BeautifulSoup(html, "html.parser")
        annonces = []

        cards = soup.select("article.search-list-item, div.search-list-item, li.search-list-item")
        logger.info("[pap] Sélecteur principal : %d cartes trouvées", len(cards))
        if not cards:
            cards = soup.select("[class*='search-list-item'], [class*='annonce']")
            logger.info("[pap] Sélecteur alternatif : %d cartes trouvées", len(cards))

        for card in cards:
            annonce = self._annonce_from_card(card)
            if annonce:
                annonces.append(annonce)

        logger.info("[pap] %d annonces valides extraites", len(annonces))
        return annonces

    def _annonce_from_card(self, card: BeautifulSoup) -> Annonce | None:
        """Extrait une Annonce depuis une carte HTML PAP."""
        try:
            # Lien et ID
            link = card.select_one("a[href*='/annonce/'], a[href*='/vente/']")
            if not link:
                link = card.select_one("a[href]")
            if not link:
                return None

            href = link.get("href", "")
            url = f"{BASE_URL}{href}" if href.startswith("/") else href
            m = re.search(r"-(\d+)\.htm|/(\d+)$", href)
            ad_id = (m.group(1) or m.group(2)) if m else re.sub(r"\W", "", href)[-12:]

            # Prix
            prix_el = card.select_one("[class*='price'], [class*='prix']")
            prix_str = prix_el.get_text(strip=True) if prix_el else ""
            prix = int(re.sub(r"\D", "", prix_str)) if prix_str else 0

            # Titre
            titre_el = card.select_one("h2, h3, [class*='title']")
            titre = titre_el.get_text(strip=True) if titre_el else ""

            # Adresse
            addr_el = card.select_one("[class*='location'], [class*='adresse'], [class*='ville']")
            adresse = addr_el.get_text(strip=True) if addr_el else ""
            cp_m = re.search(r"13\d{3}", adresse)
            code_postal = cp_m.group() if cp_m else None

            # Surface et pièces depuis le titre ou les tags
            texte = f"{titre} {card.get_text(' ')}"
            surface_m = re.search(r"(\d+(?:[,.]\d+)?)\s*m[²2]", texte)
            surface = float(surface_m.group(1).replace(",", ".")) if surface_m else None

            pieces_m = re.search(r"(\d+)\s*p[iè]", texte, re.IGNORECASE)
            pieces = int(pieces_m.group(1)) if pieces_m else None

            chambres_m = re.search(r"(\d+)\s*chambre", texte, re.IGNORECASE)
            chambres = int(chambres_m.group(1)) if chambres_m else None

            etage_m = re.search(r"(\d+)\s*[eè](?:me|r)?\s*étage|étage\s*(\d+)", texte, re.IGNORECASE)
            etage = int(etage_m.group(1) or etage_m.group(2)) if etage_m else None

            # Photo
            img_el = card.select_one("img[src]")
            photo_src = img_el.get("src", "") if img_el else ""
            photos = [photo_src] if photo_src and "placeholder" not in photo_src.lower() else []

            # Description
            desc_el = card.select_one("[class*='description'], [class*='desc']")
            description = desc_el.get_text(strip=True) if desc_el else ""

            return Annonce(
                id=f"pap_{ad_id}",
                titre=titre,
                prix=prix,
                surface=surface,
                chambres=chambres,
                pieces=pieces,
                adresse=adresse,
                code_postal=code_postal,
                description=description,
                photos=photos,
                url=url,
                etage=etage,
                source=self.SOURCE,
                date_publication=None,
            )
        except Exception as e:
            logger.debug("Erreur parsing carte PAP: %s", e)
            return None
