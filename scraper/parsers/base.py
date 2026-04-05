from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Annonce:
    """Représente une annonce immobilière normalisée."""

    id: str                       # ID unique : {source}_{id_annonce}
    titre: str
    prix: int
    surface: float | None
    chambres: int | None
    pieces: int | None
    adresse: str
    code_postal: str | None
    description: str              # Texte complet de l'annonce
    photos: list[str]             # URLs des photos
    url: str                      # Lien vers l'annonce
    etage: int | None
    source: str                   # "leboncoin", "seloger", "bienici", "pap"
    date_publication: str | None
    tags_satisfaits: list[str] = field(default_factory=list)
    score: int = 0


class BaseParser(ABC):
    """Classe abstraite pour les parsers de sites immobiliers."""

    TIMEOUT: int = 15
    MAX_RETRIES: int = 3

    @abstractmethod
    def parse(self, url: str) -> list[Annonce]:
        """Parse une URL de recherche et retourne les annonces."""
        pass
