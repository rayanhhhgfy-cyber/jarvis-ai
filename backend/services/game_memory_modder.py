"""
Game Memory Modder — read-only Android procfs process memory inspector.

# TERMUX-NOTE: Android only. procfs access requires root or /proc/self/.
#             This is a read-only inspector, not a memory patcher.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from shared.logger import get_logger

log = get_logger("game_memory_modder")


@dataclass
class ProcessInfo:
    pid: int
    name: str
    memory_rss_kb: int = 0
    maps_count: int = 0


@dataclass
class MemoryRegion:
    start: int
    end: int
    permissions: str
    offset: int
    pathname: str = ""


class GameMemoryModder:
    """
    Read-only memory inspector for Android processes via procfs.
    Can list processes, read memory maps, and dump readable strings.

    NOTE: This reads /proc/<pid>/mem. On production Android devices
    without root, this only works for the current process.
    """

    def __init__(self):
        self._proc_path = Path("/proc")

    def list_processes(self) -> List[ProcessInfo]:
        """List all processes visible via procfs."""
        procs = []
        for entry in self._proc_path.iterdir():
            if entry.name.isdigit():
                try:
                    pid = int(entry.name)
                    cmdline = (entry / "cmdline").read_bytes().split(b"\x00")[0].decode(errors="replace")
                    status = (entry / "status").read_text()
                    rss_match = re.search(r"VmRSS:\s+(\d+)\s+kB", status)
                    rss = int(rss_match.group(1)) if rss_match else 0
                    procs.append(ProcessInfo(pid=pid, name=cmdline, memory_rss_kb=rss))
                except (PermissionError, FileNotFoundError, OSError):
                    continue
        return procs

    def read_maps(self, pid: int) -> List[MemoryRegion]:
        """Read /proc/<pid>/maps and return parsed memory regions."""
        regions = []
        try:
            maps_path = self._proc_path / str(pid) / "maps"
            if not maps_path.exists():
                return regions

            for line in maps_path.read_text().split("\n"):
                if not line.strip():
                    continue
                parts = line.split()
                addr_range = parts[0].split("-")
                perms = parts[1] if len(parts) > 1 else ""
                offset = int(parts[2], 16) if len(parts) > 2 else 0
                pathname = parts[-1] if len(parts) > 5 else ""
                regions.append(MemoryRegion(
                    start=int(addr_range[0], 16),
                    end=int(addr_range[1], 16),
                    permissions=perms,
                    offset=offset,
                    pathname=pathname,
                ))
        except (PermissionError, FileNotFoundError, OSError) as e:
            log.debug("maps_read_failed", pid=pid, error=str(e))
        return regions

    def search_memory(self, pid: int, pattern: bytes, region_filter: Optional[str] = None) -> List[Dict]:
        """
        Search process memory for a byte pattern.
        Only searches readable regions with matching pathname (if filter set).

        WARNING: Very slow on large heaps. Use with caution.
        """
        results = []
        regions = self.read_maps(pid)
        for region in regions:
            if "r" not in region.permissions:
                continue
            if region_filter and region_filter not in region.pathname:
                continue

            try:
                mem_path = self._proc_path / str(pid) / "mem"
                with open(mem_path, "rb") as f:
                    size = region.end - region.start
                    if size > 1024 * 1024:  # Skip regions > 1MB for safety
                        continue
                    f.seek(region.start)
                    data = f.read(size)
                    offset = 0
                    while True:
                        pos = data.find(pattern, offset)
                        if pos == -1:
                            break
                        results.append({
                            "address": hex(region.start + pos),
                            "region_path": region.pathname,
                        })
                        offset = pos + 1
            except (PermissionError, OSError, ValueError) as e:
                log.debug("memory_search_error", pid=pid, error=str(e))
                continue

        return results

    def read_strings(self, pid: int, region_path_filter: Optional[str] = None) -> List[str]:
        """Extract readable ASCII strings from process memory."""
        strings = []
        regions = self.read_maps(pid)
        for region in regions:
            if "r" not in region.permissions:
                continue
            if region_path_filter and region_path_filter not in region.pathname:
                continue

            try:
                mem_path = self._proc_path / str(pid) / "mem"
                with open(mem_path, "rb") as f:
                    size = region.end - region.start
                    if size > 1024 * 1024:
                        continue
                    f.seek(region.start)
                    data = f.read(size)
                    # Extract ASCII strings of length >= 4
                    current = []
                    for byte in data:
                        if 32 <= byte <= 126:
                            current.append(chr(byte))
                        else:
                            if len(current) >= 4:
                                strings.append("".join(current))
                            current = []
                    if len(current) >= 4:
                        strings.append("".join(current))
            except (PermissionError, OSError):
                continue

        return strings[:100]  # Limit output


game_memory_modder = GameMemoryModder()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.game_memory_modder import game_memory_modder
# procs = game_memory_modder.list_processes()
# for p in procs[:5]:
#     print(p.pid, p.name)
# maps = game_memory_modder.read_maps(procs[0].pid)
# print(f"Found {len(maps)} memory regions")
# ---
