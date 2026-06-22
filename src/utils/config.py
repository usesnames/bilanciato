"""Project paths and document-layout profiles.

A *profile* declares, for a known document type, which page ranges hold which
financial statement. Keeping this explicit (rather than guessing) is what makes
extraction reproducible: the same PDF always yields the same tables.

Page ranges are 1-based and inclusive, matching how a human reads the PDF.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --- Project paths ---------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "uploads"
EXTRACTED = ROOT / "extracted"
NORMALIZED = ROOT / "normalized"
DATABASE = ROOT / "database"
DB_PATH = DATABASE / "bilanciato.duckdb"
# Static, publishable data site (HTML + JSON/CSV + llms.txt) for LLM/agent access.
SITE = ROOT / "site"


@dataclass(frozen=True)
class StatementSection:
    """One contiguous statement within a document."""

    table_type: str  # canonical type, see CLAUDE.md "Supported table types"
    page_start: int  # 1-based inclusive
    page_end: int  # 1-based inclusive

    def pages(self) -> list[int]:
        return list(range(self.page_start, self.page_end + 1))


@dataclass(frozen=True)
class DocumentProfile:
    """Layout of a known document type/year."""

    document_type: str
    year: int
    sections: list[StatementSection] = field(default_factory=list)
    # 1-based inclusive pages holding the consolidation-area entity table
    # (Gruppo Amministrazione Pubblica). Empty if the document has none.
    entity_pages: tuple[int, ...] = ()
    # per-entity "ulteriori dati" table (personnel cost, consolidation %, ...)
    personnel_pages: tuple[int, ...] = ()
    # participation-valuation tables (carrying value vs net equity)
    valuation_pages: tuple[int, ...] = ()
    # nota integrativa detail-table pages (movimenti / confronto / dettaglio)
    note_pages: tuple[int, ...] = ()
    # Physical layout of the per-entity tables (personnel + valuation):
    #   "inline" -- one row per entity (2022-2024)
    #   "paired" -- a name row followed by a value row (2021)
    entity_table_layout: str = "inline"
    # For the "paired" layout: which valuation pages hold the *indirect* table.
    valuation_indirect_pages: tuple[int, ...] = ()


# Layout of: DEL-550-2025_Allegato_1_Bilancio_Consolidato_2024.pdf
# Verified by scanning the per-page headers (see notebooks / extraction logs).
BILANCIO_CONSOLIDATO_2024 = DocumentProfile(
    document_type="bilancio_consolidato",
    year=2024,
    sections=[
        # The "SCHEMA ..." page of each statement already carries the first line
        # items (codes 1..n), so the section must start there, not on the next
        # page -- otherwise the opening voci are silently dropped.
        StatementSection("income_statement", 4, 8),
        StatementSection("balance_sheet_assets", 10, 15),
        StatementSection("balance_sheet_liabilities", 16, 19),
        # Pre-consolidation provisional aggregate (sum of group members'
        # statements before intercompany eliminations). Single-valued.
        StatementSection("aggregate_income_statement", 57, 59),
        StatementSection("aggregate_balance_sheet_assets", 60, 63),
        StatementSection("aggregate_balance_sheet_liabilities", 64, 66),
    ],
    entity_pages=(24, 25),
    personnel_pages=(55,),
    valuation_pages=(131, 132, 133),
    note_pages=tuple(range(37, 52)),
)

# Layout of: DEL-563-2024 Allegato 1_Bilancio Consolidato 2023.pdf
BILANCIO_CONSOLIDATO_2023 = DocumentProfile(
    document_type="bilancio_consolidato",
    year=2023,
    sections=[
        StatementSection("income_statement", 4, 8),
        StatementSection("balance_sheet_assets", 10, 15),
        StatementSection("balance_sheet_liabilities", 16, 19),
        StatementSection("aggregate_income_statement", 56, 57),
        StatementSection("aggregate_balance_sheet_assets", 58, 59),
        StatementSection("aggregate_balance_sheet_liabilities", 60, 61),
    ],
    entity_pages=(24, 25),
    personnel_pages=(53, 54),
    valuation_pages=(125, 126, 127),
    note_pages=tuple(range(36, 53)),
)

# Layout of: DEL-599-2023-All.to_n._2_Bilancio_Consolidato_2022.pdf
BILANCIO_CONSOLIDATO_2022 = DocumentProfile(
    document_type="bilancio_consolidato",
    year=2022,
    sections=[
        StatementSection("income_statement", 4, 8),
        StatementSection("balance_sheet_assets", 10, 15),
        StatementSection("balance_sheet_liabilities", 16, 19),
        StatementSection("aggregate_income_statement", 52, 54),
        StatementSection("aggregate_balance_sheet_assets", 55, 58),
        StatementSection("aggregate_balance_sheet_liabilities", 59, 60),
    ],
    entity_pages=(23, 24),
    personnel_pages=(49, 50),
    valuation_pages=(119, 120, 121),
    note_pages=tuple(range(31, 49)),
)

# Layout of: ALLEGATO_1_Del2022_644_Bilancio_Consolidato_2021.pdf
# This report has extra cover/index pages (everything is shifted ~+6 vs 2022)
# and lays out both per-entity tables (personnel + valuation) as paired
# name/value rows rather than one row per entity -- hence entity_table_layout.
BILANCIO_CONSOLIDATO_2021 = DocumentProfile(
    document_type="bilancio_consolidato",
    year=2021,
    sections=[
        StatementSection("income_statement", 10, 14),
        StatementSection("balance_sheet_assets", 16, 21),
        StatementSection("balance_sheet_liabilities", 22, 26),
        StatementSection("aggregate_income_statement", 59, 62),
        StatementSection("aggregate_balance_sheet_assets", 63, 66),
        StatementSection("aggregate_balance_sheet_liabilities", 67, 69),
    ],
    entity_pages=(30, 31, 32),
    personnel_pages=(57, 58),
    valuation_pages=(134, 135),
    note_pages=tuple(range(39, 54)),
    entity_table_layout="paired",
    valuation_indirect_pages=(135,),
)

# Registry of known documents, keyed by filename.
PROFILES: dict[str, DocumentProfile] = {
    "DEL-550-2025_Allegato_1_Bilancio_Consolidato_2024.pdf": BILANCIO_CONSOLIDATO_2024,
    "DEL-563-2024 Allegato 1_Bilancio Consolidato 2023.pdf": BILANCIO_CONSOLIDATO_2023,
    "DEL-599-2023-All.to_n._2_Bilancio_Consolidato_2022.pdf": BILANCIO_CONSOLIDATO_2022,
    "ALLEGATO_1_Del2022_644_Bilancio_Consolidato_2021.pdf": BILANCIO_CONSOLIDATO_2021,
}


# --- Rendiconto della gestione (conto del bilancio) ------------------------
@dataclass(frozen=True)
class RendicontoProfile:
    """Layout of a *rendiconto della gestione* PDF (Comune di Torino, standalone).

    We extract the two summary tables of the conto del bilancio (Allegato n.10):
    the per-titolo revenue riepilogo and the per-missione spending riepilogo.
    Page ranges are 1-based inclusive and span from the riepilogo's first page
    through its "TOTALE GENERALE ..." page.
    """

    document_type: str
    year: int
    entrate_pages: tuple[int, int]  # (start, end) of RIEPILOGO GENERALE DELLE ENTRATE
    spese_missioni_pages: tuple[int, int]  # (start, end) of RIEPILOGO ... SPESE PER MISSIONI


RENDICONTO_PROFILES: dict[str, RendicontoProfile] = {
    "All. 1 Rendiconto 2021 TESTO INTEGRATO.pdf": RendicontoProfile(
        "rendiconto_gestione", 2021, (10, 11), (44, 47)),
    "All. n. 1 Rendiconto 2022.pdf": RendicontoProfile(
        "rendiconto_gestione", 2022, (8, 9), (42, 45)),
    "All. n. 1 Rendiconto 2023_249.pdf": RendicontoProfile(
        "rendiconto_gestione", 2023, (10, 11), (45, 48)),
    "All. n.  1 Rendiconto 2024.pdf": RendicontoProfile(
        "rendiconto_gestione", 2024, (10, 11), (45, 48)),
    "All. n. 1 Rendiconto 2025.pdf": RendicontoProfile(
        "rendiconto_gestione", 2025, (10, 11), (44, 47)),
}
