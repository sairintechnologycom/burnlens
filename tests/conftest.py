import pytest
import pytest_asyncio
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch
import os

# Set test database URL
os.environ["DATABASE_URL"] = "postgresql+asyncpg://localhost/burnlens_cloud_test"
os.environ["JWT_SECRET"] = "test-secret-key"
os.environ["STRIPE_API_KEY"] = "sk_test_mock"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_mock"
os.environ["ENVIRONMENT"] = "test"


@pytest_asyncio.fixture
async def client():
    """Create test client with mocked database."""
    from burnlens_cloud.main import get_app

    app = get_app()

    # Mock database initialization
    with patch("burnlens_cloud.database.init_db") as mock_init:
        with patch("burnlens_cloud.database.close_db") as mock_close:
            mock_init.return_value = None
            mock_close.return_value = None

            async with AsyncClient(app=app, base_url="http://test") as ac:
                yield ac


@pytest_asyncio.fixture
async def mock_db():
    """Mock database connection."""
    with patch("burnlens_cloud.database.execute_query") as mock_query:
        with patch("burnlens_cloud.database.execute_insert") as mock_insert:
            with patch("burnlens_cloud.database.execute_bulk_insert") as mock_bulk:
                yield {
                    "execute_query": mock_query,
                    "execute_insert": mock_insert,
                    "execute_bulk_insert": mock_bulk,
                }
