# ====================================================================
# JARVIS OMEGA — Project Code Scanner
# ====================================================================
"""
Scans codebase directories recursively, analyzes file dependencies,
uses AST parsing for Python code (detecting imports, classes, functions),
and constructs the codebase topology within the ProjectGraph.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import List, Dict, Set, Any, Optional

from shared.logger import get_logger
from shared.models import ProjectNode, ProjectInfo
from backend.project_graph import project_graph

log = get_logger("project_scanner")


class ProjectScanner:
    """
    Parses and indexes project files to populate the knowledge graph
    and detect architecture relationships and tech debt.
    """

    def __init__(self, workspace_path: str = "./workspace") -> None:
        self.workspace_path = Path(workspace_path)

    async def scan(self) -> ProjectInfo:
        """
        Scan workspace recursively, parsing files to construct
        nodes, dependencies, imports, classes, and functions.
        """
        log.info("starting_project_scan", workspace=str(self.workspace_path))
        
        project_graph.clear()
        
        if not self.workspace_path.exists():
            self.workspace_path.mkdir(parents=True, exist_ok=True)

        files_scanned = 0
        total_lines = 0
        dependencies: Set[str] = set()
        tech_debt: List[str] = []

        # List folders and files
        for root, dirs, files in os.walk(self.workspace_path):
            # Skip hidden folders, node_modules, venv, cache, etc.
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d not in ("node_modules", "venv", "__pycache__", "chromadb", "storage")
            ]

            root_path = Path(root)
            rel_root = root_path.relative_to(self.workspace_path)

            # Register folder node
            if root_path != self.workspace_path:
                folder_node = ProjectNode(
                    node_type="folder",
                    name=root_path.name,
                    path=str(rel_root.as_posix()),
                    metadata={"full_path": str(root_path.as_posix())},
                )
                project_graph.add_node(folder_node)

            for file in files:
                file_path = root_path / file
                rel_file = file_path.relative_to(self.workspace_path)
                ext = file_path.suffix

                # Skip binaries/logs/backups
                if ext in (".pyc", ".log", ".png", ".jpg", ".zip", ".tar", ".gz", ".db", ".sqlite"):
                    continue

                files_scanned += 1
                line_count = 0
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    line_count = len(content.splitlines())
                    total_lines += line_count
                except Exception as read_err:
                    log.error("file_read_error", file=str(rel_file), error=str(read_err))
                    continue

                # Create file node
                file_node = ProjectNode(
                    node_type="file",
                    name=file,
                    path=str(rel_file.as_posix()),
                    metadata={
                        "size_bytes": file_path.stat().st_size,
                        "line_count": line_count,
                        "extension": ext,
                    },
                )
                project_graph.add_node(file_node)

                # Link file to parent folder if applicable
                if root_path != self.workspace_path:
                    parent_node = project_graph.find_node_by_path(str(rel_root.as_posix()))
                    if parent_node:
                        project_graph.add_relationship(parent_node.node_id, file_node.node_id, "contains")

                # Parse Python files specifically using AST
                if ext == ".py":
                    await self._parse_python_ast(content, file_node, dependencies, tech_debt)

        # Build high-level ProjectInfo summary
        info = ProjectInfo(
            name=self.workspace_path.name or "JarvisWorkspace",
            path=str(self.workspace_path.absolute().as_posix()),
            language="Python",
            dependencies=list(dependencies),
            files_count=files_scanned,
            total_lines=total_lines,
            architecture_summary=f"Python project with {files_scanned} source files and {total_lines} lines of code.",
            tech_debt=tech_debt,
        )

        project_graph.set_project_info(info)
        await project_graph.save()

        log.info(
            "project_scan_complete",
            files=files_scanned,
            lines=total_lines,
            dependencies=len(dependencies),
            tech_debt=len(tech_debt),
        )
        return info

    async def _parse_python_ast(
        self,
        content: str,
        file_node: ProjectNode,
        dependencies: Set[str],
        tech_debt: List[str],
    ) -> None:
        """Parses Python source code AST to extract classes, functions, and imports."""
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            tech_debt.append(f"Syntax error in file: {file_node.path} at line {e.lineno}")
            return

        for node in ast.iter_child_nodes(tree):
            # Imports
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for name in node.names:
                    dep = name.name.split(".")[0]
                    if dep not in ("os", "sys", "json", "time", "datetime", "math", "typing", "collections", "hashlib", "asyncio"):
                        dependencies.add(dep)

            # Classes
            elif isinstance(node, ast.ClassDef):
                class_node = ProjectNode(
                    node_type="class",
                    name=node.name,
                    path=f"{file_node.path}::{node.name}",
                    metadata={
                        "lineno": node.lineno,
                        "bases": [b.id for b in node.bases if isinstance(b, ast.Name)],
                    },
                )
                project_graph.add_node(class_node)
                project_graph.add_relationship(file_node.node_id, class_node.node_id, "defines")

                # Parse methods inside the class
                for subnode in node.body:
                    if isinstance(subnode, ast.FunctionDef):
                        method_node = ProjectNode(
                            node_type="function",
                            name=subnode.name,
                            path=f"{class_node.path}.{subnode.name}",
                            metadata={"lineno": subnode.lineno, "args": [arg.arg for arg in subnode.args.args]},
                        )
                        project_graph.add_node(method_node)
                        project_graph.add_relationship(class_node.node_id, method_node.node_id, "defines")

                        # Simple code complexity heuristic
                        if len(subnode.body) > 40:
                            tech_debt.append(f"Complex method {subnode.name} in class {node.name} ({len(subnode.body)} statements)")

            # Top-level Functions
            elif isinstance(node, ast.FunctionDef):
                func_node = ProjectNode(
                    node_type="function",
                    name=node.name,
                    path=f"{file_node.path}::{node.name}",
                    metadata={"lineno": node.lineno, "args": [arg.arg for arg in node.args.args]},
                )
                project_graph.add_node(func_node)
                project_graph.add_relationship(file_node.node_id, func_node.node_id, "defines")

                if len(node.body) > 30:
                    tech_debt.append(f"Long function {node.name} in {file_node.path} ({len(node.body)} statements)")


# Global scanner instance
project_scanner = ProjectScanner()
