"""Registry of downloadable datasets for the knowledge store.

Each dataset has metadata (name, description, size estimate, URL, format)
so the UI can show an NLTK-downloader-style package manager.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DatasetInfo:
    """Metadata for a downloadable dataset."""
    id: str                          # Unique identifier
    name: str                        # Display name
    description: str                 # One-line description
    category: str                    # "encyclopedia", "culture", "geography", etc.
    size_estimate_mb: float          # Estimated download size in MB
    source_url: str                  # Where to download from
    format: str                      # "wikipedia_api", "huggingface", "csv", "json", "britannica_api"
    license: str = ""                # License info
    requires_api_key: bool = False   # Whether an API key is needed
    requires_package: str = ""       # Python package requirement (e.g. "wikipedia", "datasets")
    tags: List[str] = field(default_factory=list)


# Built-in dataset registry
DATASETS: List[DatasetInfo] = [
    # === Wikipedia ===
    DatasetInfo(
        id="wikipedia_project",
        name="Wikipedia: Articles for My Project",
        description="Automatically finds and downloads Wikipedia articles matching your characters, cultures, factions, places, and technologies",
        category="Encyclopedia",
        size_estimate_mb=10.0,
        source_url="https://en.wikipedia.org",
        format="wikipedia_project",
        license="CC BY-SA 3.0",
        requires_package="wikipedia",
        tags=["wikipedia", "worldbuilding", "project", "automatic"],
    ),
    DatasetInfo(
        id="wikipedia_curated",
        name="Wikipedia: Worldbuilding Essentials",
        description="~100 hand-picked articles on government, warfare, geography, mythology, and more",
        category="Encyclopedia",
        size_estimate_mb=5.0,
        source_url="https://en.wikipedia.org",
        format="wikipedia_api",
        license="CC BY-SA 3.0",
        requires_package="wikipedia",
        tags=["wikipedia", "worldbuilding", "reference"],
    ),
    DatasetInfo(
        id="wikipedia_simple",
        name="Wikipedia: Simple English (Full)",
        description="~200k articles from Simple English Wikipedia — great general reference",
        category="Encyclopedia",
        size_estimate_mb=200.0,
        source_url="https://huggingface.co/datasets/wikipedia",
        format="huggingface",
        license="CC BY-SA 3.0",
        requires_package="datasets",
        tags=["wikipedia", "encyclopedia", "general"],
    ),

    # === Britannica ===
    DatasetInfo(
        id="britannica",
        name="Encyclopaedia Britannica (API)",
        description="High-quality encyclopedia articles via Britannica's free API",
        category="Encyclopedia",
        size_estimate_mb=3.0,
        source_url="https://encyclopaediaapi.com",
        format="britannica_api",
        license="Non-commercial, 30-day cache",
        requires_api_key=True,
        tags=["britannica", "encyclopedia", "reference"],
    ),

    # === Cultural / Food ===
    DatasetInfo(
        id="oxai_world_dishes",
        name="OxAI World-Wide Dishes",
        description="Global dishes dataset — cuisine, ingredients, origin country, and cultural context",
        category="Culture & Food",
        size_estimate_mb=2.0,
        source_url="https://raw.githubusercontent.com/oxai/world-wide-dishes/main/data/WorldWideDishes_2024_June_World_Wide_Dishes.csv",
        format="csv",
        license="MIT",
        tags=["food", "cuisine", "culture", "worldbuilding"],
    ),

    # === Names & Language ===
    DatasetInfo(
        id="ssa_names",
        name="US Baby Names (1880–2023)",
        description="Historical name popularity — useful for character naming in period settings",
        category="Names & Language",
        size_estimate_mb=3.0,
        source_url="https://raw.githubusercontent.com/hadley/data-baby-names/master/baby-names.csv",
        format="csv",
        license="Public Domain",
        tags=["names", "characters", "historical", "culture"],
    ),

    # === Geography ===
    DatasetInfo(
        id="geonames_cities",
        name="GeoNames: World Cities (15k+)",
        description="Cities worldwide with population, coordinates, and country — place name inspiration",
        category="Geography",
        size_estimate_mb=2.0,
        source_url="https://download.geonames.org/export/dump/cities15000.zip",
        format="tsv_zip",
        license="CC BY 4.0",
        tags=["geography", "cities", "places", "worldbuilding"],
    ),

    # === Mythology ===
    DatasetInfo(
        id="pantheon_mythology",
        name="Pantheon: Historical Figures",
        description="15k+ historically notable people — inspiration for character backgrounds and titles",
        category="History & Mythology",
        size_estimate_mb=8.0,
        source_url="https://raw.githubusercontent.com/vlandeiro/pantheon/master/data/pantheon.tsv",
        format="tsv",
        license="MIT",
        tags=["history", "mythology", "characters", "biography"],
    ),
]


def get_dataset_by_id(dataset_id: str) -> Optional[DatasetInfo]:
    """Get dataset info by ID."""
    return next((d for d in DATASETS if d.id == dataset_id), None)


def get_datasets_by_category() -> dict:
    """Group datasets by category."""
    result = {}
    for d in DATASETS:
        result.setdefault(d.category, []).append(d)
    return result
