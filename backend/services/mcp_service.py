"""
MCP (Model Context Protocol) Server Connectivity Service.
Connects to external MCP servers via JSON-RPC over HTTP to discover
and execute tools, resources, and prompts.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from shared.logger import get_logger

log = get_logger("mcp_service")


class MCPServerConnection:
    """Represents a connection to an external MCP server."""

    def __init__(self, name: str, url: str, headers: Optional[Dict[str, str]] = None):
        self.name = name
        self.url = url.rstrip("/")
        self.headers = headers or {}
        self._request_id = 0
        self._tools: List[Dict[str, Any]] = []
        self._resources: List[Dict[str, Any]] = []
        self._connected = False

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
        }
        if params:
            payload["params"] = params

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                self.url,
                json=payload,
                headers={**self.headers, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()

    async def initialize(self) -> bool:
        """Initialize the MCP connection and discover capabilities."""
        try:
            result = await self._request("initialize", {
                "protocolVersion": "0.1.0",
                "clientInfo": {"name": "jarvis-omega", "version": "1.0.0"},
            })
            self._connected = True

            # Discover tools
            tools_result = await self._request("tools/list")
            self._tools = tools_result.get("result", {}).get("tools", [])

            # Discover resources
            resources_result = await self._request("resources/list")
            self._resources = resources_result.get("result", {}).get("resources", [])

            log.info("mcp_server_initialized",
                     name=self.name, tools=len(self._tools), resources=len(self._resources))
            return True

        except Exception as e:
            log.error("mcp_initialize_failed", name=self.name, error=str(e))
            self._connected = False
            return False

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool on the MCP server."""
        if not self._connected:
            return {"success": False, "error": "Not connected to MCP server"}

        try:
            result = await self._request("tools/call", {
                "name": tool_name,
                "arguments": arguments,
            })
            result_data = result.get("result", {})
            log.info("mcp_tool_executed", server=self.name, tool=tool_name)
            return {
                "success": True,
                "content": result_data.get("content", []),
                "isError": result_data.get("isError", False),
            }
        except Exception as e:
            log.error("mcp_tool_failed", server=self.name, tool=tool_name, error=str(e))
            return {"success": False, "error": str(e)}

    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read a resource from the MCP server."""
        if not self._connected:
            return {"success": False, "error": "Not connected to MCP server"}

        try:
            result = await self._request("resources/read", {"uri": uri})
            result_data = result.get("result", {})
            return {"success": True, "contents": result_data.get("contents", [])}
        except Exception as e:
            log.error("mcp_resource_read_failed", server=self.name, uri=uri, error=str(e))
            return {"success": False, "error": str(e)}

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return self._tools

    @property
    def resources(self) -> List[Dict[str, Any]]:
        return self._resources

    @property
    def connected(self) -> bool:
        return self._connected

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "connected": self._connected,
            "tools": self._tools,
            "resources": self._resources,
        }


class MCPService:
    """
    Manages multiple MCP server connections.
    Provides a unified interface for discovering and executing tools
    across all connected servers.
    """

    def __init__(self):
        self._servers: Dict[str, MCPServerConnection] = {}
        self._config_file = Path("./storage/mcp_servers.json")
        self._load_config()

    async def add_server(self, name: str, url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Add and connect to a new MCP server."""
        if name in self._servers:
            return {"success": False, "error": f"Server '{name}' already registered"}

        connection = MCPServerConnection(name, url, headers)
        ok = await connection.initialize()
        if ok:
            self._servers[name] = connection
            self._save_config()
            return {"success": True, "server": connection.to_dict()}
        else:
            return {"success": False, "error": f"Failed to connect to {url}"}

    def remove_server(self, name: str) -> bool:
        """Remove an MCP server connection."""
        if name in self._servers:
            del self._servers[name]
            self._save_config()
            return True
        return False

    async def reconnect_server(self, name: str) -> Dict[str, Any]:
        """Reconnect to an existing MCP server."""
        if name not in self._servers:
            return {"success": False, "error": f"Server '{name}' not found"}
        connection = self._servers[name]
        ok = await connection.initialize()
        return {"success": ok, "server": connection.to_dict()}

    async def execute_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool on a specific MCP server."""
        server = self._servers.get(server_name)
        if not server:
            return {"success": False, "error": f"Server '{server_name}' not found"}
        return await server.execute_tool(tool_name, arguments)

    async def execute_tool_any(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool on the first server that provides it.
        Searches all connected servers.
        """
        for server in self._servers.values():
            for tool in server.tools:
                if tool.get("name") == tool_name:
                    if not server.connected:
                        await server.initialize()
                    return await server.execute_tool(tool_name, arguments)
        return {"success": False, "error": f"Tool '{tool_name}' not found on any connected server"}

    def list_servers(self) -> List[Dict[str, Any]]:
        """List all connected MCP servers and their capabilities."""
        return [s.to_dict() for s in self._servers.values()]

    def list_all_tools(self) -> List[Dict[str, Any]]:
        """List all available tools across all connected servers."""
        tools = []
        for server in self._servers.values():
            for tool in server.tools:
                tools.append({**tool, "server": server.name})
        return tools

    def _save_config(self) -> None:
        """Persist MCP server configurations."""
        try:
            data = []
            for name, server in self._servers.items():
                data.append({
                    "name": name,
                    "url": server.url,
                    "headers": server.headers,
                })
            self._config_file.parent.mkdir(parents=True, exist_ok=True)
            self._config_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.error("mcp_config_save_failed", error=str(e))

    def _load_config(self) -> None:
        """Load MCP server configurations from disk."""
        try:
            if self._config_file.exists():
                data = json.loads(self._config_file.read_text())
                for entry in data:
                    name = entry.get("name", "")
                    self._servers[name] = MCPServerConnection(
                        name=name,
                        url=entry.get("url", ""),
                        headers=entry.get("headers", {}),
                    )
        except Exception as e:
            log.error("mcp_config_load_failed", error=str(e))


mcp_service = MCPService()
