from fastapi import APIRouter, HTTPException, Query, status

from backend.vault.secure_vault import secure_vault
from shared.logger import get_logger

log = get_logger("vault_router")
router = APIRouter(prefix="/api/vault", tags=["Vault"])


@router.post("/store")
async def store_secret(key: str = Query(...), value: str = Query(...)):
    secure_vault.store(key, value)
    return {"status": "stored", "key": key}


@router.get("/retrieve/{key}")
async def retrieve_secret(key: str):
    value = secure_vault.retrieve(key)
    if value is None:
        raise HTTPException(status_code=404, detail="Key not found in vault")
    return {"key": key, "value": value}


@router.delete("/{key}")
async def delete_secret(key: str):
    success = secure_vault.delete(key)
    if not success:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"status": "deleted", "key": key}


@router.get("/keys")
async def list_keys():
    return {"keys": secure_vault.list_keys()}


@router.post("/migrate")
async def migrate_from_env():
    count = secure_vault.migrate_from_env()
    return {"migrated": count}
