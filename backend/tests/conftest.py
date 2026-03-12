import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer fake-test-token"}


@pytest.fixture
def mock_user_id():
    return "test-user-id-123"


@pytest.fixture
def mock_profile():
    return {
        "id": "test-user-id-123",
        "display_name": "TestTrader",
        "cash_balance": 100000.00,
        "created_at": "2026-03-11T00:00:00Z",
        "updated_at": "2026-03-11T00:00:00Z",
    }


@pytest.fixture
def mock_position_aapl():
    return {
        "id": "pos-1",
        "user_id": "test-user-id-123",
        "symbol": "AAPL",
        "asset_type": "stock",
        "quantity": 10.0,
        "avg_cost_basis": 150.00,
    }


@pytest.fixture
def mock_supabase():
    """Create a mock supabase client with chainable query builder."""
    mock = MagicMock()

    def make_chainable_query(data=None):
        query = MagicMock()
        result = MagicMock()
        result.data = data or []

        # Each method returns the query itself for chaining
        query.select.return_value = query
        query.insert.return_value = query
        query.update.return_value = query
        query.delete.return_value = query
        query.eq.return_value = query
        query.gt.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.single.return_value = query
        query.execute.return_value = result
        return query

    mock.table.return_value = make_chainable_query()
    mock._make_chainable_query = make_chainable_query
    return mock


@pytest.fixture
def mock_auth_token(mock_user_id):
    """Patch auth to return a fixed user ID."""
    with patch("app.services.auth.get_user_id_from_token", return_value=mock_user_id):
        yield mock_user_id
