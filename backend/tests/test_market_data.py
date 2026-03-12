import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone

from app.services.market_data import (
    get_stock_quote,
    get_crypto_quote,
    get_quote,
    get_available_assets,
    is_stock_market_open,
    TOP_STOCKS,
    CRYPTO_MAP,
)


class TestIsStockMarketOpen:
    def test_closed_on_saturday(self):
        with patch("app.services.market_data.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 5
            mock_dt.now.return_value = mock_now
            assert is_stock_market_open() is False

    def test_closed_on_sunday(self):
        with patch("app.services.market_data.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 6
            mock_dt.now.return_value = mock_now
            assert is_stock_market_open() is False


class TestGetStockQuote:
    @pytest.mark.asyncio
    async def test_successful_quote(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "c": 175.50,
            "d": 2.30,
            "dp": 1.33,
        }

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response

        with (
            patch("app.services.market_data.httpx.AsyncClient") as mock_client_cls,
            patch("app.services.market_data.get_settings") as mock_settings,
        ):
            mock_client_cls.return_value.__aenter__.return_value = mock_client_instance
            mock_client_cls.return_value.__aexit__.return_value = False
            mock_settings.return_value.finnhub_api_key = "test-key"

            result = await get_stock_quote("AAPL")

        assert result is not None
        assert result["symbol"] == "AAPL"
        assert result["price"] == 175.50
        assert result["asset_type"] == "stock"
        assert result["name"] == "Apple"

    @pytest.mark.asyncio
    async def test_failed_quote_returns_none(self):
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response

        with (
            patch("app.services.market_data.httpx.AsyncClient") as mock_client_cls,
            patch("app.services.market_data.get_settings") as mock_settings,
        ):
            mock_client_cls.return_value.__aenter__.return_value = mock_client_instance
            mock_client_cls.return_value.__aexit__.return_value = False
            mock_settings.return_value.finnhub_api_key = "test-key"

            result = await get_stock_quote("AAPL")

        assert result is None

    @pytest.mark.asyncio
    async def test_zero_price_returns_none(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"c": 0, "d": 0, "dp": 0}

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response

        with (
            patch("app.services.market_data.httpx.AsyncClient") as mock_client_cls,
            patch("app.services.market_data.get_settings") as mock_settings,
        ):
            mock_client_cls.return_value.__aenter__.return_value = mock_client_instance
            mock_client_cls.return_value.__aexit__.return_value = False
            mock_settings.return_value.finnhub_api_key = "test-key"

            result = await get_stock_quote("INVALID")

        assert result is None


class TestGetCryptoQuote:
    @pytest.mark.asyncio
    async def test_successful_quote(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bitcoin": {"usd": 65000.00, "usd_24h_change": 2.5}
        }

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response

        with patch("app.services.market_data.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__.return_value = mock_client_instance
            mock_client_cls.return_value.__aexit__.return_value = False

            result = await get_crypto_quote("BTC")

        assert result is not None
        assert result["symbol"] == "BTC"
        assert result["price"] == 65000.00
        assert result["asset_type"] == "crypto"
        assert result["name"] == "Bitcoin"

    @pytest.mark.asyncio
    async def test_unsupported_crypto_returns_none(self):
        result = await get_crypto_quote("FAKECOIN")
        assert result is None


class TestGetQuote:
    @pytest.mark.asyncio
    async def test_routes_to_stock(self):
        with patch("app.services.market_data.get_stock_quote", new_callable=AsyncMock) as mock:
            mock.return_value = {"symbol": "AAPL", "price": 175.0}
            result = await get_quote("AAPL", "stock")
            mock.assert_called_once_with("AAPL")
            assert result["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_routes_to_crypto(self):
        with patch("app.services.market_data.get_crypto_quote", new_callable=AsyncMock) as mock:
            mock.return_value = {"symbol": "BTC", "price": 65000.0}
            result = await get_quote("BTC", "crypto")
            mock.assert_called_once_with("BTC")
            assert result["symbol"] == "BTC"

    @pytest.mark.asyncio
    async def test_invalid_type_returns_none(self):
        result = await get_quote("AAPL", "forex")
        assert result is None


class TestGetAvailableAssets:
    @pytest.mark.asyncio
    async def test_returns_stocks_and_crypto(self):
        assets = await get_available_assets()
        assert "stocks" in assets
        assert "crypto" in assets
        assert len(assets["stocks"]) == len(TOP_STOCKS)
        assert len(assets["crypto"]) == len(CRYPTO_MAP)

    @pytest.mark.asyncio
    async def test_auki_is_included(self):
        assets = await get_available_assets()
        crypto_symbols = [c["symbol"] for c in assets["crypto"]]
        assert "AUKI" in crypto_symbols
