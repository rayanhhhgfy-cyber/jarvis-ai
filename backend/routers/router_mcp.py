"""
MCP Server Connectivity Router.
REST endpoints to manage MCP server connections and execute tools.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.mcp_service import mcp_service
from shared.logger import get_logger

log = get_logger("router_mcp")
router = APIRouter(prefix="/api/mcp", tags=["MCP"])


class AddServerRequest(BaseModel):
    name: str
    url: str
    headers: Optional[Dict[str, str]] = None


class ExecuteToolRequest(BaseModel):
    server: str = ""
    tool: str
    arguments: Dict[str, Any] = {}


@router.get("/servers")
async def list_mcp_servers() -> Dict[str, Any]:
    """List all connected MCP servers."""
    servers = mcp_service.list_servers()
    return {"servers": servers, "count": len(servers)}


@router.post("/servers")
async def add_mcp_server(req: AddServerRequest) -> Dict[str, Any]:
    """Add and connect to a new MCP server."""
    result = await mcp_service.add_server(req.name, req.url, req.headers)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to add server"))
    return result


@router.delete("/servers/{name}")
async def remove_mcp_server(name: str) -> Dict[str, Any]:
    """Remove an MCP server connection."""
    success = mcp_service.remove_server(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")
    return {"status": "removed", "name": name}


@router.post("/servers/{name}/reconnect")
async def reconnect_mcp_server(name: str) -> Dict[str, Any]:
    """Reconnect to an MCP server."""
    result = await mcp_service.reconnect_server(name)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to reconnect"))
    return result


@router.get("/tools")
async def list_all_tools() -> Dict[str, Any]:
    """List all tools available across all connected MCP servers."""
    tools = mcp_service.list_all_tools()
    return {"tools": tools, "count": len(tools)}


@router.post("/tools/execute")
async def execute_mcp_tool(req: ExecuteToolRequest) -> Dict[str, Any]:
    """Execute a tool on an MCP server."""
    if req.server:
        result = await mcp_service.execute_tool(req.server, req.tool, req.arguments)
    else:
        result = await mcp_service.execute_tool_any(req.tool, req.arguments)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Tool execution failed"))
    return result


@router.post("/tools/call")
async def call_mcp_tool(req: ExecuteToolRequest) -> Dict[str, Any]:
    """Alias for execute tool."""
    return await execute_mcp_tool(req)
