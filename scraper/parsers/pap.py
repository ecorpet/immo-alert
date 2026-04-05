"""Parser pour PAP — RSS (fiable) avec fallback HTML."""

import logging
import re
import time
import xml.etree.ElementTree as ET

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
    """Parser pour PAP — préfère le flux RSS."""

    SOURCE = "pap"

    def parse(self, url: str) -> list[Annonce]:
        """Parse une URL PAP (RSS ou HTML)."""
        rss_url = self._to_rss_url(url)
        logger.info("[pap] GET RSS %s", rss_url[:80])
        try:
            with httpx.Client(headers=HEADERS, timeout=self.TIMEOUT, follow_redirects=True) as client:
                resp = client.get(rss_url)
                logger.info("[pap] HTTP %s — %d octets", resp.status_code, len(resp.content))
                resp.raise_for_status()
                annonces = self._parse_rss(resp.text)
                if annonces:
                    return annonces
                logger.warning("[pap] RSS vide, fallback HTML…")
        except Exception as e:
            logger.warning("[pap] RSS échoué (%s), fallback HTML…", e)

        # Fallback HTML
        return self._parse_html_url(url)

    # ------------------------------------------------------------------

    def _to_rss_url(self, url: str) -> str:
        """Convertit une URL de recherche PAP en URL RSS si nécessaire."""
        if ".rss" in url:
            return url
        # Supprime les paramètres GET et ajoute .rss
        base = url.split("?")[0].rstrip("/")
        return base + ".rss"

    def _parse_rss(self, xml_text: str) -> list[Annonce]:
        """Parse un flux RSS PAP."""
        try:
            root = ET.fromstring(xml_text.encode("utf-8"))
        except ET.ParseError as e:
            logger.warning("[pap] Erreur parsing XML RSS : %s", e)
            return []

        items = root.findall(".//item")
        logger.info("[pap] RSS : %d items trouvés", len(items))
        annonces = [a for item in items if (a := self._annonce_from_rss_item(item))]
        logger.info("[pap] RSS : %d annonces valides", len(annonces))
        return annonces

    def _annonce_from_rss_item(self, item: ET.Element) -> Annonce | None:
        """Construit une Annonce depuis un item RSS PAP."""
        try:
            titre = (item.findtext("title") or "").strip()
            url = (item.findtext("link") or item.findtext("guid") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            description_html = item.findtext("description") or ""

            # ID depuis l'URL
            m = re.search(r"-r?(\d+)(?:\.htm)?$", url)
            ad_id = m.group(1) if m else re.sub(r"\W", "", url)[-12:]

            # Prix depuis le titre : "850 € par mois" ou "850€/mois"
            prix_m = re.search(r"(\d[\d\s]*)\s*€", titre.replace("\u202f", "").replace("\xa0", ""))
            prix = int(re.sub(r"\D", "", prix_m.group(1))) if prix_m else 0

            # Parsing de la description HTML
            soup = BeautifulSoup(description_html, "html.parser")
            texte_desc = soup.get_text(" ")

            # Surface
            surf_m = re.search(r"(\d+(?:[,.]\d+)?)\s*m[²2]", f"{titre} {texte_desc}", re.IGNORECASE)
            surface = float(surf_m.group(1).replace(",", ".")) if surf_m else None

            # Pièces / chambres
            pieces_m = re.search(r"(\d+)\s*pi[eè]ces?", f"{titre} {texte_desc}", re.IGNORECASE)
            pieces = int(pieces_m.group(1)) if pieces_m else None
            ch_m = re.search(r"(\d+)\s*chambre", f"{titre} {texte_desc}", re.IGNORECASE)
            chambres = int(ch_m.group(1)) if ch_m else None

            # Adresse / code postal
            addr_m = re.search(r"Marseille\s+(\d+)e?", f"{titre} {texte_desc}", re.IGNORECASE)
            code_postal = f"130{int(addr_m.group(1)):02d}" if addr_m else None
            adresse_m = re.search(r"(Marseille[^<\n,]{0,30})", texte_desc, re.IGNORECASE)
            adresse = adresse_m.group(1).strip() if adresse_m else ""

            # Photos
            photos = [img["src"] for img in soup.find_all("img", src=True) if "placeholder" not in img["src"].lower()]

            # Étage
            etage_m = re.search(r"(\d+)\s*[eè](?:me|r)?\s*étage|étage\s*(\d+)", texte_desc, re.IGNORECASE)
            etage = int(etage_m.group(1) or etage_m.group(2)) if etage_m else None

            return Annonce(
                id=f"pap_{ad_id}",
                titre=titre,
                prix=prix,
                surface=surface,
                chambres=chambres,
                pieces=pieces,
                adresse=adresse,
                code_postal=code_postal,
                description=texte_desc[:500],
                photos=photos,
                url=url,
                etage=etage,
                source=self.SOURCE,
                date_publication=pub_date,
            )
        except Exception as e:
            logger.debug("[pap] Erreur parsing item RSS : %s", e)
            return None

    # ------------------------------------------------------------------

    def _parse_html_url(self, url: str) -> list[Annonce]:
        """Fallback : scraping HTML classique."""
        for attempt in range(self.MAX_RETRIES):
            try:
                with httpx.Client(headers=HEADERS, timeout=self.TIMEOUT, follow_redirects=True) as client:
                    logger.info("[pap] GET HTML %s (tentative %d)", url[:80], attempt + 1)
                    resp = client.get(url)
                    logger.info("[pap] HTTP %s — %d octets", resp.status_code, len(resp.content))
                    resp.raise_for_status()
                    return self._parse_html(resp.text)
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
        logger.info("[pap] HTML sélecteur principal : %d cartes", len(cards))
        if not cards:
            cards = soup.select("[class*='search-list-item'], [class*='annonce']")
            logger.info("[pap] HTML sélecteur alternatif : %d cartes", len(cards))

        for card in cards:
            annonce = self._annonce_from_card(card)
            if annonce:
                annonces.append(annonce)

        logger.info("[pap] HTML : %d annonces valides", len(annonces))
        return annonces

    def _annonce_from_card(self, card: BeautifulSoup) -> Annonce | None:
        try:
            link = card.select_one("a[href*='/annonce/'], a[href*='/vente/'], a[href*='/location/']")
            if not link:
                link = card.select_one("a[href]")
            if not link:
                return None

            href = link.get("href", "")
            url = f"{BASE_URL}{href}" if href.startswith("/") else href
            m = re.search(r"-(\d+)\.htm|/(\d+)$", href)
            ad_id = (m.group(1) or m.group(2)) if m else re.sub(r"\W", "", href)[-12:]

            prix_el = card.select_one("[class*='price'], [class*='prix']")
            prix_str = prix_el.get_text(strip=True) if prix_el else ""
            prix = int(re.sub(r"\D", "", prix_str)) if prix_str else 0

            titre_el = card.select_one("h2, h3, [class*='title']")
            titre = titre_el.get_text(strip=True) if titre_el else ""

            addr_el = card.select_one("[class*='location'], [class*='adresse'], [class*='ville']")
            adresse = addr_el.get_text(strip=True) if addr_el else ""
            cp_m = re.search(r"13\d{3}", adresse)
            code_postal = cp_m.group() if cp_m else None

            texte = f"{titre} {card.get_text(' ')}"
            surf_m = re.search(r"(\d+(?:[,.]\d+)?)\s*m[²2]", texte)
            surface = float(surf_m.group(1).replace(",", ".")) if surf_m else None
            pieces_m = re.search(r"(\d+)\s*pi[eè]", texte, re.IGNORECASE)
            pieces = int(pieces_m.group(1)) if pieces_m else None
            ch_m = re.search(r"(\d+)\s*chambre", texte, re.IGNORECASE)
            chambres = int(ch_m.group(1)) if ch_m else None
            etage_m = re.search(r"(\d+)\s*[eè](?:me|r)?\s*étage|étage\s*(\d+)", texte, re.IGNORECASE)
            etage = int(etage_m.group(1) or etage_m.group(2)) if etage_m else None

            img_el = card.select_one("img[src]")
            photo_src = img_el.get("src", "") if img_el else ""
            photos = [photo_src] if photo_src and "placeholder" not in photo_src.lower() else []

            desc_el = card.select_one("[class*='description'], [class*='desc']")
            description = desc_el.get_text(strip=True) if desc_el else ""

            return Annonce(
                id=f"pap_{ad_id}",
                titre=titre, prix=prix, surface=surface,
                chambres=chambres, pieces=pieces, adresse=adresse,
                code_postal=code_postal, description=description,
                photos=photos, url=url, etage=etage,
                source=self.SOURCE, date_publication=None,
            )
        except Exception as e:
            logger.debug("[pap] Erreur parsing carte HTML : %s", e)
            return None
