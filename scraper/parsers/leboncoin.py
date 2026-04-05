"""Parser pour Leboncoin — tente d'abord le HTML (__NEXT_DATA__), puis l'API interne."""

import json
import logging
import re
import time
from typing import Any

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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Referer": "https://www.leboncoin.fr/",
}


class LeboncoinParser(BaseParser):
    """Parser pour Leboncoin."""

    SOURCE = "leboncoin"

    def parse(self, url: str) -> list[Annonce]:
        """Parse une URL de recherche Leboncoin et retourne les annonces."""
        for attempt in range(self.MAX_RETRIES):
            try:
                with httpx.Client(headers=HEADERS, timeout=self.TIMEOUT, follow_redirects=True) as client:
                    logger.info("[leboncoin] GET %s (tentative %d)", url[:80], attempt + 1)
                    resp = client.get(url)
                    logger.info("[leboncoin] HTTP %s — %d octets", resp.status_code, len(resp.content))
                    resp.raise_for_status()
                    html = resp.text
                    if any(kw in html.lower() for kw in ["captcha", "datadome", "are you a robot", "accès refusé", "access denied"]):
                        logger.warning("[leboncoin] Blocage anti-bot détecté dans la réponse HTML")
                    annonces = self._parse_html(html, client)
                    if annonces:
                        return annonces
                    logger.warning("[leboncoin] HTML vide ou bloqué, tentative API interne…")
                    return self._parse_api(url, client)
            except httpx.HTTPStatusError as e:
                logger.warning("[leboncoin] HTTP %s — bloqué ? (tentative %d/%d)", e.response.status_code, attempt + 1, self.MAX_RETRIES)
            except Exception as e:
                logger.error("[leboncoin] Erreur tentative %d : %s", attempt + 1, e, exc_info=True)
            if attempt < self.MAX_RETRIES - 1:
                time.sleep(2 ** attempt * 2)
        logger.error("[leboncoin] Échec après %d tentatives", self.MAX_RETRIES)
        return []

    # ------------------------------------------------------------------
    def _parse_html(self, html: str, client: httpx.Client) -> list[Annonce]:
        """Tente d'extraire les annonces via __NEXT_DATA__, puis HTML classique."""
        soup = BeautifulSoup(html, "html.parser")

        next_data_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_data_tag:
            logger.info("[leboncoin] __NEXT_DATA__ trouvé, extraction JSON…")
            try:
                data = json.loads(next_data_tag.string)
                # Trace le chemin JSON pour diagnostiquer les changements de structure
                props = data.get("props", {})
                logger.info("[leboncoin] props keys: %s", list(props.keys()))
                page_props = props.get("pageProps", {})
                logger.info("[leboncoin] pageProps keys: %s", list(page_props.keys()))
                search_data = page_props.get("searchData", {})
                logger.info("[leboncoin] searchData keys: %s", list(search_data.keys()) if isinstance(search_data, dict) else type(search_data).__name__)
                ads: list[dict] = search_data.get("ads", []) if isinstance(search_data, dict) else []
                logger.info("[leboncoin] __NEXT_DATA__ : %d annonces brutes", len(ads))
                if ads:
                    logger.info("[leboncoin] exemple annonce[0] keys: %s", list(ads[0].keys()))
                results = [a for ad in ads if (a := self._annonce_from_next_data(ad))]
                logger.info("[leboncoin] __NEXT_DATA__ : %d annonces valides", len(results))
                if results:
                    return results
            except (json.JSONDecodeError, AttributeError) as e:
                logger.warning("[leboncoin] Parsing __NEXT_DATA__ échoué : %s", e)
        else:
            logger.warning("[leboncoin] __NEXT_DATA__ absent")

        # Fallback HTML classique
        cards = soup.select("a[data-qa-id='aditem_container']")
        logger.info("[leboncoin] Fallback HTML : %d cartes trouvées", len(cards))
        return [a for card in cards if (a := self._annonce_from_card(card))]

    def _annonce_from_next_data(self, ad: dict[str, Any]) -> Annonce | None:
        """Construit une Annonce depuis les données JSON __NEXT_DATA__."""
        try:
            ad_id = str(ad.get("list_id", ""))
            prix_raw = ad.get("price", [None])
            prix = int(prix_raw[0]) if prix_raw else 0
            if not prix:
                return None

            attrs: dict[str, str] = {
                a["key"]: a.get("value_label", (a.get("values") or [""])[0])
                for a in ad.get("attributes", [])
                if "key" in a
            }

            def parse_int(s: str) -> int | None:
                cleaned = re.sub(r"\D", "", s)
                return int(cleaned) if cleaned else None

            def parse_float(s: str) -> float | None:
                cleaned = re.sub(r"[^\d.]", "", s)
                return float(cleaned) if cleaned else None

            location = ad.get("location", {})
            code_postal = location.get("zipcode", "") or None
            ville = location.get("city", "")
            adresse = f"{ville} {code_postal or ''}".strip()

            photos = [
                img if isinstance(img, str) else img.get("url", "")
                for img in ad.get("images", {}).get("urls_large", [])
            ]
            photos = [p for p in photos if p]

            return Annonce(
                id=f"leboncoin_{ad_id}",
                titre=ad.get("subject", ""),
                prix=prix,
                surface=parse_float(attrs.get("square", "")),
                chambres=parse_int(attrs.get("rooms", "")),
                pieces=parse_int(attrs.get("rooms", "")),
                adresse=adresse,
                code_postal=code_postal,
                description=ad.get("body", ""),
                photos=photos,
                url=f"https://www.leboncoin.fr/annonces/{ad_id}.htm",
                etage=parse_int(attrs.get("floor_number", "")),
                source=self.SOURCE,
                date_publication=ad.get("first_publication_date"),
            )
        except Exception as e:
            logger.debug("Erreur construction Annonce Leboncoin: %s", e)
            return None

    def _annonce_from_card(self, card: Any) -> Annonce | None:
        """Construit une Annonce depuis une carte HTML (fallback sans __NEXT_DATA__)."""
        href = card.get("href", "")
        if not href:
            return None
        url = f"https://www.leboncoin.fr{href}" if href.startswith("/") else href
        m = re.search(r"/(\d+)", href)
        if not m:
            return None

        prix_el = card.select_one("[data-qa-id='aditem_price']")
        prix_str = prix_el.get_text(strip=True) if prix_el else ""
        prix = int(re.sub(r"\D", "", prix_str)) if prix_str else 0

        titre_el = card.select_one("[data-qa-id='aditem_title']")
        titre = titre_el.get_text(strip=True) if titre_el else ""

        loc_el = card.select_one("[data-qa-id='aditem_location']")
        adresse = loc_el.get_text(strip=True) if loc_el else ""
        cp_match = re.search(r"13\d{3}", adresse)
        code_postal = cp_match.group() if cp_match else None

        img_el = card.select_one("img[src]")
        photos = [img_el["src"]] if img_el else []

        return Annonce(
            id=f"leboncoin_{m.group(1)}",
            titre=titre,
            prix=prix,
            surface=None,
            chambres=None,
            pieces=None,
            adresse=adresse,
            code_postal=code_postal,
            description="",
            photos=photos,
            url=url,
            etage=None,
            source=self.SOURCE,
            date_publication=None,
        )

    def _parse_api(self, search_url: str, client: httpx.Client) -> list[Annonce]:
        """Fallback via l'API interne Leboncoin (si DataDome bloque le HTML)."""
        try:
            api_headers = {
                **HEADERS,
                "Content-Type": "application/json",
                "api_key": "ba0c2dad52b3585c9a20b7f5e95ac119",
            }
            payload = {
                "filters": {
                    "category": {"id": "9"},
                    "enums": {"ad_type": ["offer"]},
                    "location": {"area": {"lat": 43.2965, "lng": 5.3698, "radius": 10000}},
                    "ranges": {},
                },
                "sort_by": "time",
                "sort_order": "desc",
                "offset": 0,
                "limit": 35,
            }
            logger.info("[leboncoin] POST API interne…")
            resp = client.post(
                "https://api.leboncoin.fr/finder/search",
                json=payload,
                headers=api_headers,
            )
            logger.info("[leboncoin] API HTTP %s — %d octets", resp.status_code, len(resp.content))
            resp.raise_for_status()
            ads = resp.json().get("ads", [])
            logger.info("[leboncoin] API : %d annonces", len(ads))
            return [a for ad in ads if (a := self._annonce_from_next_data(ad))]
        except Exception as e:
            logger.error("[leboncoin] Erreur API interne : %s", e, exc_info=True)
            return []
