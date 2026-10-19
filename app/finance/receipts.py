"""Receipt photos attached to a transaction.

Security posture (there is no OCR and nothing is "read" from the image; it is stored so the person can look at it later):
  * the file type is decided by its bytes (JPEG, PNG or WebP), never by the file name or the Content-Type the browser sent
  * at most 2 MB per receipt and 200 per account; one receipt per transaction (a new one replaces it)
  * location and camera metadata (EXIF, XMP, PNG text chunks) is removed before storing
  * served only to the owner, with nosniff, a sandboxing CSP and no caching, so a crafted file can never run as a page
"""
import hashlib
import struct
from typing import Optional

from app import db, store
from app.finance import books
from app.finance.books import FinanceError, new_id

MAX_BYTES = 2_000_000
MAX_PER_USER = 200
TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def sniff(data: bytes) -> Optional[str]:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def strip_jpeg(data: bytes) -> bytes:
    """Drop APP1 (EXIF/XMP) and comment segments; everything else, including the picture data, is copied untouched."""
    out, i = bytearray(data[:2]), 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return data                                   # not a clean segment stream: keep the original rather than damage it
        marker = data[i + 1]
        if marker == 0xDA:                                # start of scan: the rest is image data
            out += data[i:]
            return bytes(out)
        if marker == 0xD9 or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out += data[i:i + 2]
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if length < 2 or i + 2 + length > len(data):
            return data
        if marker not in (0xE1, 0xFE):                    # keep everything except EXIF/XMP (APP1) and comments
            out += data[i:i + 2 + length]
        i += 2 + length
    return bytes(out)


def strip_png(data: bytes) -> bytes:
    out, i = bytearray(data[:8]), 8
    drop = {b"eXIf", b"tEXt", b"iTXt", b"zTXt", b"tIME"}
    while i + 12 <= len(data):
        length = struct.unpack(">I", data[i:i + 4])[0]
        kind = data[i + 4:i + 8]
        end = i + 12 + length
        if end > len(data):
            return data
        if kind not in drop:
            out += data[i:end]
        i = end
    return bytes(out)


def clean(data: bytes, mime: str) -> bytes:
    return strip_jpeg(data) if mime == "image/jpeg" else strip_png(data) if mime == "image/png" else data


def attach(user: str, txn_id: str, data: bytes, claimed: Optional[str] = None) -> dict:
    books.get_transaction(user, txn_id)                   # 404 for someone else's or a deleted transaction
    if not data:
        raise FinanceError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise FinanceError(f"The photo is too large (limit {MAX_BYTES // 1_000_000} MB). Take it at a lower resolution.", 413)
    mime = sniff(data)
    if mime is None:
        raise FinanceError("Only JPEG, PNG or WebP photos are accepted.", 415)
    if claimed and claimed.split(";")[0].strip().lower() not in (mime, "application/octet-stream"):
        raise FinanceError("The file content does not match its declared type.", 415)
    body = clean(data, mime)
    n = books._one("SELECT COUNT(*) AS n FROM fin_receipts WHERE username=? AND txn_id<>?", (user, txn_id))["n"]
    if n >= MAX_PER_USER:
        raise FinanceError(f"You have reached the limit of {MAX_PER_USER} receipts. Delete some to add more.", 409)
    rid = new_id("rcp")
    with db.LOCK:
        c = db.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM fin_receipts WHERE txn_id=? AND username=?", (txn_id, user))
            c.execute("INSERT INTO fin_receipts (id, username, txn_id, mime, size, sha256, data, created) VALUES (?,?,?,?,?,?,?,?)",
                      (rid, user, txn_id, mime, len(body), hashlib.sha256(body).hexdigest(), body, store.now()))
            c.execute("UPDATE fin_transactions SET receipt_ref=?, updated=? WHERE id=? AND username=?", (rid, store.now(), txn_id, user))
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()
    books._audit(user, "fin_receipt_attached", {"txn": txn_id, "bytes": len(body), "mime": mime})
    return {"id": rid, "txn_id": txn_id, "mime": mime, "size": len(body), "metadata_removed": len(body) < len(data)}


def get(user: str, txn_id: str) -> tuple[str, bytes]:
    r = books._one("SELECT mime, data FROM fin_receipts WHERE txn_id=? AND username=?", (txn_id, user))
    if not r:
        raise FinanceError("No receipt for this transaction.", 404)
    return r["mime"], bytes(r["data"])


def remove(user: str, txn_id: str) -> dict:
    books.get_transaction(user, txn_id)
    store._write("DELETE FROM fin_receipts WHERE txn_id=? AND username=?", (txn_id, user))
    store._write("UPDATE fin_transactions SET receipt_ref=NULL WHERE id=? AND username=?", (txn_id, user))
    books._audit(user, "fin_receipt_removed", {"txn": txn_id})
    return {"removed": txn_id}
