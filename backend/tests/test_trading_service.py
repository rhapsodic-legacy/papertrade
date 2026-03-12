import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException

from app.services.trading import execute_trade, _execute_buy, _execute_sell


class TestExecuteTrade:
    @pytest.mark.asyncio
    async def test_buy_stock_when_market_closed_raises(self):
        with patch("app.services.trading.is_stock_market_open", return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                await execute_trade("user1", "AAPL", "stock", "buy", 10)
            assert exc_info.value.status_code == 400
            assert "closed" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_crypto_allowed_anytime(self):
        mock_quote = {"price": 65000.0, "symbol": "BTC"}
        mock_db = MagicMock()

        # Profile query
        profile_result = MagicMock()
        profile_result.data = {"cash_balance": 100000.0}

        # Position query (no existing position)
        pos_result = MagicMock()
        pos_result.data = []

        # Transaction insert
        tx_result = MagicMock()
        tx_result.data = [
            {
                "id": "tx-1",
                "user_id": "user1",
                "symbol": "BTC",
                "asset_type": "crypto",
                "side": "buy",
                "quantity": 0.5,
                "price": 65000.0,
                "total": 32500.0,
                "created_at": "2026-03-11T00:00:00Z",
            }
        ]

        call_count = [0]

        def table_side_effect(table_name):
            query = MagicMock()
            query.select.return_value = query
            query.insert.return_value = query
            query.update.return_value = query
            query.eq.return_value = query
            query.single.return_value = query

            if table_name == "profiles":
                query.execute.return_value = profile_result
            elif table_name == "positions":
                query.execute.return_value = pos_result
            elif table_name == "transactions":
                query.execute.return_value = tx_result
            return query

        mock_db.table.side_effect = table_side_effect

        with (
            patch("app.services.trading.get_quote", new_callable=AsyncMock, return_value=mock_quote),
            patch("app.services.trading.get_supabase_admin", return_value=mock_db),
        ):
            result = await execute_trade("user1", "BTC", "crypto", "buy", 0.5)

        assert result["symbol"] == "BTC"
        assert result["total"] == 32500.0

    @pytest.mark.asyncio
    async def test_buy_insufficient_funds_raises(self):
        mock_quote = {"price": 200.0, "symbol": "AAPL"}
        mock_db = MagicMock()

        profile_result = MagicMock()
        profile_result.data = {"cash_balance": 100.0}  # only $100

        def table_side_effect(table_name):
            query = MagicMock()
            query.select.return_value = query
            query.eq.return_value = query
            query.single.return_value = query
            query.execute.return_value = profile_result
            return query

        mock_db.table.side_effect = table_side_effect

        with (
            patch("app.services.trading.is_stock_market_open", return_value=True),
            patch("app.services.trading.get_quote", new_callable=AsyncMock, return_value=mock_quote),
            patch("app.services.trading.get_supabase_admin", return_value=mock_db),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await execute_trade("user1", "AAPL", "stock", "buy", 10)
            assert exc_info.value.status_code == 400
            assert "insufficient funds" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_quote_not_found_raises(self):
        with (
            patch("app.services.trading.is_stock_market_open", return_value=True),
            patch("app.services.trading.get_quote", new_callable=AsyncMock, return_value=None),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await execute_trade("user1", "FAKE", "stock", "buy", 10)
            assert exc_info.value.status_code == 404


class TestExecuteBuy:
    def test_creates_new_position(self):
        mock_db = MagicMock()

        # No existing position
        pos_result = MagicMock()
        pos_result.data = []

        call_log = []

        def table_side_effect(table_name):
            query = MagicMock()
            query.select.return_value = query
            query.insert.return_value = query
            query.update.return_value = query
            query.eq.return_value = query
            query.execute.return_value = pos_result if table_name == "positions" else MagicMock()

            def track_insert(data):
                call_log.append(("insert", table_name, data))
                return query

            query.insert.side_effect = track_insert
            return query

        mock_db.table.side_effect = table_side_effect

        _execute_buy(mock_db, "user1", "AAPL", "stock", 10, 150.0, 1500.0, 100000.0)

        # Should have inserted a new position
        position_inserts = [c for c in call_log if c[1] == "positions"]
        assert len(position_inserts) == 1
        assert position_inserts[0][2]["quantity"] == 10
        assert position_inserts[0][2]["avg_cost_basis"] == 150.0

    def test_updates_existing_position_with_averaged_cost(self):
        mock_db = MagicMock()

        pos_result = MagicMock()
        pos_result.data = [
            {"id": "pos-1", "quantity": 10.0, "avg_cost_basis": 140.0}
        ]

        update_log = []

        def table_side_effect(table_name):
            query = MagicMock()
            query.select.return_value = query
            query.update.return_value = query
            query.eq.return_value = query

            if table_name == "positions":
                query.execute.return_value = pos_result

                def track_update(data):
                    update_log.append(data)
                    return query

                query.update.side_effect = track_update

            else:
                query.execute.return_value = MagicMock()

            return query

        mock_db.table.side_effect = table_side_effect

        # Buy 10 more at $160
        _execute_buy(mock_db, "user1", "AAPL", "stock", 10, 160.0, 1600.0, 100000.0)

        # Avg cost should be (10*140 + 10*160) / 20 = 150
        assert len(update_log) > 0
        pos_update = [u for u in update_log if "avg_cost_basis" in u]
        assert len(pos_update) == 1
        assert pos_update[0]["quantity"] == 20.0
        assert pos_update[0]["avg_cost_basis"] == 150.0


class TestExecuteSell:
    def test_sell_insufficient_shares_raises(self):
        mock_db = MagicMock()

        pos_result = MagicMock()
        pos_result.data = [{"id": "pos-1", "quantity": 5.0, "avg_cost_basis": 150.0}]

        def table_side_effect(table_name):
            query = MagicMock()
            query.select.return_value = query
            query.eq.return_value = query
            query.execute.return_value = pos_result
            return query

        mock_db.table.side_effect = table_side_effect

        with pytest.raises(HTTPException) as exc_info:
            _execute_sell(mock_db, "user1", "AAPL", "stock", 10, 150.0, 1500.0, 100000.0)
        assert exc_info.value.status_code == 400
        assert "insufficient" in exc_info.value.detail.lower()

    def test_sell_no_position_raises(self):
        mock_db = MagicMock()

        pos_result = MagicMock()
        pos_result.data = []

        def table_side_effect(table_name):
            query = MagicMock()
            query.select.return_value = query
            query.eq.return_value = query
            query.execute.return_value = pos_result
            return query

        mock_db.table.side_effect = table_side_effect

        with pytest.raises(HTTPException) as exc_info:
            _execute_sell(mock_db, "user1", "AAPL", "stock", 10, 150.0, 1500.0, 100000.0)
        assert exc_info.value.status_code == 400

    def test_sell_all_deletes_position(self):
        mock_db = MagicMock()

        pos_result = MagicMock()
        pos_result.data = [{"id": "pos-1", "quantity": 10.0, "avg_cost_basis": 150.0}]

        delete_called = []

        def table_side_effect(table_name):
            query = MagicMock()
            query.select.return_value = query
            query.update.return_value = query
            query.eq.return_value = query
            query.execute.return_value = pos_result if table_name == "positions" else MagicMock()

            def track_delete():
                delete_called.append(table_name)
                return query

            query.delete.side_effect = track_delete
            return query

        mock_db.table.side_effect = table_side_effect

        _execute_sell(mock_db, "user1", "AAPL", "stock", 10, 160.0, 1600.0, 100000.0)

        # Should delete position when selling all shares
        assert "positions" in delete_called
