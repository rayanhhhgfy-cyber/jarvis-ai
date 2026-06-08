from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from backend.services.browser_service import browser_service
from shared.logger import get_logger

log = get_logger("router_browser")
router = APIRouter(prefix="/api/browser", tags=["Browser"])


class NavigateRequest(BaseModel):
    url: str
    timeout: int = 30000


class Interaction(BaseModel):
    type: str
    selector: Optional[str] = None
    value: Optional[str] = None


class InteractRequest(BaseModel):
    url: str
    actions: List[Interaction]
    timeout: int = 30000


class JSRequest(BaseModel):
    script: str


class SelectorRequest(BaseModel):
    selector: str


class TypeRequest(BaseModel):
    selector: str
    text: str


class KeyRequest(BaseModel):
    key: str


class TextRequest(BaseModel):
    text: str


@router.post("/navigate")
async def navigate(req: NavigateRequest):
    result = await browser_service.navigate(req.url, timeout=req.timeout)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Browser navigation failed"))
    return result


@router.post("/interact")
async def interact(req: InteractRequest):
    actions = [a.model_dump() for a in req.actions]
    result = await browser_service.interact(req.url, actions, timeout=req.timeout)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Browser interaction failed"))
    return result


@router.post("/execute-js")
async def execute_js(req: JSRequest):
    result = await browser_service.execute_js(req.script)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "JS execution failed"))
    return result


@router.post("/get-text")
async def get_text(req: SelectorRequest):
    result = await browser_service.get_text(req.selector)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to get text"))
    return result


@router.post("/click")
async def click(req: SelectorRequest):
    result = await browser_service.click(req.selector)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Click failed"))
    return result


@router.post("/type")
async def type_text(req: TypeRequest):
    result = await browser_service.type_text(req.selector, req.text)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Type failed"))
    return result


@router.post("/type-focused")
async def type_focused(req: TextRequest):
    """Type text into the currently focused element."""
    result = await browser_service.type_text(":focus", req.text)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Type failed"))
    return result


@router.post("/press")
async def press_key(req: KeyRequest):
    result = await browser_service.press_key(req.key)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Key press failed"))
    return result


@router.post("/screenshot")
async def screenshot():
    result = await browser_service.screenshot()
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Screenshot failed"))
    return result
