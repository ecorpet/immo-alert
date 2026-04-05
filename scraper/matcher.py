"""Moteur de matching : évalue une annonce contre les critères du Google Sheet."""

import logging
import re
from dataclasses import dataclass, field

from .parsers.base import Annonce

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dictionnaires de mots-clés
# ---------------------------------------------------------------------------

MOTS_CALME = ["calme", "silencieux", "silencieuse", "paisible", "au calme", "tranquille", "pas de vis-à-vis"]
MOTS_BRUYANT = ["bruyant", "bruyante", "passant", "passante", "animé", "animée", "rue passante"]
MOTS_ETAGE_ELEVE = ["dernier étage", "dernière étage", "étage élevé", "haut étage"]
MOTS_VUE = ["vue dégagée", "vue mer", "vue panoramique", "sans vis-à-vis", "sans vis à vis", "dégagée", "vue imprenable"]
MOTS_EXTERIEUR = ["terrasse", "balcon", "rooftop", "toit-terrasse", "toit terrasse", "jardin privatif"]
MOTS_EXPO_NORD = ["exposition nord", "plein nord", "orienté nord", "orientée nord", "face nord"]
MOTS_COMMERCES = ["proche commerces", "quartier commerçant", "commerces à pied", "commerces proches", "à pied des commerces"]


@dataclass
class ResultatMatching:
    """Résultat de l'évaluation d'une annonce."""

    passe: bool
    score: int
    tags_satisfaits: list[str] = field(default_factory=list)
    raisons_rejet: list[str] = field(default_factory=list)


def matcher_annonce(annonce: Annonce, criteres: dict[str, dict[str, str]]) -> ResultatMatching:
    """
    Évalue une annonce contre les critères et retourne le résultat.

    Règles de scoring :
    - Critère obligatoire satisfait : +10 pts
    - Critère optionnel satisfait   : +5 pts
    - Critère interdit détecté      : rejet immédiat (score = -1)
    - Critère obligatoire numérique non satisfait : rejet immédiat
    """
    score = 0
    tags: list[str] = []
    rejets: list[str] = []
    texte = f"{annonce.titre} {annonce.description}".lower()

    # --- Interdictions (vérifiées en premier) ---
    expo = _val(criteres, "exposition_interdite")
    if expo and "nord" in expo.lower():
        if any(m in texte for m in MOTS_EXPO_NORD):
            return ResultatMatching(False, -1, [], ["exposition nord détectée"])

    # --- Prix (obligatoire, numérique) ---
    prix_max_str = _val(criteres, "prix_max")
    if prix_max_str:
        try:
            prix_max = int(prix_max_str)
            if annonce.prix > 0:
                if annonce.prix <= prix_max:
                    score += 10
                    tags.append(f"prix ≤ {prix_max:,} €".replace(",", "\u202f"))
                else:
                    return ResultatMatching(False, -1, [], [f"prix {annonce.prix} € > max {prix_max} €"])
        except ValueError:
            logger.warning("Valeur prix_max invalide : %s", prix_max_str)

    prix_min_str = _val(criteres, "prix_min")
    if prix_min_str:
        try:
            prix_min = int(prix_min_str)
            if annonce.prix > 0 and annonce.prix < prix_min:
                return ResultatMatching(False, -1, [], [f"prix {annonce.prix} € < min {prix_min} €"])
        except ValueError:
            logger.warning("Valeur prix_min invalide : %s", prix_min_str)

    # --- Chambres (obligatoire, numérique) ---
    chambres_min_str = _val(criteres, "chambres_min")
    if chambres_min_str and annonce.chambres is not None:
        try:
            chambres_min = int(chambres_min_str)
            if annonce.chambres >= chambres_min:
                score += 10
                tags.append(f"{annonce.chambres} chambre(s)")
            else:
                return ResultatMatching(False, -1, [], [f"chambres {annonce.chambres} < min {chambres_min}"])
        except ValueError:
            logger.warning("Valeur chambres_min invalide : %s", chambres_min_str)

    # --- Arrondissements (obligatoire) ---
    arr_str = _val(criteres, "arrondissements")
    if arr_str:
        arrondissements = [a.strip() for a in arr_str.split(",") if a.strip()]
        if annonce.code_postal or annonce.adresse:
            if _check_arrondissement(annonce, arrondissements):
                score += 10
                tags.append(f"arr. {annonce.code_postal or annonce.adresse[:10]}")
            else:
                return ResultatMatching(False, -1, [], [f"arrondissement non souhaité : {annonce.code_postal}"])
        # Si pas d'info géo → ne pas rejeter, ne pas compter

    # --- Photos (obligatoire) ---
    photos_min_str = _val(criteres, "photos_min")
    if photos_min_str:
        try:
            photos_min = int(photos_min_str)
            nb_photos = len(annonce.photos)
            if nb_photos == 0:
                pass  # Inconnu → ne pas rejeter
            elif nb_photos >= photos_min:
                score += 10
                tags.append(f"{nb_photos} photos")
            else:
                return ResultatMatching(False, -1, [], [f"photos {nb_photos} < min {photos_min}"])
        except ValueError:
            pass

    # --- Bruit / calme ---
    bruit_critere = _val(criteres, "bruit")
    if bruit_critere and "silencieux" in bruit_critere.lower():
        prio = _prio(criteres, "bruit")
        if any(m in texte for m in MOTS_BRUYANT) and prio == "obligatoire":
            return ResultatMatching(False, -1, [], ["annonce indique bruyant/passant"])
        if any(m in texte for m in MOTS_CALME):
            score += 10 if prio == "obligatoire" else 5
            tags.append("calme")

    # --- Étage élevé ---
    etage_critere = _val(criteres, "etage")
    if etage_critere and "eleve" in etage_critere.lower():
        prio = _prio(criteres, "etage")
        etage_ok = (
            (annonce.etage is not None and annonce.etage >= 3)
            or any(m in texte for m in MOTS_ETAGE_ELEVE)
            or bool(re.search(r"[4-9]\s*[eè](?:me|r)?\s*étage|dernier\s*étage", texte))
        )
        if etage_ok:
            score += 10 if prio == "obligatoire" else 5
            tags.append("étage élevé")

    # --- Vue dégagée ---
    vue_critere = _val(criteres, "vue")
    if vue_critere and "degagee" in vue_critere.lower():
        prio = _prio(criteres, "vue")
        if any(m in texte for m in MOTS_VUE):
            score += 10 if prio == "obligatoire" else 5
            tags.append("vue dégagée")

    # --- Extérieur (terrasse/balcon) ---
    ext_critere = _val(criteres, "exterieur")
    if ext_critere and "terrasse" in ext_critere.lower():
        prio = _prio(criteres, "exterieur")
        if any(m in texte for m in MOTS_EXTERIEUR):
            score += 10 if prio == "obligatoire" else 5
            tags.append("terrasse/balcon")

    # --- Commerces ---
    commerce_critere = _val(criteres, "commerce_distance_max")
    if commerce_critere:
        if any(m in texte for m in MOTS_COMMERCES):
            score += 5
            tags.append("proches commerces")

    # --- Seuil final ---
    seuil = 30
    if score < seuil:
        rejets.append(f"score {score} < seuil {seuil}")
        return ResultatMatching(False, score, tags, rejets)

    return ResultatMatching(True, score, tags, [])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _val(criteres: dict, nom: str) -> str | None:
    """Retourne la valeur d'un critère, ou None si absent."""
    return criteres.get(nom, {}).get("valeur")


def _prio(criteres: dict, nom: str) -> str:
    """Retourne la priorité d'un critère (défaut : obligatoire)."""
    return criteres.get(nom, {}).get("priorite", "obligatoire")


def _check_arrondissement(annonce: Annonce, arrondissements: list[str]) -> bool:
    """Vérifie si l'annonce est dans l'un des arrondissements souhaités."""
    texte = f"{annonce.adresse} {annonce.code_postal or ''}".lower()
    for arr in arrondissements:
        arr = arr.strip()
        # Code postal : 13005, 13006…
        if len(arr) == 1:
            cp = f"1300{arr}"
        elif len(arr) == 2:
            cp = f"130{arr}"
        else:
            cp = arr
        if cp in texte:
            return True
        # Patterns textuels
        for pattern in [f"{arr}e ", f"{arr}ème", f"{arr}eme", f"marseille {arr}", f" {arr}e,"]:
            if pattern in texte:
                return True
    return False
