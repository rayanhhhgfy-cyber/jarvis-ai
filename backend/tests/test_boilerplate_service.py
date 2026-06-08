# ====================================================================
# JARVIS OMEGA — SaaS Boilerplate Generator Unit Tests
# ====================================================================
"""
Unit tests for BoilerplateService, validating project skeletons generation,
file writing/modifying, and dev server simulation.
"""

import json
import pytest
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch
from backend.services.boilerplate_service import BoilerplateService

TEST_WORKSPACE_DIR = Path("./workspace/test_builds_temp")

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def boilerplate_svc():
    if TEST_WORKSPACE_DIR.exists():
        shutil.rmtree(TEST_WORKSPACE_DIR)
    TEST_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    
    with patch("backend.services.boilerplate_service.settings") as mock_settings:
        mock_settings.workspace_dir = str(TEST_WORKSPACE_DIR)
        
        service = BoilerplateService()
        yield service
        
    if TEST_WORKSPACE_DIR.exists():
        shutil.rmtree(TEST_WORKSPACE_DIR)

@pytest.mark.anyio
@patch("backend.services.boilerplate_service.llm_service")
async def test_generate_project_lifecycle(mock_llm, boilerplate_svc):
    """Test full boilerplate generation, listing files, and editing files."""
    # 1. Mock LLM output JSON
    mock_llm.get_response = AsyncMock(return_value=json.dumps({
        "framework": "nextjs",
        "styling": "tailwind",
        "database": "supabase",
        "auth": "none",
        "description": "Test E-Commerce Store",
        "files": {
            "package.json": '{"name": "test-app"}',
            "app/page.tsx": "export default function Page() { return <div>Store</div> }"
        }
    }))
    
    # Generate
    meta = await boilerplate_svc.generate_project(prompt="Build a simple e-commerce store")
    assert meta["framework"] == "nextjs"
    assert meta["database"] == "supabase"
    assert "package.json" in meta["files"]
    
    project_id = meta["project_id"]
    
    # 2. Get project files list and content
    contents = await boilerplate_svc.get_project_files(project_id)
    assert len(contents["file_tree"]) == 2
    assert "package.json" in contents["file_tree"]
    assert "app/page.tsx" in contents["file_tree"]
    assert contents["files"]["package.json"] == '{"name": "test-app"}'
    
    # 3. Modify file content via Monaco mock save
    new_content = "export default function Page() { return <div>Updated Store</div> }"
    save_success = await boilerplate_svc.save_project_file(project_id, "app/page.tsx", new_content)
    assert save_success is True
    
    # Check again
    contents_updated = await boilerplate_svc.get_project_files(project_id)
    assert contents_updated["files"]["app/page.tsx"] == new_content

@pytest.mark.anyio
@patch("backend.services.boilerplate_service.llm_service")
async def test_generate_project_fallback(mock_llm, boilerplate_svc):
    """Test fallback to mock skeleton if LLM response is not valid JSON."""
    mock_llm.get_response = AsyncMock(return_value="Non-JSON raw string error response")
    
    meta = await boilerplate_svc.generate_project(prompt="Build nextjs app")
    assert meta["framework"] == "nextjs"
    assert len(meta["files"]) > 0
    
    project_id = meta["project_id"]
    contents = await boilerplate_svc.get_project_files(project_id)
    assert "package.json" in contents["file_tree"]
