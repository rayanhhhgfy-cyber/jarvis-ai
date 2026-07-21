# ====================================================================
# JARVIS OMEGA — Cloud Plugin
# ====================================================================
"""
Phase 8 seed plugin: AWS S3 / EC2 + GCP Storage basics.

AWS uses boto3 if installed; GCP uses google-cloud-storage if installed.
Both degrade gracefully if their SDK or credentials are missing.
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.tools import tool, RiskTier


def _cred(key: str) -> str:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or ""
    except Exception:
        return ""


# --------------------------------------------------------------------
# AWS S3
# --------------------------------------------------------------------

@tool(
    name="aws.s3_upload",
    description="Upload a local file to S3.",
    parameters={
        "type": "object",
        "properties": {
            "bucket": {"type": "string"},
            "key": {"type": "string", "description": "S3 object key."},
            "local_path": {"type": "string"},
        },
        "required": ["bucket", "key", "local_path"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="cloud",
)
async def aws_s3_upload(bucket: str, key: str, local_path: str) -> Dict[str, Any]:
    try:
        import boto3  # type: ignore
    except ImportError:
        return {"ok": False, "error": "boto3 is not installed"}
    ak = _cred("aws_access_key_id")
    sak = _cred("aws_secret_access_key")
    region = _cred("aws_region") or "us-east-1"
    if not (ak and sak):
        return {"ok": False, "error": "aws_access_key_id / aws_secret_access_key not in vault"}
    # boto3 client is sync — run in a thread executor via boto3 itself.
    import asyncio
    def _do():
        s3 = boto3.client("s3", aws_access_key_id=ak, aws_secret_access_key=sak, region_name=region)
        s3.upload_file(local_path, bucket, key)
        return {"ok": True, "bucket": bucket, "key": key}
    return await asyncio.to_thread(_do)


@tool(
    name="aws.s3_download",
    description="Download an S3 object to a local file.",
    parameters={
        "type": "object",
        "properties": {
            "bucket": {"type": "string"},
            "key": {"type": "string"},
            "local_path": {"type": "string"},
        },
        "required": ["bucket", "key", "local_path"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="cloud",
)
async def aws_s3_download(bucket: str, key: str, local_path: str) -> Dict[str, Any]:
    try:
        import boto3  # type: ignore
    except ImportError:
        return {"ok": False, "error": "boto3 is not installed"}
    ak = _cred("aws_access_key_id")
    sak = _cred("aws_secret_access_key")
    region = _cred("aws_region") or "us-east-1"
    if not (ak and sak):
        return {"ok": False, "error": "aws credentials not in vault"}
    import asyncio
    def _do():
        s3 = boto3.client("s3", aws_access_key_id=ak, aws_secret_access_key=sak, region_name=region)
        s3.download_file(bucket, key, local_path)
        return {"ok": True, "local_path": local_path}
    return await asyncio.to_thread(_do)


@tool(
    name="aws.ec2_list",
    description="List EC2 instances in a region.",
    parameters={
        "type": "object",
        "properties": {
            "region": {"type": "string", "default": "us-east-1"},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="cloud",
)
async def aws_ec2_list(region: str = "us-east-1") -> Dict[str, Any]:
    try:
        import boto3  # type: ignore
    except ImportError:
        return {"ok": False, "error": "boto3 is not installed"}
    ak = _cred("aws_access_key_id")
    sak = _cred("aws_secret_access_key")
    if not (ak and sak):
        return {"ok": False, "error": "aws credentials not in vault"}
    import asyncio
    def _do():
        ec2 = boto3.client("ec2", aws_access_key_id=ak, aws_secret_access_key=sak, region_name=region)
        resp = ec2.describe_instances()
        instances: List[Dict[str, Any]] = []
        for r in resp.get("Reservations", []):
            for inst in r.get("Instances", []):
                instances.append({
                    "id": inst.get("InstanceId"),
                    "state": inst.get("State", {}).get("Name"),
                    "type": inst.get("InstanceType"),
                    "public_ip": inst.get("PublicIpAddress"),
                    "name": next((t.get("Value") for t in inst.get("Tags", []) if t.get("Key") == "Name"), None),
                })
        return {"ok": True, "count": len(instances), "instances": instances}
    return await asyncio.to_thread(_do)


# --------------------------------------------------------------------
# GCP Storage
# --------------------------------------------------------------------

@tool(
    name="gcp.storage_upload",
    description="Upload a local file to a GCP Storage bucket. Uses google-cloud-storage if installed.",
    parameters={
        "type": "object",
        "properties": {
            "bucket": {"type": "string"},
            "blob": {"type": "string"},
            "local_path": {"type": "string"},
        },
        "required": ["bucket", "blob", "local_path"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="cloud",
)
async def gcp_storage_upload(bucket: str, blob: str, local_path: str) -> Dict[str, Any]:
    try:
        from google.cloud import storage  # type: ignore
    except ImportError:
        return {"ok": False, "error": "google-cloud-storage is not installed"}
    creds_path = _cred("google_application_credentials")
    if not creds_path:
        return {"ok": False, "error": "google_application_credentials (path to service-account JSON) not set"}
    import asyncio, os
    def _do():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
        client = storage.Client()
        bucket_obj = client.bucket(bucket)
        blob_obj = bucket_obj.blob(blob)
        blob_obj.upload_from_filename(local_path)
        return {"ok": True, "bucket": bucket, "blob": blob}
    return await asyncio.to_thread(_do)


PLUGIN_NAME = "cloud"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "AWS (S3 + EC2) and GCP (Storage) integrations."
