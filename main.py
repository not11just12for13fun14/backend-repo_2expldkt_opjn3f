import os
from typing import List, Optional, Any, Dict

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document
from schemas import Deck, DeckCard

app = FastAPI(title="MTG Deck Builder API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Utils
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)


def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    doc = dict(doc)
    if doc.get("_id"):
        doc["id"] = str(doc.pop("_id"))
    # Convert any ObjectIds nested (defensive)
    for k, v in list(doc.items()):
        if isinstance(v, ObjectId):
            doc[k] = str(v)
        if isinstance(v, list):
            doc[k] = [str(x) if isinstance(x, ObjectId) else x for x in v]
    return doc


# Scryfall helpers
SCRYFALL_API = "https://api.scryfall.com"


def _face_images(face: Dict[str, Any]) -> Dict[str, Optional[str]]:
    img_small = face.get("image_uris", {}).get("small") if face.get("image_uris") else None
    img_normal = face.get("image_uris", {}).get("normal") if face.get("image_uris") else None
    return {
        "small": img_small,
        "normal": img_normal,
    }


def map_scryfall_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """Return a UI-friendly subset including front/back images when present."""
    image_front_small = None
    image_front_normal = None
    image_back_small = None
    image_back_normal = None

    if card.get("image_uris"):
        image_front_small = card["image_uris"].get("small")
        image_front_normal = card["image_uris"].get("normal")
    elif card.get("card_faces") and len(card["card_faces"]) > 0:
        face0 = card["card_faces"][0]
        imgs0 = _face_images(face0)
        image_front_small = imgs0["small"]
        image_front_normal = imgs0["normal"]

    # Back face
    if card.get("card_faces") and len(card["card_faces"]) > 1:
        face1 = card["card_faces"][1]
        imgs1 = _face_images(face1)
        image_back_small = imgs1["small"]
        image_back_normal = imgs1["normal"]

    # Text fields prefer full card fields, fallback to first face
    mana_cost = card.get("mana_cost")
    type_line = card.get("type_line")
    oracle_text = card.get("oracle_text")
    colors = card.get("colors")

    if not mana_cost and card.get("card_faces"):
        mana_cost = card["card_faces"][0].get("mana_cost")
    if not type_line and card.get("card_faces"):
        type_line = card["card_faces"][0].get("type_line")
    if not oracle_text and card.get("card_faces"):
        oracle_text = card["card_faces"][0].get("oracle_text")

    return {
        "scryfall_id": card.get("id"),
        "name": card.get("name"),
        "mana_cost": mana_cost,
        "type_line": type_line,
        "oracle_text": oracle_text,
        "colors": colors,
        "image_small": image_front_small,  # legacy field used by UI
        "image_front_small": image_front_small,
        "image_front_normal": image_front_normal,
        "image_back_small": image_back_small,
        "image_back_normal": image_back_normal,
        "has_back": bool(image_back_small or image_back_normal),
    }


@app.get("/")
def read_root():
    return {"message": "MTG Deck Builder API is running"}


@app.get("/api/cards/search")
def search_cards(q: str, page: int = 1) -> Dict[str, Any]:
    """Proxy search to Scryfall, returning trimmed results for UI."""
    try:
        resp = requests.get(f"{SCRYFALL_API}/cards/search", params={"q": q, "page": page}, timeout=10)
        if resp.status_code != 200:
            try:
                detail = resp.json().get("details", "Scryfall error")
            except Exception:
                detail = "Scryfall error"
            raise HTTPException(status_code=resp.status_code, detail=detail)
        data = resp.json()
        mapped = [map_scryfall_card(c) for c in data.get("data", [])]
        return {
            "object": "list",
            "total_cards": data.get("total_cards"),
            "has_more": data.get("has_more", False),
            "next_page": data.get("next_page"),
            "data": mapped,
        }
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="Scryfall request timed out")


@app.get("/api/cards/{scryfall_id}")
def get_card(scryfall_id: str) -> Dict[str, Any]:
    resp = requests.get(f"{SCRYFALL_API}/cards/{scryfall_id}", timeout=10)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Card not found")
    card = resp.json()
    return map_scryfall_card(card)


# Deck endpoints
@app.post("/api/decks")
def create_deck(deck: Deck) -> Dict[str, str]:
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    deck_id = create_document("deck", deck)
    return {"id": deck_id}


@app.get("/api/decks")
def list_decks() -> List[Dict[str, Any]]:
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    docs = db["deck"].find().sort("updated_at", -1)
    return [serialize_doc(d) for d in docs]


@app.get("/api/decks/{deck_id}")
def get_deck(deck_id: str) -> Dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    doc = db["deck"].find_one({"_id": ObjectId(deck_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Deck not found")
    return serialize_doc(doc)


class DeckUpdate(BaseModel):
    name: Optional[str] = None
    format: Optional[str] = None
    description: Optional[str] = None
    cards: Optional[List[DeckCard]] = None


@app.put("/api/decks/{deck_id}")
def update_deck(deck_id: str, payload: DeckUpdate) -> Dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    update_doc: Dict[str, Any] = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not update_doc:
        return {"updated": False}
    # naive timestamp update
    try:
        from datetime import datetime
        update_doc["updated_at"] = datetime.utcnow()
    except Exception:
        pass
    res = db["deck"].update_one({"_id": ObjectId(deck_id)}, {"$set": update_doc})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Deck not found")
    return {"updated": res.modified_count > 0}


@app.delete("/api/decks/{deck_id}")
def delete_deck(deck_id: str) -> Dict[str, bool]:
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    res = db["deck"].delete_one({"_id": ObjectId(deck_id)})
    return {"deleted": res.deleted_count > 0}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
