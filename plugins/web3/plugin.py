# ====================================================================
# JARVIS OMEGA - Decentralized Hosting (Phase 14)
# ====================================================================
"""
Deploy sites to IPFS/Arweave + ENS domains. Permanent, uncensorable, $0/mo.

  web3.deploy_ipfs       - Pinata free tier or local IPFS node
  web3.deploy_arweave    - permanent storage (one-time payment)
  web3.register_ens      - ENS domain registration (ETH gas)
  web3.publish_mirror    - Mirror.xyz on-chain blog
  web3.dns_link          - link IPFS hash to ENS domain
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx

from backend.tools import tool, RiskTier


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


@tool(
    name="web3.deploy_ipfs",
    description="Pin a folder to IPFS via Pinata free tier (1GB free). Returns CID + gateway URL.",
    parameters={
        "type": "object",
        "properties": {
            "site_dir": {"type": "string", "description": "Local directory to pin."},
        },
        "required": ["site_dir"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="web3",
)
async def web3_deploy_ipfs(site_dir: str) -> Dict[str, Any]:
    from pathlib import Path
    if not Path(site_dir).is_dir():
        return {"ok": False, "error": "site_dir not found"}
    jwt = _cred("pinata_jwt")
    if not jwt:
        return {"ok": False, "error": "pinata_jwt not in vault. Sign up at https://pinata.cloud (free 1GB)"}
    try:
        import asyncio
        # Walk the dir, upload files via Pinata's pinFileToIPFS with metadata preserving paths.
        files_to_upload = list(Path(site_dir).rglob("*"))
        files_to_upload = [f for f in files_to_upload if f.is_file()]
        if not files_to_upload:
            return {"ok": False, "error": "no files in site_dir"}

        # Pinata supports multipart upload.
        def _do():
            import requests
            import io
            url = "https://api.pinata.cloud/pinning/pinFileToIPFS"
            headers = {"Authorization": f"Bearer {jwt}"}
            files = []
            for fp in files_to_upload:
                rel = str(fp.relative_to(site_dir))
                files.append(("file", (rel, open(fp, "rb"))))
            try:
                resp = requests.post(url, headers=headers, files=files, timeout=120)
            finally:
                for _, f in files:
                    f[1].close()
            return resp
        resp = await asyncio.to_thread(_do)
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        data = resp.json()
        cid = data.get("IpfsHash")
        return {
            "ok": True, "cid": cid,
            "gateway_url": f"https://gateway.pinata.cloud/ipfs/{cid}",
            "public_url": f"https://ipfs.io/ipfs/{cid}",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="web3.deploy_arweave",
    description="Deploy to Arweave (permanent storage, one-time payment). Requires arweave_wallet_json in vault.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
        },
        "required": ["file_path"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="web3",
)
async def web3_deploy_arweave(file_path: str) -> Dict[str, Any]:
    from pathlib import Path
    if not Path(file_path).is_file():
        return {"ok": False, "error": "file not found"}
    wallet = _cred("arweave_wallet_json")
    if not wallet:
        return {"ok": False, "error": "arweave_wallet_json not in vault. Get a wallet at https://arweave.org"}
    return {
        "ok": False,
        "error": "Arweave upload needs the `arweave` Python SDK + wallet funded with AR tokens.",
        "manual_url": "https://viewblock.io/arweave",
        "next_steps": "Install `arweave` SDK, load wallet JSON, fund with AR (1 AR ≈ $10, pays for ~GB)",
    }


@tool(
    name="web3.register_ens",
    description="Register an ENS domain (.eth). Requires eth_wallet_private_key + ETH balance.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "ENS name without .eth suffix."},
            "years": {"type": "integer", "default": 1},
        },
        "required": ["name"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="web3",
)
async def web3_register_ens(name: str, years: int = 1) -> Dict[str, Any]:
    pk = _cred("eth_wallet_private_key")
    if not pk:
        return {"ok": False, "error": "eth_wallet_private_key not in vault"}
    return {
        "ok": False,
        "error": "ENS registration requires web3.py + ENS contract interaction. Use the ENS app for now.",
        "manual_url": f"https://app.ens.domains/{name}.eth",
        "name": name, "years": years,
        "instructions": "Open the URL, connect wallet, complete registration.",
    }


@tool(
    name="web3.publish_mirror",
    description="Publish an article to Mirror.xyz (on-chain blog). Requires mirror_token in vault.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content_markdown": {"type": "string"},
        },
        "required": ["title", "content_markdown"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="web3",
)
async def web3_publish_mirror(title: str, content_markdown: str) -> Dict[str, Any]:
    token = _cred("mirror_token")
    if not token:
        return {"ok": False, "error": "mirror_token not in vault. Sign in to https://mirror.xyz"}
    return {
        "ok": False,
        "error": "Mirror.xyz doesn't have a public write API yet. Manual publish required.",
        "manual_url": "https://mirror.xyz/dashboard",
        "title": title,
    }


@tool(
    name="web3.dns_link",
    description="Link an IPFS CID to an ENS domain (content hash record). Requires eth_wallet_private_key.",
    parameters={
        "type": "object",
        "properties": {
            "ens_name": {"type": "string", "description": "e.g. sir.eth"},
            "cid": {"type": "string"},
        },
        "required": ["ens_name", "cid"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="web3",
)
async def web3_dns_link(ens_name: str, cid: str) -> Dict[str, Any]:
    pk = _cred("eth_wallet_private_key")
    if not pk:
        return {"ok": False, "error": "eth_wallet_private_key not in vault"}
    return {
        "ok": False,
        "error": "ENS content-hash update requires web3.py + ENS resolver contract. Use ENS app for now.",
        "manual_url": f"https://app.ens.domains/{ens_name}",
        "instructions": f"Open {ens_name} settings → Content Hash → set to ipfs://{cid}",
    }


PLUGIN_NAME = "web3"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Decentralized hosting: IPFS (Pinata free), Arweave, ENS domains, Mirror.xyz."
