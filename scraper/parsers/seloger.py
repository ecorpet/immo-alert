"""Parser pour SeLoger — extrait les données JSON depuis window.__NEXT_DATA__ ou initialData."""

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
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": "https://www.seloger.com/",
}


class SeLogerParser(BaseParser):
    """Parser pour SeLoger."""

    SOURCE = "seloger"

    def parse(self, url: str) -> list[Annonce]:
        """Parse une URL de recherche SeLoger et retourne les annonces."""
        for attempt in range(self.MAX_RETRIES):
            try:
                with httpx.Client(headers=HEADERS, timeout=self.TIMEOUT, follow_redirects=True) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                    return self._parse_html(resp.text)
            except httpx.HTTPStatusError as e:
                logger.warning("SeLoger HTTP %s, tentative %d/%d", e.response.status_code, attempt + 1, self.MAX_RETRIES)
            except Exception as e:
                logger.error("Erreur SeLoger tentative %d: %s", attempt + 1, e)
            if attempt < self.MAX_RETRIES - 1:
                time.sleep(2 ** attempt * 2)
        return []

    def _parse_html(self, html: str) -> list[Annonce]:
        """Extrait les annonces depuis le JSON embarqué dans la page."""
        soup = BeautifulSoup(html, "html.parser")

        # Tenter __NEXT_DATA__
        next_data_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_data_tag:
            try:
                data = json.loads(next_data_tag.string)
                listings = self._extract_listings_from_next_data(data)
                if listings:
                    return listings
            except (json.JSONDecodeError, AttributeError) as e:
                logger.debug("SeLoger __NEXT_DATA__ échoué: %s", e)

        # Tenter window["initialData"] ou initialData = {...}
        for script in soup.find_all("script"):
            text = script.string or ""
            m = re.search(r'window\["initialData"\]\s*=\s*({.+?});', text, re.DOTALL)
            if not m:
                m = re.search(r'initialData\s*=\s*({.+?});', text, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                    listings = self._extract_listings_from_next_data(data)
                    if listings:
                        return listings
                except json.JSONDecodeError:
                    continue

        logger.warning("Aucune donnée JSON trouvée pour SeLoger")
        return []

    def _extract_listings_from_next_data(self, data: dict) -> list[Annonce]:
        """Navigue dans l'arborescence JSON pour trouver les annonces."""
        # Chercher récursivement une liste de listings
        listings = self._find_listings(data)
        return [a for item in listings if (a := self._annonce_from_listing(item))]

    def _find_listings(self, obj: object, depth: int = 0) -> list[dict]:
        """Recherche récursive d'une liste d'annonces dans un dict JSON."""
        if depth > 8:
            return []
        if isinstance(obj, dict):
            # Clés typiques SeLoger
            for key in ("listings", "ads", "results", "items", "cards"):
                if key in obj and isinstance(obj[key], list) and len(obj[key]) > 0:
                    if isinstance(obj[key][0], dict) and "id" in obj[key][0]:
                        return obj[key]
            for v in obj.values():
                result = self._find_listings(v, depth + 1)
                if result:
                    return result
        elif isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
            if "id" in obj[0] and "price" in obj[0]:
                return obj
        return []

    def _annonce_from_listing(self, item: dict) -> Annonce | None:
        """Construit une Annonce depuis un dict de listing SeLoger."""
        try:
            ad_id = str(item.get("id", item.get("listingId", "")))
            prix = int(item.get("price", item.get("pricing", {}).get("price", 0)) or 0)
            if not prix or not ad_id:
                return None

            def to_float(v: object) -> float | None:
                try:
                    return float(str(v).replace(",", ".")) if v else None
                except (ValueError, TypeError):
                    return None

            def to_int(v: object) -> int | None:
                try:
                    return int(str(v)) if v else None
                except (ValueError, TypeError):
                    return None

            photos = [
                p if isinstance(p, str) else p.get("url", p.get("src", ""))
                for p in (item.get("photos") or item.get("images") or [])
            ]
            photos = [p for p in photos if p]

            contact = item.get("contact", {})
            adresse = (
                item.get("address")
                or item.get("location", {}).get("label", "")
                or contact.get("city", "")
            )
            code_postal = item.get("postalCode") or item.get("location", {}).get("postalCode")

            return Annonce(
                id=f"seloger_{ad_id}",
                titre=item.get("title", item.get("publicationTitle", "")),
                prix=prix,
                surface=to_float(item.get("surface", item.get("area"))),
                chambres=to_int(item.get("bedroomCount", item.get("bedrooms"))),
                pieces=to_int(item.get("roomCount", item.get("rooms"))),
                adresse=adresse,
                code_postal=str(code_postal) if code_postal else None,
                description=item.get("description", item.get("shortDescription", "")),
                photos=photos,
                url=item.get("listingUrl", item.get("url", f"https://www.seloger.com/annonces/{ad_id}.htm")),
                etage=to_int(item.get("floor", item.get("floorNumber"))),
                source=self.SOURCE,
                date_publication=item.get("publicationDate"),
            )
        except Exception as e:
            logger.debug("Erreur construction Annonce SeLoger: %s", e)
            return None
