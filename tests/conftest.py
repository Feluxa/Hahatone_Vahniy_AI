import pytest
from pathlib import Path
import shutil

from harness.repo.workspace import copy_clean

ROOT_DIR = Path(__file__).resolve().parents[1]
MERIDIAN_DIR = ROOT_DIR / "materials" / "hackathon-participants" / "meridian"
GOLDEN_REPO = ROOT_DIR / "golden" / "settlement-001" / "environment" / "repo"

@pytest.fixture(scope="session", autouse=True)
def prepare_golden_repo():
    if not MERIDIAN_DIR.exists():
        pytest.skip("materials/hackathon-participants/meridian not found")
    
    if GOLDEN_REPO.exists():
        shutil.rmtree(GOLDEN_REPO, ignore_errors=True)
        
    GOLDEN_REPO.parent.mkdir(parents=True, exist_ok=True)
    copy_clean(MERIDIAN_DIR, GOLDEN_REPO)
    yield
    # Optionally clean up, but `.gitignore` already ignores it.
