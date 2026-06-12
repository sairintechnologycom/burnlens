import pytest
from fastapi.testclient import TestClient
from burnlens.config import BurnLensConfig
from burnlens.proxy.server import get_app
from burnlens.storage.database import init_db

def test_server_lifespan_wal(tmp_path):
    db_path = str(tmp_path / "test.db")
    wal_path = str(tmp_path / "wal.jsonl")
    dlq_path = str(tmp_path / "dlq.jsonl")
    
    config = BurnLensConfig(
        db_path=db_path,
    )
    # Inject WAL fields dynamically or via subclassing if not configured yet
    config.wal_path = wal_path
    config.dlq_path = dlq_path
    
    app = get_app(config)
    
    # We use TestClient as a context manager to trigger lifespan startup and shutdown
    with TestClient(app) as client:
        # Check that WAL and worker were mounted on app state
        assert hasattr(app.state, "wal")
        assert hasattr(app.state, "wal_worker")
