"""Comprehensive worldbuilding object models."""

from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from enum import Enum


# ===== FACTIONS =====
class FactionType(str, Enum):
    """Type of faction."""
    NATION = "nation"
    ORGANIZATION = "organization"
    RELIGION = "religion"
    TRIBE = "tribe"
    CORPORATION = "corporation"
    INDIVIDUAL = "individual"
    OTHER = "other"


class Faction(BaseModel):
    """A faction - can be nation, organization, or individual actor."""
    id: str
    name: str
    faction_type: FactionType
    description: str = ""
    leader: Optional[str] = None  # Character name or title
    founded_date: Optional[str] = None
    capital: Optional[str] = None  # For nations
    territory: List[str] = Field(default_factory=list)  # Planet/location names
    allies: List[str] = Field(default_factory=list)  # Faction IDs
    enemies: List[str] = Field(default_factory=list)  # Faction IDs
    resources: Dict[str, int] = Field(default_factory=dict)  # Resource name -> quantity
    government_type: Optional[str] = None
    military_strength: int = 0  # 0-100 scale
    economic_power: int = 0  # 0-100 scale
    notes: str = ""


# ===== PLANETS =====
class PlanetType(str, Enum):
    """Type of planet."""
    TERRESTRIAL = "terrestrial"
    GAS_GIANT = "gas_giant"
    ICE_GIANT = "ice_giant"
    DESERT = "desert"
    OCEAN = "ocean"
    JUNGLE = "jungle"
    ARCTIC = "arctic"
    VOLCANIC = "volcanic"
    ARTIFICIAL = "artificial"


class Moon(BaseModel):
    """A moon orbiting a planet."""
    name: str
    diameter: Optional[str] = None  # e.g., "3,474 km"
    mass: Optional[str] = None  # e.g., "7.34 × 10^22 kg"
    orbital_period: Optional[str] = None  # e.g., "27.3 days"
    orbital_distance: Optional[str] = None  # e.g., "384,400 km"
    tidally_locked: bool = False
    atmosphere: str = ""
    surface_features: str = ""  # Craters, maria, etc.
    description: str = ""


class Continent(BaseModel):
    """A continent on a planet."""
    name: str
    area: Optional[str] = None
    climate_zones: List[str] = Field(default_factory=list)
    major_cities: List[str] = Field(default_factory=list)
    population: Optional[int] = None
    terrain_description: str = ""
    notes: str = ""


class City(BaseModel):
    """A city on a continent."""
    name: str
    continent: str
    population: Optional[int] = None
    founded: Optional[str] = None
    government: Optional[str] = None
    economy_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    description: str = ""


class ClimateZone(BaseModel):
    """Climate zone with geographic boundaries."""
    zone_name: str  # Tropical, Temperate, Arctic, etc.
    latitude_start: Optional[float] = None  # Degrees north (positive) or south (negative)
    latitude_end: Optional[float] = None  # Degrees north (positive) or south (negative)
    temperature_range: Optional[str] = None  # e.g., "15°C to 35°C"
    precipitation: Optional[str] = None  # e.g., "2000mm annually"
    seasons: List[str] = Field(default_factory=list)
    weather_patterns: str = ""
    description: str = ""


class ClimatePreset(BaseModel):
    """Named climate preset that can be reused across planets."""
    id: str
    name: str  # e.g., "Earth-like", "Desert World", "Ice Planet"
    description: str = ""

    # Default climate zones for this preset
    default_zones: List[str] = Field(default_factory=list)  # e.g., ["Tropical", "Temperate", "Arctic"]

    # Climate characteristics
    temperature_range: Optional[str] = None  # e.g., "-50°C to 50°C"
    precipitation_pattern: Optional[str] = None  # e.g., "Seasonal monsoons"
    seasons: List[str] = Field(default_factory=list)  # e.g., ["Spring", "Summer", "Fall", "Winter"]
    atmospheric_composition: Optional[str] = None  # e.g., "78% N2, 21% O2"

    # Weather characteristics
    weather_patterns: str = ""  # General weather description
    extreme_events: List[str] = Field(default_factory=list)  # e.g., ["Hurricanes", "Tornadoes"]

    # Notes
    notes: str = ""


class Planet(BaseModel):
    """A planet with full details."""
    id: str
    name: str
    planet_type: PlanetType

    # Stellar System
    star_system: Optional[str] = None  # Name of the star system
    primary_star: Optional[str] = None  # Name of primary star
    secondary_stars: List[str] = Field(default_factory=list)  # Binary/trinary systems

    # Orbital Mechanics
    orbital_period: Optional[str] = None  # Year length, e.g., "365.25 days"
    year_length: Optional[str] = None  # Alternative to orbital_period
    rotation_period: Optional[str] = None  # Day length, e.g., "24 hours"
    day_length: Optional[str] = None  # Alternative to rotation_period
    orbital_distance: Optional[str] = None  # e.g., "1 AU" or "150 million km"
    orbital_eccentricity: Optional[str] = None  # e.g., "0.0167"
    axial_tilt: Optional[str] = None  # e.g., "23.5 degrees"
    retrograde_rotation: bool = False  # Rotates opposite to orbit direction
    in_habitable_zone: bool = False  # Within life-bearing zone of star

    # Physical Properties
    diameter: Optional[str] = None  # e.g., "12,742 km"
    mass: Optional[str] = None  # e.g., "5.97 × 10^24 kg"
    gravity: Optional[str] = None  # e.g., "9.8 m/s²" or "1.0 g"
    atmosphere: str = ""  # Atmospheric composition
    atmospheric_pressure: Optional[str] = None  # e.g., "1 atm" or "101.3 kPa"
    magnetic_field: Optional[str] = None  # e.g., "Strong" or "None"

    # Moons
    moons: List[Moon] = Field(default_factory=list)
    number_of_moons: int = 0  # Auto-calculated or manually set

    # Geography
    continents: List[Continent] = Field(default_factory=list)
    cities: List[City] = Field(default_factory=list)
    ocean_coverage: Optional[str] = None  # e.g., "71%"
    land_coverage: Optional[str] = None  # e.g., "29%"

    # Climate
    climate_zones: List[ClimateZone] = Field(default_factory=list)
    dominant_climate: Optional[str] = None

    # Life & Biology
    flora_species: List[str] = Field(default_factory=list)  # Flora IDs
    fauna_species: List[str] = Field(default_factory=list)  # Fauna IDs
    population: Optional[int] = None
    dominant_species: List[str] = Field(default_factory=list)
    factions: List[str] = Field(default_factory=list)  # Faction IDs

    # Visuals
    planet_image_path: Optional[str] = None
    map_image_path: Optional[str] = None

    description: str = ""
    notes: str = ""


class Star(BaseModel):
    """A star in a star system."""
    id: str
    name: str
    spectral_class: Optional[str] = None  # O, B, A, F, G, K, M (e.g., "G2V" for Sun)
    mass: Optional[str] = None  # e.g., "1.0 solar masses"
    radius: Optional[str] = None  # e.g., "696,000 km"
    temperature: Optional[str] = None  # e.g., "5,778 K"
    luminosity: Optional[str] = None  # e.g., "1.0 solar luminosities"
    age: Optional[str] = None  # e.g., "4.6 billion years"
    color: Optional[str] = None  # e.g., "Yellow", "Red", "Blue"
    description: str = ""
    notes: str = ""


class StarSystem(BaseModel):
    """A star system containing one or more stars and planets."""
    id: str
    name: str
    system_type: str = "single"  # single, binary, trinary, multiple

    # Stars in the system
    primary_star: Optional[str] = None  # Star ID
    companion_stars: List[str] = Field(default_factory=list)  # Star IDs for binary/multiple systems

    # Planets in the system
    planet_ids: List[str] = Field(default_factory=list)  # Planet IDs in this system

    # System properties
    galaxy: Optional[str] = None  # e.g., "Milky Way", "Andromeda", custom galaxy name
    location: Optional[str] = None  # e.g., "Orion Arm", "Galactic Core"
    distance_from_earth: Optional[str] = None  # e.g., "4.37 light years"

    # Habitable zone
    habitable_zone_inner: Optional[str] = None  # e.g., "0.95 AU"
    habitable_zone_outer: Optional[str] = None  # e.g., "1.37 AU"

    # Additional info
    description: str = ""
    notes: str = ""


# ===== HISTORY =====
class HistoricalEvent(BaseModel):
    """A historical event on a timeline."""
    id: str
    name: str
    date: str  # Can be any format the user wants
    timestamp: Optional[int] = None  # For sorting, optional numeric value
    event_type: str = "general"  # war, treaty, discovery, disaster, etc.
    key_figures: List[str] = Field(default_factory=list)  # Character names
    factions_involved: List[str] = Field(default_factory=list)  # Faction IDs
    location: Optional[str] = None  # Planet or place name
    description: str = ""
    consequences: str = ""
    related_events: List[str] = Field(default_factory=list)  # Event IDs


# ===== CHARACTER ENHANCEMENTS =====
class CharacterLifeEvent(BaseModel):
    """An event in a character's life."""
    date: str
    age: Optional[int] = None
    event_type: str = "general"  # birth, death, achievement, trauma, etc.
    title: str
    description: str = ""
    location: Optional[str] = None
    witnesses: List[str] = Field(default_factory=list)  # Other character names


class EnhancedCharacter(BaseModel):
    """Enhanced character with timeline and full details."""
    id: str
    name: str
    sex: Optional[str] = None
    gender: Optional[str] = None
    species: str = "human"
    birth_date: Optional[str] = None
    death_date: Optional[str] = None
    age: Optional[int] = None

    # Physical
    height: Optional[str] = None
    build: Optional[str] = None
    distinctive_features: str = ""

    # Background
    birthplace: Optional[str] = None
    current_location: Optional[str] = None
    occupation: Optional[str] = None
    social_class: Optional[str] = None

    # Affiliations
    faction: Optional[str] = None  # Faction ID
    allegiances: List[str] = Field(default_factory=list)  # Faction IDs

    # Personality & Relationships (from original model)
    personality: str = ""
    backstory: str = ""
    relationships: Dict[str, str] = Field(default_factory=dict)  # name -> relationship type

    # Timeline
    life_events: List[CharacterLifeEvent] = Field(default_factory=list)

    # Visuals
    image_path: Optional[str] = None

    notes: str = ""


# ===== MILITARY =====
class MilitaryBranch(BaseModel):
    """A branch of a military."""
    name: str
    branch_type: str  # Army, Navy, Air Force, Space Force, etc.
    size: Optional[int] = None
    commander: Optional[str] = None  # Character name
    equipment: List[str] = Field(default_factory=list)
    specialization: str = ""
    bases: List[str] = Field(default_factory=list)  # Location names


class Army(BaseModel):
    """A military force belonging to a faction."""
    id: str
    name: str
    faction_id: str
    total_strength: Optional[int] = None
    branches: List[MilitaryBranch] = Field(default_factory=list)
    allies: List[str] = Field(default_factory=list)  # Faction IDs
    enemies: List[str] = Field(default_factory=list)  # Faction IDs
    active_conflicts: List[str] = Field(default_factory=list)  # Conflict names
    victories: List[str] = Field(default_factory=list)
    defeats: List[str] = Field(default_factory=list)
    description: str = ""


# ===== ECONOMY =====
class EconomyType(str, Enum):
    """Type of economic system."""
    CAPITALIST = "capitalist"
    SOCIALIST = "socialist"
    FEUDAL = "feudal"
    BARTER = "barter"
    COMMAND = "command"
    MIXED = "mixed"
    POST_SCARCITY = "post_scarcity"


class Good(BaseModel):
    """A tradeable good or resource."""
    name: str
    category: str  # Raw material, manufactured, service, etc.
    value: Optional[float] = None
    unit: str = "units"
    produced_by: List[str] = Field(default_factory=list)  # Faction IDs
    consumed_by: List[str] = Field(default_factory=list)  # Faction IDs
    description: str = ""


class TradeRoute(BaseModel):
    """A trade route between factions."""
    from_faction: str  # Faction ID
    to_faction: str  # Faction ID
    goods: List[str] = Field(default_factory=list)  # Good names
    volume: Optional[float] = None
    value: Optional[float] = None
    route_type: str = "bilateral"  # bilateral, export, import


class Economy(BaseModel):
    """Economic system for a faction."""
    id: str
    faction_id: str
    economy_type: EconomyType
    currency: Optional[str] = None
    gdp: Optional[float] = None
    major_industries: List[str] = Field(default_factory=list)
    goods: List[Good] = Field(default_factory=list)
    trade_routes: List[TradeRoute] = Field(default_factory=list)
    trade_partners: List[str] = Field(default_factory=list)  # Faction IDs
    embargoes: List[str] = Field(default_factory=list)  # Faction IDs
    description: str = ""


# ===== POWER HIERARCHY =====
class HierarchyNode(BaseModel):
    """A node in a power hierarchy."""
    id: str
    title: str
    held_by: Optional[str] = None  # Character name
    faction: Optional[str] = None  # Faction ID
    parent_id: Optional[str] = None  # For tree structure
    children_ids: List[str] = Field(default_factory=list)
    power_level: int = 0  # 0-100
    responsibilities: List[str] = Field(default_factory=list)
    description: str = ""


class PowerHierarchy(BaseModel):
    """A complete power hierarchy structure."""
    id: str
    name: str
    hierarchy_type: str  # Government, Corporate, Religious, etc.
    faction_id: Optional[str] = None
    root_node_id: str  # Top of the hierarchy
    nodes: List[HierarchyNode] = Field(default_factory=list)
    allies: List[str] = Field(default_factory=list)  # Other hierarchy IDs
    enemies: List[str] = Field(default_factory=list)
    description: str = ""


# ===== POLITICS =====
class GovernmentBranch(BaseModel):
    """A branch of government."""
    id: str
    name: str
    branch_type: str  # Executive, Legislative, Judicial, etc.
    head: Optional[str] = None  # Character name or title
    members: List[str] = Field(default_factory=list)  # Character names
    powers: List[str] = Field(default_factory=list)
    headquarters: Optional[str] = None
    parent_branch_id: Optional[str] = None
    sub_branches: List[str] = Field(default_factory=list)  # Branch IDs
    description: str = ""


class PoliticalSystem(BaseModel):
    """A political system for a faction."""
    id: str
    faction_id: str
    system_type: str  # Democracy, Monarchy, Dictatorship, etc.
    constitution: str = ""
    branches: List[GovernmentBranch] = Field(default_factory=list)
    ruling_party: Optional[str] = None
    opposition_parties: List[str] = Field(default_factory=list)
    description: str = ""


# ===== TECHNOLOGY =====
class TechnologyType(str, Enum):
    """Technology type categories."""
    WEAPON = "weapon"
    TRANSPORTATION = "transportation"
    COMMUNICATION = "communication"
    MEDICAL = "medical"
    ENERGY = "energy"
    COMPUTING = "computing"
    AGRICULTURE = "agriculture"
    CONSTRUCTION = "construction"
    MANUFACTURING = "manufacturing"
    BIOTECHNOLOGY = "biotechnology"
    NANOTECHNOLOGY = "nanotechnology"
    ARTIFICIAL_INTELLIGENCE = "artificial_intelligence"
    SPACE = "space"
    OTHER = "other"


class Technology(BaseModel):
    """A technology or invention in the world."""
    id: str
    name: str
    technology_type: TechnologyType
    description: str = ""

    # Faction associations
    factions_with_access: List[str] = Field(default_factory=list)  # Faction IDs that have this tech
    inventor_faction: Optional[str] = None  # Faction ID that invented it

    # Impact ratings (0-100)
    game_changing_level: int = 50  # 0=benign, 100=game-changing
    destructive_level: int = 50  # 0=helpful, 100=destructive

    # Development info
    development_date: Optional[str] = None  # When it was invented
    tech_level: Optional[str] = None  # e.g., "Medieval", "Modern", "Future", "Sci-Fi"
    cost_to_build: str = ""  # Resources, time, money required to build/create
    prerequisites: List[str] = Field(default_factory=list)  # Other tech IDs needed first

    # Usage
    applications: List[str] = Field(default_factory=list)  # How it's used
    limitations: str = ""  # What it can't do
    side_effects: str = ""  # Unintended consequences

    # Story impact
    story_relevance: str = ""  # Why this matters to the plot
    notes: str = ""


# ===== MYTHOLOGY =====
class Myth(BaseModel):
    """A myth or legend."""
    id: str
    name: str
    myth_type: str  # Creation, Hero, Prophecy, etc.
    associated_factions: List[str] = Field(default_factory=list)  # Faction IDs
    key_figures: List[str] = Field(default_factory=list)  # deity/character names
    time_period: Optional[str] = None
    moral_lesson: str = ""
    description: str = ""
    full_text: str = ""


# ===== FLORA =====
class FloraType(str, Enum):
    """Types of plant life."""
    TREE = "tree"
    SHRUB = "shrub"
    FLOWER = "flower"
    GRASS = "grass"
    VINE = "vine"
    MOSS = "moss"
    FUNGUS = "fungus"
    AQUATIC_PLANT = "aquatic_plant"
    CARNIVOROUS_PLANT = "carnivorous_plant"
    CROP = "crop"
    HERB = "herb"
    MEDICINAL = "medicinal"
    TOXIC = "toxic"
    OTHER = "other"


class SpeciesInteraction(BaseModel):
    """Interaction between flora/fauna species."""
    species_id: str  # ID of the interacting species
    species_name: str  # Name for display
    interaction_type: str  # e.g., "preys on", "pollinated by", "symbiotic with", "competes with"
    description: str = ""  # Details of the interaction


class Flora(BaseModel):
    """A plant species in the world."""
    id: str
    name: str
    flora_type: FloraType
    description: str = ""

    # Classification
    scientific_name: Optional[str] = None
    common_names: List[str] = Field(default_factory=list)

    # Habitat
    native_planets: List[str] = Field(default_factory=list)  # Planet IDs or names
    preferred_climate: str = ""  # e.g., "tropical", "temperate", "arid"
    habitat: str = ""  # e.g., "forest floor", "canopy", "riverbanks"

    # Characteristics
    size: str = ""  # e.g., "10-15 meters tall", "ground cover"
    lifespan: str = ""  # e.g., "annual", "perennial", "1000+ years"
    growth_rate: str = ""  # e.g., "fast", "slow", "seasonal"
    appearance: str = ""  # Physical description

    # Special Properties
    edible: bool = False
    medicinal_properties: str = ""
    toxicity: str = ""  # If toxic, describe effects
    magical_properties: str = ""  # For fantasy settings
    economic_value: str = ""  # Trade/resource value

    # Interactions
    interactions: List[SpeciesInteraction] = Field(default_factory=list)

    # Story Relevance
    cultural_significance: str = ""  # Religious, symbolic meaning
    story_relevance: str = ""
    notes: str = ""


# ===== FAUNA =====
class FaunaType(str, Enum):
    """Types of animal life."""
    MAMMAL = "mammal"
    BIRD = "bird"
    REPTILE = "reptile"
    AMPHIBIAN = "amphibian"
    FISH = "fish"
    INSECT = "insect"
    ARACHNID = "arachnid"
    CRUSTACEAN = "crustacean"
    MOLLUSK = "mollusk"
    MYTHICAL_CREATURE = "mythical_creature"
    ALIEN_CREATURE = "alien_creature"
    PREDATOR = "predator"
    HERBIVORE = "herbivore"
    OMNIVORE = "omnivore"
    OTHER = "other"


class Fauna(BaseModel):
    """An animal species in the world."""
    id: str
    name: str
    fauna_type: FaunaType
    description: str = ""

    # Classification
    scientific_name: Optional[str] = None
    common_names: List[str] = Field(default_factory=list)

    # Habitat
    native_planets: List[str] = Field(default_factory=list)  # Planet IDs or names
    preferred_climate: str = ""  # e.g., "tropical", "arctic", "temperate"
    habitat: str = ""  # e.g., "forest", "ocean", "desert", "mountains"
    territory_size: str = ""  # e.g., "5 km radius", "migratory"

    # Physical Characteristics
    size: str = ""  # e.g., "2 meters long", "housecat-sized"
    weight: str = ""  # e.g., "50-70 kg"
    appearance: str = ""  # Physical description
    lifespan: str = ""  # e.g., "10-15 years"

    # Behavior
    diet: str = ""  # What they eat
    behavior: str = ""  # Behavioral patterns
    social_structure: str = ""  # e.g., "pack animal", "solitary", "herd"
    intelligence_level: str = ""  # e.g., "low", "moderate", "high", "sentient"
    reproduction: str = ""  # Reproductive info

    # Abilities
    special_abilities: List[str] = Field(default_factory=list)  # e.g., "flight", "camouflage", "venom"
    magical_properties: str = ""  # For fantasy settings

    # Threat Level
    danger_level: int = 0  # 0-100 scale
    domestication_status: str = ""  # e.g., "wild", "domesticated", "semi-domesticated"

    # Interactions
    interactions: List[SpeciesInteraction] = Field(default_factory=list)

    # Economic/Cultural Value
    economic_value: str = ""  # Hunt, trade, resources
    cultural_significance: str = ""  # Religious, symbolic meaning

    # Story Relevance
    story_relevance: str = ""
    notes: str = ""


# ===== COMPLETE WORLDBUILDING =====
class CompleteWorldBuilding(BaseModel):
    """Complete worldbuilding with all interconnected objects."""

    # Core systems
    factions: List[Faction] = Field(default_factory=list)

    # Planets & Space
    planets: List[Planet] = Field(default_factory=list)
    stars: List[Star] = Field(default_factory=list)

    # History
    historical_events: List[HistoricalEvent] = Field(default_factory=list)

    # Characters
    characters: List[EnhancedCharacter] = Field(default_factory=list)

    # Military
    armies: List[Army] = Field(default_factory=list)

    # Economy
    economies: List[Economy] = Field(default_factory=list)
    goods: List[Good] = Field(default_factory=list)

    # Power & Politics
    power_hierarchies: List[PowerHierarchy] = Field(default_factory=list)
    political_systems: List[PoliticalSystem] = Field(default_factory=list)

    # Mythology
    myths: List[Myth] = Field(default_factory=list)

    # Legacy text fields (for backwards compatibility)
    legacy_text: Dict[str, str] = Field(default_factory=dict)
