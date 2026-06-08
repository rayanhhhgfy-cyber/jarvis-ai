# ====================================================================
# JARVIS OMEGA — Project Knowledge Graph
# ====================================================================
"""
Maintains a semantic model of the codebase: folders, files, classes,
functions, API routes, database schemas, and external dependencies.
Tracks relationships (imports, calls, uses, definitions) and persists to disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Any

from shared.logger import get_logger
from shared.models import ProjectNode, ProjectInfo

log = get_logger("project_graph")


class ProjectGraph:
    """
    Knowledge graph containing structural nodes and semantic relationships
    representing codebase architecture.
    """

    def __init__(self, storage_dir: str = "./storage") -> None:
        self._nodes: Dict[str, ProjectNode] = {}
        self._storage_path = Path(storage_dir) / "project_graph.json"
        self._info: Optional[ProjectInfo] = None

    async def initialize(self) -> None:
        """Load stored graph from disk if available."""
        if self._storage_path.exists():
            try:
                data = json.loads(self._storage_path.read_text(encoding="utf-8"))
                self._nodes = {
                    node_data["node_id"]: ProjectNode(**node_data)
                    for node_data in data.get("nodes", [])
                }
                if "info" in data:
                    self._info = ProjectInfo(**data["info"])
                log.info("project_graph_loaded", nodes=len(self._nodes))
            except Exception as e:
                log.error("project_graph_load_error", error=str(e))

    async def save(self) -> None:
        """Persist graph structure to disk."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "nodes": [node.model_dump(mode="json") for node in self._nodes.values()],
                "info": self._info.model_dump(mode="json") if self._info else None,
            }
            self._storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            log.debug("project_graph_saved", nodes=len(self._nodes))
        except Exception as e:
            log.error("project_graph_save_failed", error=str(e))

    def add_node(self, node: ProjectNode) -> None:
        """Add or update a node in the graph."""
        self._nodes[node.node_id] = node

    def get_node(self, node_id: str) -> Optional[ProjectNode]:
        """Retrieve a node by its ID."""
        return self._nodes.get(node_id)

    def find_node_by_path(self, path: str) -> Optional[ProjectNode]:
        """Find a file or folder node by absolute or relative path."""
        for node in self._nodes.values():
            if node.path == path:
                return node
        return None

    def add_relationship(self, source_id: str, target_id: str, rel_type: str) -> bool:
        """Establish a directed relationship between two nodes."""
        source = self._nodes.get(source_id)
        target = self._nodes.get(target_id)
        if not source or not target:
            return False

        # Avoid duplicates
        for rel in source.relationships:
            if rel.get("target_id") == target_id and rel.get("type") == rel_type:
                return True

        source.relationships.append({
            "target_id": target_id,
            "target_name": target.name,
            "type": rel_type,
        })
        return True

    def remove_node(self, node_id: str) -> None:
        """Remove a node and all incoming/outgoing relationships."""
        self._nodes.pop(node_id, None)
        # Clean incoming relationships from other nodes
        for node in self._nodes.values():
            node.relationships = [
                rel for rel in node.relationships if rel.get("target_id") != node_id
            ]

    def clear(self) -> None:
        """Reset the graph structure."""
        self._nodes.clear()
        self._info = None

    def set_project_info(self, info: ProjectInfo) -> None:
        """Set high level scanned project metadata."""
        self._info = info
        # Also populate nodes array in ProjectInfo
        self._info.graph_nodes = list(self._nodes.values())

    def get_project_info(self) -> Optional[ProjectInfo]:
        """Retrieve high level project metadata."""
        if self._info:
            self._info.graph_nodes = list(self._nodes.values())
        return self._info

    def get_all_nodes(self) -> List[ProjectNode]:
        """Retrieve list of all graph nodes."""
        return list(self._nodes.values())


# Global project graph instance
project_graph = ProjectGraph()
