"""Parser pour Bien'ici — extrait les données depuis window.__INITIAL_STATE__."""

import json
import logging
import re
import time

import httpx
from bs4 import BeautifulSoup

from .base import Annonce, BaseParser

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": "https://www.bienici.com/",
}


class BieniciParser(BaseParser):
    """Parser pour Bien'ici."""

    SOURCE = "bienici"

    def parse(self, url: str) -> list[Annonce]:
        """Parse une URL de recherche Bien'ici et retourne les annonces."""
        for attempt in range(self.MAX_RETRIES):
            try:
                with httpx.Client(headers=HEADERS, timeout=self.TIMEOUT, follow_redirects=True) as client:
                    logger.info("[bienici] GET %s (tentative %d)", url[:80], attempt + 1)
                    resp = client.get(url)
                    logger.info("[bienici] HTTP %s — %d octets", resp.status_code, len(resp.content))
                    resp.raise_for_status()
                    html = resp.text
                    if any(kw in html.lower() for kw in ["captcha", "are you a robot", "accès refusé", "access denied"]):
                        logger.warning("[bienici] Blocage anti-bot détecté dans la réponse HTML")
                    return self._parse_html(html)
            except httpx.HTTPStatusError as e:
                logger.warning("[bienici] HTTP %s — bloqué ? (tentative %d/%d)", e.response.status_code, attempt + 1, self.MAX_RETRIES)
            except Exception as e:
                logger.error("[bienici] Erreur tentative %d : %s", attempt + 1, e, exc_info=True)
            if attempt < self.MAX_RETRIES - 1:
                time.sleep(2 ** attempt * 2)
        logger.error("[bienici] Échec après %d tentatives", self.MAX_RETRIES)
        return []

    def _parse_html(self, html: str) -> list[Annonce]:
        """Extrait les annonces depuis window.__INITIAL_STATE__."""
        soup = BeautifulSoup(html, "html.parser")

        for script in soup.find_all("script"):
            text = script.string or ""
            m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?});?\s*</script>", text, re.DOTALL)
            if not m:
                m = re.search(r"__INITIAL_STATE__\s*=\s*({.+})", text, re.DOTALL)
            if m:
                logger.info("[bienici] __INITIAL_STATE__ trouvé, extraction JSON…")
                try:
                    data = json.loads(m.group(1))
                    ads = self._extract_ads(data)
                    logger.info("[bienici] %d annonces brutes extraites", len(ads))
                    results = [a for item in ads if (a := self._annonce_from_item(item))]
                    logger.info("[bienici] %d annonces valides", len(results))
                    return results
                except json.JSONDecodeError as e:
                    logger.warning("[bienici] JSON decode échoué : %s", e)

        logger.warning("[bienici] window.__INITIAL_STATE__ introuvable — site bloqué ou structure changée")
        return []

    def _extract_ads(self, data: dict) -> list[dict]:
        """Cherche les annonces dans l'arborescence JSON."""
        # Chemins typiques Bien'ici
        for path in [
            ["realEstateAds"],
            ["searchResults", "ads"],
            ["results", "realEstateAds"],
        ]:
            node = data
            for key in path:
                if isinstance(node, dict) and key in node:
                    node = node[key]
                else:
                    node = None
                    break
            if isinstance(node, list) and node:
                return node
        return []

    def _annonce_from_item(self, item: dict) -> Annonce | None:
        """Construit une Annonce depuis un dict Bien'ici."""
        try:
            ad_id = str(item.get("id", ""))
            prix = int(item.get("price", 0) or 0)
            if not prix or not ad_id:
                return None

            photos = [
                p.get("url", p.get("src", "")) if isinstance(p, dict) else str(p)
                for p in (item.get("photos") or [])
            ]
            photos = [p for p in photos if p]

            adresse = item.get("address", {})
            if isinstance(adresse, dict):
                adresse_str = adresse.get("label", adresse.get("city", ""))
                code_postal = str(adresse.get("postalCode", "")) or None
            else:
                adresse_str = str(adresse)
                code_postal = None
                m = re.search(r"13\d{3}", adresse_str)
                if m:
                    code_postal = m.group()

            return Annonce(
                id=f"bienici_{ad_id}",
                titre=item.get("title", ""),
                prix=prix,
                surface=float(item["surfaceArea"]) if item.get("surfaceArea") else None,
                chambres=int(item["bedroomCount"]) if item.get("bedroomCount") else None,
                pieces=int(item["roomsQuantity"]) if item.get("roomsQuantity") else None,
                adresse=adresse_str,
                code_postal=code_postal,
                description=item.get("description", ""),
                photos=photos,
                url=item.get("url", f"https://www.bienici.com/annonce/{ad_id}"),
                etage=int(item["floor"]) if item.get("floor") is not None else None,
                source=self.SOURCE,
                date_publication=item.get("publicationDate"),
            )
        except Exception as e:
            logger.debug("Erreur construction Annonce Bien'ici: %s", e)
            return None
