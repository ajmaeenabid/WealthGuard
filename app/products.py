import json
import os
from functools import lru_cache

from app.schemas import Product

DATA = os.path.join(os.path.dirname(__file__), "data")


@lru_cache(maxsize=1)
def load_products() -> dict[str, Product]:
    with open(os.path.join(DATA, "products.json"), encoding="utf-8") as f:
        return {p["id"]: Product(**p) for p in json.load(f)}


@lru_cache(maxsize=1)
def load_personas() -> dict[str, dict]:
    with open(os.path.join(DATA, "personas.json"), encoding="utf-8") as f:
        return {p["id"]: p for p in json.load(f)}
