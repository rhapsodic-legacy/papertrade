import pytest
from unittest.mock import patch, MagicMock, AsyncMock  # noqa: F401
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


class TestHealthCheck:
    def test_health_returns_ok(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestMarketEndpoints:
    def test_list_assets(self):
        resp = client.get("/api/market/assets")
        assert resp.status_code == 200
        data = resp.json()
        assert "stocks" in data
        assert "crypto" in data
        assert len(data["stocks"]) == 20
        assert len(data["crypto"]) == 8

    def test_market_status(self):
        resp = client.get("/api/market/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "stock_market_open" in data
        assert data["crypto_market_open"] is True

    def test_quote_invalid_asset_type(self):
        resp = client.get("/api/market/quote/forex/EURUSD")
        assert resp.status_code == 400

    def test_quote_unsupported_stock(self):
        resp = client.get("/api/market/quote/stock/FAKESYMBOL")
        assert resp.status_code == 400

    def test_quote_unsupported_crypto(self):
        resp = client.get("/api/market/quote/crypto/FAKECOIN")
        assert resp.status_code == 400

    def test_quote_stock_success(self):
        mock_quote = {
            "symbol": "AAPL",
            "asset_type": "stock",
            "price": 175.0,
            "change": 2.0,
            "change_pct": 1.15,
            "name": "Apple",
        }
        with patch("app.routers.market.get_quote", new_callable=AsyncMock, return_value=mock_quote):
            resp = client.get("/api/market/quote/stock/AAPL")
        assert resp.status_code == 200
        assert resp.json()["symbol"] == "AAPL"
        assert resp.json()["price"] == 175.0

    def test_quote_crypto_success(self):
        mock_quote = {
            "symbol": "BTC",
            "asset_type": "crypto",
            "price": 65000.0,
            "change": 1500.0,
            "change_pct": 2.36,
            "name": "Bitcoin",
        }
        with patch("app.routers.market.get_quote", new_callable=AsyncMock, return_value=mock_quote):
            resp = client.get("/api/market/quote/crypto/BTC")
        assert resp.status_code == 200
        assert resp.json()["price"] == 65000.0


class TestTradingEndpoints:
    def test_trade_requires_auth(self):
        resp = client.post(
            "/api/trading/trade",
            json={"symbol": "AAPL", "asset_type": "stock", "side": "buy", "quantity": 10},
        )
        assert resp.status_code == 401

    def test_trade_with_auth(self):
        mock_result = {
            "id": "tx-1",
            "symbol": "AAPL",
            "asset_type": "stock",
            "side": "buy",
            "quantity": 10,
            "price": 175.0,
            "total": 1750.0,
            "created_at": "2026-03-11T00:00:00Z",
        }
        with (
            patch("app.routers.trading.get_user_id_from_token", return_value="user-1"),
            patch("app.routers.trading.execute_trade", new_callable=AsyncMock, return_value=mock_result),
        ):
            resp = client.post(
                "/api/trading/trade",
                json={"symbol": "AAPL", "asset_type": "stock", "side": "buy", "quantity": 10},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1750.0

    def test_trade_invalid_side_rejected(self):
        resp = client.post(
            "/api/trading/trade",
            json={"symbol": "AAPL", "asset_type": "stock", "side": "short", "quantity": 10},
            headers={"Authorization": "Bearer fake-token"},
        )
        assert resp.status_code == 422  # validation error

    def test_trade_zero_quantity_rejected(self):
        resp = client.post(
            "/api/trading/trade",
            json={"symbol": "AAPL", "asset_type": "stock", "side": "buy", "quantity": 0},
            headers={"Authorization": "Bearer fake-token"},
        )
        assert resp.status_code == 422

    def test_trade_negative_quantity_rejected(self):
        resp = client.post(
            "/api/trading/trade",
            json={"symbol": "AAPL", "asset_type": "stock", "side": "buy", "quantity": -5},
            headers={"Authorization": "Bearer fake-token"},
        )
        assert resp.status_code == 422


class TestPortfolioEndpoints:
    def test_portfolio_requires_auth(self):
        resp = client.get("/api/portfolio/")
        assert resp.status_code == 401

    def test_leaderboard_requires_auth(self):
        # Leaderboard doesn't require auth in the router, but let's verify it works
        # It calls supabase directly, so we need to mock that
        mock_db = MagicMock()
        result = MagicMock()
        result.data = []
        query = MagicMock()
        query.select.return_value = query
        query.limit.return_value = query
        query.execute.return_value = result
        mock_db.table.return_value = query

        with patch("app.routers.portfolio.get_supabase_admin", return_value=mock_db):
            resp = client.get("/api/portfolio/leaderboard")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_history_requires_auth(self):
        resp = client.get("/api/portfolio/history")
        assert resp.status_code == 401


class TestWatchlistEndpoints:
    def test_watchlist_requires_auth(self):
        resp = client.get("/api/watchlist/")
        assert resp.status_code == 401

    def test_add_to_watchlist_requires_auth(self):
        resp = client.post(
            "/api/watchlist/",
            json={"symbol": "AAPL", "asset_type": "stock"},
        )
        assert resp.status_code == 401

    def test_delete_from_watchlist_requires_auth(self):
        resp = client.delete("/api/watchlist/AAPL")
        assert resp.status_code == 401

    def test_add_unsupported_stock(self):
        with patch("app.routers.watchlist.get_user_id_from_token", return_value="user-1"):
            resp = client.post(
                "/api/watchlist/",
                json={"symbol": "FAKESYMBOL", "asset_type": "stock"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 400

    def test_add_unsupported_crypto(self):
        with patch("app.routers.watchlist.get_user_id_from_token", return_value="user-1"):
            resp = client.post(
                "/api/watchlist/",
                json={"symbol": "FAKECOIN", "asset_type": "crypto"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 400

    def test_add_duplicate_to_watchlist(self):
        mock_db = MagicMock()
        select_query = MagicMock()
        select_query.select.return_value = select_query
        select_query.eq.return_value = select_query
        result = MagicMock()
        result.data = [{"id": "existing-1"}]
        select_query.execute.return_value = result
        mock_db.table.return_value = select_query

        with (
            patch("app.routers.watchlist.get_user_id_from_token", return_value="user-1"),
            patch("app.routers.watchlist.get_supabase_admin", return_value=mock_db),
        ):
            resp = client.post(
                "/api/watchlist/",
                json={"symbol": "AAPL", "asset_type": "stock"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 409

    def test_get_watchlist_success(self):
        mock_db = MagicMock()
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.order.return_value = query
        result = MagicMock()
        result.data = [
            {"id": "w1", "symbol": "AAPL", "asset_type": "stock", "created_at": "2026-03-11"},
        ]
        query.execute.return_value = result
        mock_db.table.return_value = query

        mock_quote = {
            "symbol": "AAPL",
            "asset_type": "stock",
            "price": 175.0,
            "change": 2.0,
            "change_pct": 1.15,
            "name": "Apple",
        }

        with (
            patch("app.routers.watchlist.get_user_id_from_token", return_value="user-1"),
            patch("app.routers.watchlist.get_supabase_admin", return_value=mock_db),
            patch("app.routers.watchlist.get_quote", new_callable=AsyncMock, return_value=mock_quote),
        ):
            resp = client.get(
                "/api/watchlist/",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["symbol"] == "AAPL"
        assert data[0]["price"] == 175.0

    def test_remove_from_watchlist_not_found(self):
        mock_db = MagicMock()
        query = MagicMock()
        query.delete.return_value = query
        query.eq.return_value = query
        result = MagicMock()
        result.data = []
        query.execute.return_value = result
        mock_db.table.return_value = query

        with (
            patch("app.routers.watchlist.get_user_id_from_token", return_value="user-1"),
            patch("app.routers.watchlist.get_supabase_admin", return_value=mock_db),
        ):
            resp = client.delete(
                "/api/watchlist/AAPL",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 404
