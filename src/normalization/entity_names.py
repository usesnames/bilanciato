"""Entity-name normalization (crosswalk across sources).

The same organism is written differently in different tables, e.g.

    "FCT Holding S.p.A. e suo Gruppo"                              (p.55)
    "FCT HOLDING S.p.A. a socio unico ... (che consolida GTT)"     (p.132)
    "INFRA.TO S.r.l."  vs  "INFRATRASPORTI.TO S.r.l. a socio unico" (p.55 / p.131)

This module maps any raw name to a stable canonical (``slug``, ``display``) so
figures from different tables can be joined. Because aliases like
INFRA.TO/INFRATRASPORTI.TO can't be reconciled by string cleanup alone, matching
uses an explicit, ordered registry of distinctive patterns -- auditable and
deterministic. Parentheticals (``(società partecipata da Iren)``) are stripped
first so the subject of the name wins over entities merely mentioned in it.

Unmatched names are not dropped: they get a slug derived from the cleaned name,
so the crosswalk is total.
"""

from __future__ import annotations

import re
import unicodedata

# (slug, display name, distinctive pattern). Order matters: first match wins,
# so the subject of a name beats entities mentioned in a trailing clause.
_REGISTRY: list[tuple[str, str, str]] = [
    ("5t", "5T S.r.l.", r"\b5T\b"),
    ("afc_torino", "AFC Torino S.p.A.", r"\bAFC\b"),
    ("amiat", "AMIAT S.p.A.", r"\bAMIAT\b"),
    ("smat", "SMAT S.p.A. e suo Gruppo", r"\bSMAT\b"),
    ("trm", "TRM S.p.A.", r"\bTRM\b"),
    ("soris", "SORIS S.p.A.", r"\bSORIS\b"),
    ("lumiq", "LUMIQ S.r.l.", r"\bLUMIQ\b"),
    ("cct", "CCT S.r.l.", r"\bC\.?C\.?T\b"),
    ("fct_holding", "FCT Holding S.p.A. (consolida GTT)", r"\bFCT\b"),
    ("infratrasporti_to", "Infratrasporti.TO S.r.l.", r"\bINFRA"),
    ("iren", "IREN S.p.A. e suo Gruppo", r"\bIREN\b"),
    ("environment_park", "Environment Park S.p.A.", r"ENVIRONMENT PARK"),
    ("tne", "TNE S.p.A.", r"\bTNE\b"),
    ("turismo_torino", "Turismo Torino e Provincia S.c.ar.l.", r"TURISMO TORINO"),
    ("farmacie_comunali", "Farmacie Comunali Torino S.p.A.", r"FARMACIE COMUNALI"),
    ("agenzia_mobilita", "Agenzia della Mobilità Piemontese", r"MOBILIT"),
    ("csi_piemonte", "Consorzio CSI Piemonte", r"\bCSI\b|SISTEMA INFORMATIVO"),
    ("cit", "Consorzio Intercomunale Torino - CIT", r"INTERCOMUNALE TORINO|\bCIT\b"),
    ("ator", "Associazione d'Ambito Torinese - ATOR", r"\bATOR\b|D'AMBITO TORINESE"),
    ("abbonamento_musei", "Associazione Abbonamento Musei", r"ABBONAMENTO MUSEI"),
    ("urban_lab", "Associazione Urban Lab", r"URBAN LAB"),
    ("torino_musei", "Fondazione Torino Musei", r"TORINO MUSEI"),
    ("fondazione_cultura", "Fondazione per la Cultura Torino", r"PER LA CULTURA"),
    ("teatro_regio", "Fondazione Teatro Regio di Torino", r"TEATRO REGIO"),
    ("teatro_stabile", "Fondazione Teatro Stabile di Torino", r"TEATRO STABILE"),
    ("film_commission", "Fondazione Film Commission Torino-Piemonte", r"FILM COMMISSION"),
    ("museo_egizio", "Fondazione Museo delle Antichità Egizie", r"ANTICHIT"),
    ("piemonte_innova", "Fondazione Piemonte Innova", r"PIEMONTE INNOVA"),
    ("polo_900", "Fondazione Polo del '900", r"POLO DEL"),
    ("prolo", "Fondazione Prolo - Museo del Cinema", r"PROLO"),
    ("venaria_reale", "Fondazione La Venaria Reale", r"VENARIA"),
    ("cavour", "Fondazione Cavour", r"CAVOUR"),
    ("stadio_filadelfia", "Fondazione Stadio Filadelfia", r"FILADELFIA"),
    ("fond_20_marzo", "Fondazione 20 Marzo 2006 - TOP", r"20 MARZO"),
    ("cascina_roccafranca", "Fondazione Cascina Roccafranca", r"ROCCAFRANCA"),
    ("contrada_torino", "Fondazione Contrada Torino", r"CONTRADA TORINO"),
    ("porta_palazzo", "Comitato Progetto Porta Palazzo - The Gate", r"PORTA PALAZZO"),
    ("iter", "Istituzione ITER", r"\bITER\b"),
    ("gtt", "GTT S.p.A.", r"\bGTT\b"),
]


def _clean(raw: str) -> str:
    """Uppercase, drop parentheticals, normalize accents/punctuation."""
    no_paren = re.sub(r"\([^)]*\)", " ", raw)
    folded = unicodedata.normalize("NFKD", no_paren)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = folded.replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", folded.upper()).strip()


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def canonicalize(raw: str) -> tuple[str, str]:
    """Map a raw entity name to a (slug, display_name) canonical pair."""
    cleaned = _clean(raw)
    for slug, display, pattern in _REGISTRY:
        if re.search(pattern, cleaned):
            return slug, display
    # Total fallback: derive a slug from the cleaned name, keep raw as display.
    core = re.split(r"\bS\.?P\.?A\.?\b|\bS\.?R\.?L\.?\b|\bS\.?C\.?AR", cleaned)[0].strip()
    return _slugify(core) or _slugify(cleaned), raw.strip()
