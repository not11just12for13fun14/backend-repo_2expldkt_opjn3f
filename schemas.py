"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal

# MTG Deck Builder Schemas

class DeckCard(BaseModel):
    """A single card entry in a deck"""
    scryfall_id: str = Field(..., description="Scryfall card ID")
    name: str = Field(..., description="Card name")
    quantity: int = Field(1, ge=1, le=99, description="Number of copies")
    mana_cost: Optional[str] = Field(None, description="Mana cost string from Scryfall")
    type_line: Optional[str] = Field(None, description="Type line from Scryfall")
    colors: Optional[List[str]] = Field(default=None, description="List of colors from Scryfall")
    image_small: Optional[str] = Field(default=None, description="Small image URL for display")
    image_front_small: Optional[str] = Field(default=None)
    image_back_small: Optional[str] = Field(default=None)
    cmc: Optional[float] = Field(default=None, description="Converted mana cost (Scryfall cmc)")
    color_identity: Optional[List[str]] = Field(default=None, description="Scryfall color identity")

class Deck(BaseModel):
    """Deck collection schema (collection name: deck)"""
    name: str = Field(..., min_length=1, max_length=120, description="Deck name")
    format: Optional[Literal[
        "commander",
        "modern",
        "standard",
        "pioneer",
        "legacy",
        "vintage",
        "pauper",
        "brawl",
        "historic",
        "casual"
    ]] = Field(default="casual", description="Intended play format")
    description: Optional[str] = Field(default=None, max_length=500)
    cards: List[DeckCard] = Field(default_factory=list, description="List of cards in the deck")
    # Commander-specific metadata (optional)
    commander_id: Optional[str] = Field(default=None, description="Scryfall ID of the commander")
    commander_name: Optional[str] = Field(default=None)
    commander_colors: Optional[List[str]] = Field(default=None, description="Commander color identity (WUBRG)")

# Example schemas (kept for reference)
class User(BaseModel):
    name: str
    email: str
    address: str
    age: Optional[int] = None
    is_active: bool = True

class Product(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    category: str
    in_stock: bool = True
