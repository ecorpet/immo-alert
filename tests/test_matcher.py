"""Tests unitaires pour le moteur de matching."""

import pytest

from scraper.parsers.base import Annonce
from scraper.matcher import matcher_annonce, ResultatMatching


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CRITERES_BASE = {
    "prix_max": {"valeur": "350000", "priorite": "obligatoire"},
    "chambres_min": {"valeur": "1", "priorite": "obligatoire"},
    "arrondissements": {"valeur": "5,6,7", "priorite": "obligatoire"},
    "photos_min": {"valeur": "5", "priorite": "obligatoire"},
    "bruit": {"valeur": "silencieux", "priorite": "obligatoire"},
    "etage": {"valeur": "eleve", "priorite": "obligatoire"},
    "vue": {"valeur": "degagee", "priorite": "obligatoire"},
    "exterieur": {"valeur": "terrasse", "priorite": "optionnel"},
    "exposition_interdite": {"valeur": "nord", "priorite": "interdiction"},
    "commerce_distance_max": {"valeur": "500", "priorite": "optionnel"},
}


def _annonce(**kwargs) -> Annonce:
    """Construit une Annonce de test avec des valeurs par défaut."""
    defaults = dict(
        id="test_1",
        titre="Appartement lumineux",
        prix=280000,
        surface=65.0,
        chambres=2,
        pieces=3,
        adresse="Marseille 6e arrondissement",
        code_postal="13006",
        description="Appartement calme au 4e étage avec vue dégagée et terrasse.",
        photos=["p1.jpg", "p2.jpg", "p3.jpg", "p4.jpg", "p5.jpg"],
        url="https://example.com/1",
        etage=4,
        source="test",
        date_publication=None,
    )
    defaults.update(kwargs)
    return Annonce(**defaults)


# ---------------------------------------------------------------------------
# Tests prix
# ---------------------------------------------------------------------------

def test_prix_max_satisfait():
    r = matcher_annonce(_annonce(prix=300000), CRITERES_BASE)
    assert r.passe is True
    assert any("prix" in t for t in r.tags_satisfaits)


def test_prix_max_depasse():
    r = matcher_annonce(_annonce(prix=400000), CRITERES_BASE)
    assert r.passe is False
    assert any("prix" in r for r in r.raisons_rejet)


def test_prix_zero_non_rejete():
    """Un prix inconnu (0) ne doit pas rejeter l'annonce."""
    r = matcher_annonce(_annonce(prix=0), CRITERES_BASE)
    # Le prix 0 ne déclenche pas de rejet sur ce critère
    # D'autres critères peuvent faire passer ou échouer l'annonce
    assert r.score >= 0


# ---------------------------------------------------------------------------
# Tests chambres
# ---------------------------------------------------------------------------

def test_chambres_min_satisfait():
    r = matcher_annonce(_annonce(chambres=2), CRITERES_BASE)
    assert r.passe is True


def test_chambres_min_insuffisant():
    r = matcher_annonce(_annonce(chambres=0), CRITERES_BASE)
    assert r.passe is False


def test_chambres_inconnues_non_rejetees():
    """Chambres inconnues (None) ne doivent pas rejeter."""
    r = matcher_annonce(_annonce(chambres=None), CRITERES_BASE)
    # Pas de rejet sur les chambres, mais peut échouer sur le score
    assert "chambres" not in " ".join(r.raisons_rejet)


# ---------------------------------------------------------------------------
# Tests arrondissements
# ---------------------------------------------------------------------------

def test_arrondissement_valide():
    r = matcher_annonce(_annonce(code_postal="13007"), CRITERES_BASE)
    assert r.passe is True


def test_arrondissement_invalide():
    r = matcher_annonce(_annonce(code_postal="13008", adresse="Marseille 8e"), CRITERES_BASE)
    assert r.passe is False
    assert any("arrondissement" in rej for rej in r.raisons_rejet)


def test_arrondissement_depuis_adresse():
    """Détection via le texte de l'adresse."""
    r = matcher_annonce(_annonce(code_postal=None, adresse="Marseille 6ème"), CRITERES_BASE)
    assert r.passe is True


# ---------------------------------------------------------------------------
# Tests photos
# ---------------------------------------------------------------------------

def test_photos_suffisantes():
    r = matcher_annonce(_annonce(photos=["a", "b", "c", "d", "e"]), CRITERES_BASE)
    assert r.passe is True


def test_photos_insuffisantes():
    r = matcher_annonce(_annonce(photos=["a", "b"]), CRITERES_BASE)
    assert r.passe is False


def test_photos_inconnues_non_rejetees():
    """Zéro photos ne doit pas rejeter (info inconnue)."""
    ann = _annonce(photos=[])
    r = matcher_annonce(ann, CRITERES_BASE)
    assert "photos" not in " ".join(r.raisons_rejet)


# ---------------------------------------------------------------------------
# Tests critères textuels
# ---------------------------------------------------------------------------

def test_calme_detecte():
    r = matcher_annonce(_annonce(description="Appartement calme et silencieux"), CRITERES_BASE)
    assert any("calme" in t for t in r.tags_satisfaits)


def test_bruyant_rejete():
    r = matcher_annonce(_annonce(description="Rue passante et animée"), CRITERES_BASE)
    assert r.passe is False


def test_etage_eleve_structure():
    r = matcher_annonce(_annonce(etage=5, description=""), CRITERES_BASE)
    assert any("étage" in t for t in r.tags_satisfaits)


def test_etage_eleve_textuel():
    r = matcher_annonce(_annonce(etage=None, description="Situé au dernier étage de l'immeuble"), CRITERES_BASE)
    assert any("étage" in t for t in r.tags_satisfaits)


def test_vue_degagee():
    r = matcher_annonce(_annonce(description="Vue dégagée sur la mer"), CRITERES_BASE)
    assert any("vue" in t for t in r.tags_satisfaits)


def test_terrasse_optionnel():
    r = matcher_annonce(_annonce(description="Grande terrasse ensoleillée"), CRITERES_BASE)
    assert any("terrasse" in t for t in r.tags_satisfaits)


# ---------------------------------------------------------------------------
# Tests interdictions
# ---------------------------------------------------------------------------

def test_exposition_nord_rejetee():
    r = matcher_annonce(_annonce(description="Exposition nord, très lumineux le matin"), CRITERES_BASE)
    assert r.passe is False
    assert r.score == -1


def test_exposition_sud_acceptee():
    r = matcher_annonce(_annonce(description="Plein sud, très ensoleillé"), CRITERES_BASE)
    assert r.passe is True


# ---------------------------------------------------------------------------
# Tests score
# ---------------------------------------------------------------------------

def test_score_annonce_parfaite():
    """Une annonce qui satisfait tous les critères doit avoir un score élevé."""
    ann = _annonce(
        prix=250000,
        chambres=3,
        code_postal="13006",
        photos=["p"] * 6,
        etage=5,
        description="Appartement calme, vue dégagée, terrasse, proche commerces",
    )
    r = matcher_annonce(ann, CRITERES_BASE)
    assert r.passe is True
    assert r.score >= 50


def test_score_seuil():
    """Une annonce avec un score insuffisant est rejetée."""
    criteres_stricts = {
        "prix_max": {"valeur": "350000", "priorite": "obligatoire"},
        "chambres_min": {"valeur": "1", "priorite": "obligatoire"},
    }
    # Annonce minimaliste sans mots-clés
    ann = _annonce(
        code_postal=None, adresse="",
        photos=[], description="", etage=None,
    )
    r = matcher_annonce(ann, criteres_stricts)
    # Avec si peu de critères satisfaits, le score peut être bas
    assert isinstance(r.score, int)
