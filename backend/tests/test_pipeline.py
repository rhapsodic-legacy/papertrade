"""Tests for the AI trading pipeline components.

Covers: ATR position cap, FOMC calendar, yield curve fallback,
options flow parsing, sentiment JSON parsing, economic calendar,
earnings urgency, LLM routing, and the full trading loop.
"""

import json
import math
import pytest
from datetime import date, timedelta
from unittest.mock import patch, MagicMock, AsyncMock


# ---------------------------------------------------------------------------
# 1. ATR-based position cap
# ---------------------------------------------------------------------------

class TestATRPositionCap:
    """Test the ATR-based position sizing guard in _execute_ai_trade."""

    def _build_brief(self, symbol: str, atr: float, price: float) -> dict:
        return {
            "stock_technicals": {
                symbol: {"atr_14": atr, "close": price},
            },
            "crypto_technicals": {},
        }

    @pytest.mark.asyncio
    async def test_cap_reduces_oversized_stock_buy(self):
        """A buy of 100 shares should be capped when ATR says max is lower."""
        from app.services.ai_trader import _execute_ai_trade

        brief = self._build_brief("AAPL", atr=6.0, price=250.0)
        risk_params = {"max_position_pct": 15.0}

        trade = {
            "symbol": "AAPL", "asset_type": "stock", "side": "buy",
            "quantity": 100, "reasoning": "test", "modules_used": [],
        }

        mock_quote = {"price": 250.0, "symbol": "AAPL"}
        mock_profile = MagicMock()
        mock_profile.data = {"cash_balance": 100000.0}

        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_profile
        # Position check returns empty (no existing position)
        pos_result = MagicMock()
        pos_result.data = []
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = pos_result
        # Insert returns success
        tx_result = MagicMock()
        tx_result.data = [{"id": "tx-1"}]
        mock_db.table.return_value.insert.return_value.execute.return_value = tx_result

        with patch("app.services.ai_trader.get_quote", new_callable=AsyncMock, return_value=mock_quote), \
             patch("app.services.ai_trader.get_supabase_admin", return_value=mock_db):
            result = await _execute_ai_trade(
                "user-1", trade, brief=brief, risk_params=risk_params,
            )

        # The trade should have been capped — quantity should be less than 100
        assert trade["quantity"] < 100, f"Expected cap, got quantity={trade['quantity']}"
        # But not zero
        assert trade["quantity"] > 0

    @pytest.mark.asyncio
    async def test_no_cap_when_quantity_already_small(self):
        """A small buy should pass through uncapped."""
        from app.services.ai_trader import _execute_ai_trade

        brief = self._build_brief("PFE", atr=0.6, price=27.0)
        risk_params = {"max_position_pct": 15.0}

        trade = {
            "symbol": "PFE", "asset_type": "stock", "side": "buy",
            "quantity": 5, "reasoning": "test", "modules_used": [],
        }

        mock_quote = {"price": 27.0, "symbol": "PFE"}
        mock_profile = MagicMock()
        mock_profile.data = {"cash_balance": 100000.0}

        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_profile
        pos_result = MagicMock()
        pos_result.data = []
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = pos_result
        tx_result = MagicMock()
        tx_result.data = [{"id": "tx-1"}]
        mock_db.table.return_value.insert.return_value.execute.return_value = tx_result

        with patch("app.services.ai_trader.get_quote", new_callable=AsyncMock, return_value=mock_quote), \
             patch("app.services.ai_trader.get_supabase_admin", return_value=mock_db):
            result = await _execute_ai_trade(
                "user-1", trade, brief=brief, risk_params=risk_params,
            )

        # Quantity should be unchanged
        assert trade["quantity"] == 5

    @pytest.mark.asyncio
    async def test_no_cap_on_sells(self):
        """Sells should never be capped by ATR."""
        from app.services.ai_trader import _execute_ai_trade

        brief = self._build_brief("AAPL", atr=50.0, price=250.0)  # extreme ATR
        risk_params = {"max_position_pct": 15.0}

        trade = {
            "symbol": "AAPL", "asset_type": "stock", "side": "sell",
            "quantity": 50, "reasoning": "test", "modules_used": [],
        }

        mock_quote = {"price": 250.0, "symbol": "AAPL"}
        mock_profile = MagicMock()
        mock_profile.data = {"cash_balance": 50000.0}

        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_profile
        pos_result = MagicMock()
        pos_result.data = [{"id": "pos-1", "quantity": 50.0}]
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = pos_result
        tx_result = MagicMock()
        tx_result.data = [{"id": "tx-1"}]
        mock_db.table.return_value.insert.return_value.execute.return_value = tx_result

        with patch("app.services.ai_trader.get_quote", new_callable=AsyncMock, return_value=mock_quote), \
             patch("app.services.ai_trader.get_supabase_admin", return_value=mock_db):
            result = await _execute_ai_trade(
                "user-1", trade, brief=brief, risk_params=risk_params,
            )

        assert trade["quantity"] == 50

    def test_atr_cap_math(self):
        """Verify the ATR cap formula directly."""
        price = 300.0
        atr = 9.0  # 3% ATR
        max_position_pct = 0.15
        risk_per_trade = max_position_pct * 0.2  # 3%
        portfolio_value = 100_000.0
        atr_pct = atr / price
        atr_stop_fraction = 2 * atr_pct  # 6%
        max_dollars = portfolio_value * risk_per_trade / atr_stop_fraction
        max_dollars = min(max_dollars, portfolio_value * max_position_pct)
        max_qty = int(max_dollars / price)

        # 100000 * 0.03 / 0.06 = 50000, min(50000, 15000) = 15000
        # 15000 / 300 = 50 shares
        assert max_dollars == 15000.0
        assert max_qty == 50


# ---------------------------------------------------------------------------
# 2. FOMC Economic Calendar
# ---------------------------------------------------------------------------

class TestFOMCCalendar:
    """Test the FOMC-based economic calendar."""

    @pytest.mark.asyncio
    async def test_returns_fomc_context(self):
        """Should always return a Fed context line with days since/until."""
        from app.services.market_brief import _fetch_economic_calendar
        events = await _fetch_economic_calendar("dummy-key")

        context_events = [e for e in events if "Fed context" in e.get("event", "")]
        assert len(context_events) >= 1, "Should have at least one Fed context event"

        ctx = context_events[0]
        assert "since last FOMC" in ctx["event"]
        assert "until next" in ctx["event"]

    @pytest.mark.asyncio
    async def test_fomc_eve_warning(self):
        """Day before FOMC should produce an eve warning."""
        from app.services.market_brief import _FOMC_DATES, _fetch_economic_calendar

        # Find next FOMC date and fake today as the day before
        today = date.today()
        all_dates = []
        for year_dates in _FOMC_DATES.values():
            all_dates.extend(date.fromisoformat(d) for d in year_dates)
        future = [d for d in all_dates if d > today]
        if not future:
            pytest.skip("No future FOMC dates in schedule")

        next_fomc = min(future)
        eve = next_fomc - timedelta(days=1)

        with patch("app.services.market_brief.date") as mock_date:
            mock_date.today.return_value = eve
            mock_date.fromisoformat = date.fromisoformat
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            events = await _fetch_economic_calendar("dummy")

        eve_events = [e for e in events if "FOMC Eve" in e.get("event", "")]
        assert len(eve_events) >= 1, f"Expected FOMC Eve warning for {eve}"

    @pytest.mark.asyncio
    async def test_fomc_decision_day(self):
        """On FOMC day, should produce a rate decision event."""
        from app.services.market_brief import _FOMC_DATES, _fetch_economic_calendar

        today = date.today()
        all_dates = []
        for year_dates in _FOMC_DATES.values():
            all_dates.extend(date.fromisoformat(d) for d in year_dates)
        future = [d for d in all_dates if d > today]
        if not future:
            pytest.skip("No future FOMC dates")

        fomc_day = min(future)

        with patch("app.services.market_brief.date") as mock_date:
            mock_date.today.return_value = fomc_day
            mock_date.fromisoformat = date.fromisoformat
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            events = await _fetch_economic_calendar("dummy")

        decision_events = [e for e in events if "FOMC Rate Decision" in e.get("event", "")]
        assert len(decision_events) >= 1

    def test_fomc_dates_are_valid(self):
        """All hardcoded FOMC dates should be parseable and on weekdays."""
        from app.services.market_brief import _FOMC_DATES
        for year, dates in _FOMC_DATES.items():
            for d_str in dates:
                d = date.fromisoformat(d_str)
                assert d.year == year
                assert d.weekday() < 5, f"{d_str} is a weekend"

    def test_fomc_sep_months(self):
        """Dot plot meetings should be in Mar/Jun/Sep/Dec."""
        from app.services.market_brief import _FOMC_SEP_MONTHS
        assert _FOMC_SEP_MONTHS == {3, 6, 9, 12}


# ---------------------------------------------------------------------------
# 3. Sentiment JSON Parsing
# ---------------------------------------------------------------------------

class TestSentimentParsing:
    """Test LLM sentiment response parsing."""

    def _headlines(self, n: int = 3) -> list[dict]:
        return [
            {"headline": f"Headline {i}", "summary": "", "source": "test",
             "symbol": "AAPL" if i == 0 else None, "news_type": "general"}
            for i in range(n)
        ]

    def test_parse_valid_json(self):
        from app.services.sentiment import _parse_scores
        raw = json.dumps({
            "scores": [
                {"id": 0, "score": 0.5, "confidence": 0.9, "categories": ["earnings"]},
                {"id": 1, "score": -0.3, "confidence": 0.7, "categories": ["macro"]},
                {"id": 2, "score": 0.0, "confidence": 0.5, "categories": ["other"]},
            ]
        })
        headlines = self._headlines(3)
        scored = _parse_scores(raw, headlines)
        assert len(scored) == 3
        assert scored[0]["score"] == 0.5
        assert scored[1]["score"] == -0.3
        assert scored[2]["categories"] == ["other"]

    def test_parse_markdown_fenced_json(self):
        """LLMs often wrap JSON in ```json ... ``` fences."""
        from app.services.sentiment import _parse_scores
        raw = '```json\n{"scores": [{"id": 0, "score": 0.2, "confidence": 0.8, "categories": ["fed"]}]}\n```'
        scored = _parse_scores(raw, self._headlines(1))
        assert len(scored) == 1
        assert scored[0]["score"] == 0.2

    def test_parse_clamps_score_range(self):
        """Scores outside [-1, 1] should be clamped."""
        from app.services.sentiment import _parse_scores
        raw = json.dumps({
            "scores": [{"id": 0, "score": 2.5, "confidence": 1.5, "categories": ["earnings"]}]
        })
        scored = _parse_scores(raw, self._headlines(1))
        assert scored[0]["score"] == 1.0
        assert scored[0]["confidence"] == 1.0

    def test_parse_invalid_categories_fallback(self):
        """Unknown categories should fall back to ['other']."""
        from app.services.sentiment import _parse_scores
        raw = json.dumps({
            "scores": [{"id": 0, "score": 0.1, "confidence": 0.5, "categories": ["nonsense", "gibberish"]}]
        })
        scored = _parse_scores(raw, self._headlines(1))
        assert scored[0]["categories"] == ["other"]

    def test_parse_empty_response_raises(self):
        """Completely invalid JSON should raise."""
        from app.services.sentiment import _parse_scores
        with pytest.raises(Exception):
            _parse_scores("not json at all", self._headlines(1))

    def test_parse_skips_out_of_range_ids(self):
        """IDs beyond the headline list should be skipped."""
        from app.services.sentiment import _parse_scores
        raw = json.dumps({
            "scores": [
                {"id": 0, "score": 0.1, "confidence": 0.5, "categories": ["other"]},
                {"id": 99, "score": 0.9, "confidence": 0.9, "categories": ["earnings"]},
            ]
        })
        scored = _parse_scores(raw, self._headlines(2))
        assert len(scored) == 1


# ---------------------------------------------------------------------------
# 4. Yield Curve Fallback
# ---------------------------------------------------------------------------

class TestYieldCurveFallback:
    """Test the Yahoo Finance Treasury yield fallback."""

    @pytest.mark.asyncio
    async def test_yahoo_fallback_parses_valid_response(self):
        from app.services.market_brief import _fetch_treasury_yields_yahoo

        mock_response = {
            "chart": {
                "result": [{
                    "indicators": {
                        "quote": [{"close": [4.25, 4.28, 4.30, None, 4.29]}]
                    }
                }],
                "error": None,
            }
        }

        async def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = mock_response
            return resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.market_brief.httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_treasury_yields_yahoo()

        # Should have parsed at least one yield
        assert len(result) > 0
        for label, data in result.items():
            assert "rate" in data
            assert "source" in data
            assert data["source"] == "Yahoo Finance"
            assert isinstance(data["rate"], float)

    @pytest.mark.asyncio
    async def test_yahoo_fallback_handles_api_error(self):
        from app.services.market_brief import _fetch_treasury_yields_yahoo

        mock_response = {"chart": {"error": {"code": "Not Found"}, "result": None}}

        async def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = mock_response
            return resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.market_brief.httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_treasury_yields_yahoo()

        assert result == {}

    @pytest.mark.asyncio
    async def test_yahoo_fallback_handles_http_error(self):
        from app.services.market_brief import _fetch_treasury_yields_yahoo

        async def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 403
            return resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.market_brief.httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_treasury_yields_yahoo()

        assert result == {}


# ---------------------------------------------------------------------------
# 5. Options Flow Parsing
# ---------------------------------------------------------------------------

class TestOptionsFlow:
    """Test VIX-based options flow signal generation."""

    @pytest.mark.asyncio
    async def test_vix_classification_thresholds(self):
        """Test that VIX values map to correct signal classifications."""
        import time
        from app.services.market_brief import _fetch_options_flow

        def _make_yahoo_response(vix_value: float):
            """Build a fake Yahoo Finance VIX chart response."""
            now = int(time.time())
            # Need at least 10 data points for high/low calc
            timestamps = [now - i * 86400 for i in range(10, 0, -1)]
            closes = [vix_value] * 10
            return {
                "chart": {
                    "result": [{
                        "timestamp": timestamps,
                        "indicators": {"quote": [{"close": closes}]},
                    }],
                    "error": None,
                }
            }

        async def _run(vix: float) -> dict:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = _make_yahoo_response(vix)
            with patch("app.services.market_brief.httpx.AsyncClient") as MockClient:
                client = AsyncMock()
                client.get.return_value = mock_resp
                client.__aenter__ = AsyncMock(return_value=client)
                client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = client
                return await _fetch_options_flow()

        extreme = await _run(40.0)
        assert extreme["signal"] == "EXTREME_FEAR"

        elevated_fear = await _run(28.0)
        assert elevated_fear["signal"] == "ELEVATED_FEAR"

        cautious = await _run(22.0)
        assert cautious["signal"] == "CAUTIOUS"

        neutral = await _run(16.0)
        assert neutral["signal"] == "NEUTRAL"

        complacent = await _run(13.0)
        assert complacent["signal"] == "COMPLACENT"


# ---------------------------------------------------------------------------
# 6. LLM Routing
# ---------------------------------------------------------------------------

class TestLLMRouting:
    """Test the LLM routing layer."""

    @pytest.mark.asyncio
    async def test_local_tier_tries_ollama_first(self):
        from app.services.llm import call_llm

        with patch("app.services.llm.get_settings") as mock_settings:
            settings = MagicMock()
            settings.ollama_base_url = "http://localhost:11434"
            settings.ollama_model = "gemma4:e2b"
            settings.mistral_api_key = "test-key"
            mock_settings.return_value = settings

            with patch("app.services.llm._call_ollama", new_callable=AsyncMock, return_value="ollama response") as mock_ollama:
                result = await call_llm("system", "user", tier="local")
                assert result == "ollama response"
                mock_ollama.assert_called_once()

    @pytest.mark.asyncio
    async def test_local_tier_falls_back_to_mistral(self):
        from app.services.llm import call_llm

        with patch("app.services.llm.get_settings") as mock_settings:
            settings = MagicMock()
            settings.ollama_base_url = "http://localhost:11434"
            settings.ollama_model = "gemma4:e2b"
            settings.mistral_api_key = "test-key"
            mock_settings.return_value = settings

            with patch("app.services.llm._call_ollama", new_callable=AsyncMock, side_effect=Exception("connection refused")), \
                 patch("app.services.llm._call_mistral_api", new_callable=AsyncMock, return_value="mistral response") as mock_mistral:
                result = await call_llm("system", "user", tier="local")
                assert result == "mistral response"
                mock_mistral.assert_called_once()

    @pytest.mark.asyncio
    async def test_cloud_tier_skips_ollama(self):
        from app.services.llm import call_llm

        with patch("app.services.llm.get_settings") as mock_settings:
            settings = MagicMock()
            settings.ollama_base_url = "http://localhost:11434"
            settings.mistral_api_key = "test-key"
            mock_settings.return_value = settings

            with patch("app.services.llm._call_ollama", new_callable=AsyncMock) as mock_ollama, \
                 patch("app.services.llm._call_mistral_api", new_callable=AsyncMock, return_value="cloud response"):
                result = await call_llm("system", "user", tier="cloud")
                assert result == "cloud response"
                mock_ollama.assert_not_called()

    @pytest.mark.asyncio
    async def test_local_only_raises_when_ollama_unavailable(self):
        from app.services.llm import call_llm

        with patch("app.services.llm.get_settings") as mock_settings:
            settings = MagicMock()
            settings.ollama_base_url = ""
            settings.mistral_api_key = ""
            mock_settings.return_value = settings

            with pytest.raises(Exception, match="Ollama not configured"):
                await call_llm("system", "user", tier="local_only")


# ---------------------------------------------------------------------------
# 7. Discipline Scoring Rules
# ---------------------------------------------------------------------------

class TestDisciplineScoring:
    """Test discipline scoring rule evaluation."""

    def test_discipline_rules_exist_for_all_personalities(self):
        from app.services.analytics import DISCIPLINE_RULES
        from app.services.ai_trader import PERSONALITIES

        for pkey in PERSONALITIES:
            assert pkey in DISCIPLINE_RULES, f"No discipline rules for {pkey}"
            assert len(DISCIPLINE_RULES[pkey]) >= 2, f"Too few rules for {pkey}"

    def test_each_rule_has_required_fields(self):
        from app.services.analytics import DISCIPLINE_RULES

        for pkey, rules in DISCIPLINE_RULES.items():
            for rule in rules:
                assert "id" in rule, f"Missing id in {pkey} rule"
                assert "label" in rule, f"Missing label in {pkey} rule"


# ---------------------------------------------------------------------------
# 8. AI Trade Response Parsing
# ---------------------------------------------------------------------------

class TestTradeResponseParsing:
    """Test parsing of LLM trade responses."""

    def test_parse_valid_trade_json(self):
        """Valid JSON trade response should parse correctly."""
        raw = json.dumps({
            "trades": [
                {"symbol": "AAPL", "asset_type": "stock", "side": "buy",
                 "quantity": 10, "reasoning": "Strong fundamentals",
                 "modules_used": ["fundamentals", "technicals"]},
                {"symbol": "BTC", "asset_type": "crypto", "side": "sell",
                 "quantity": 0.5, "reasoning": "Taking profits",
                 "modules_used": ["momentum"]},
            ]
        })
        data = json.loads(raw)
        trades = data.get("trades", [])
        assert len(trades) == 2
        assert trades[0]["symbol"] == "AAPL"
        assert trades[1]["side"] == "sell"

    def test_parse_markdown_wrapped_trades(self):
        """LLMs sometimes wrap JSON in markdown code fences."""
        raw = '```json\n{"trades": [{"symbol": "NVDA", "asset_type": "stock", "side": "buy", "quantity": 5, "reasoning": "AI boom", "modules_used": ["technicals"]}]}\n```'
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        data = json.loads(text)
        assert len(data["trades"]) == 1
        assert data["trades"][0]["symbol"] == "NVDA"

    def test_parse_empty_trades(self):
        """LLM returns no trades — should be valid."""
        raw = '{"trades": []}'
        data = json.loads(raw)
        assert data["trades"] == []

    @pytest.mark.asyncio
    async def test_get_ai_trades_no_name_error(self):
        """Regression: _get_ai_trades must not reference undefined display_name."""
        from app.services.ai_trader import _get_ai_trades

        mock_response = '{"trades": []}'
        with patch("app.services.ai_trader._call_mistral", new_callable=AsyncMock, return_value=mock_response), \
             patch("app.services.ai_trader.get_settings") as mock_settings:
            settings = MagicMock()
            settings.mistral_api_key = "test-key"
            mock_settings.return_value = settings

            # This should NOT raise NameError. Returns (trades, conditional_orders).
            trades, cond_orders = await _get_ai_trades(
                "contrarian_carl", "mistral",
                brief={"stocks": [], "crypto": [], "news": [], "stock_technicals": {},
                       "crypto_technicals": {}, "fundamentals": {}, "analyst_recommendations": {},
                       "earnings_calendar": [], "economic_calendar": [], "insider_transactions": {},
                       "social_sentiment": {}, "options_flow": {}, "yield_curve": {}},
                portfolio={"cash": 100_000, "positions": []},
                trade_memory="",
            )
            assert isinstance(trades, list)
            assert isinstance(cond_orders, list)


# ---------------------------------------------------------------------------
# 9. Market Brief Technicals
# ---------------------------------------------------------------------------

class TestBriefTechnicals:
    """Test technical indicator calculations used in the market brief."""

    def test_compute_atr(self):
        from app.services.market_brief import _compute_atr

        # Build 15 candles with known high/low/close
        candles = []
        for i in range(16):
            price = 100 + i
            candles.append({
                "high": price + 2,
                "low": price - 2,
                "close": price,
            })

        atr = _compute_atr(candles, period=14)
        assert atr is not None
        assert atr > 0
        # With constant $4 range (high-low), ATR should be ~4
        assert 3.5 <= atr <= 5.0

    def test_compute_atr_insufficient_data(self):
        from app.services.market_brief import _compute_atr
        candles = [{"high": 102, "low": 98, "close": 100}] * 5
        assert _compute_atr(candles, period=14) is None

    def test_compute_historical_volatility(self):
        from app.services.market_brief import _compute_historical_volatility

        # Constant prices = zero volatility
        closes = [100.0] * 25
        vol = _compute_historical_volatility(closes)
        assert vol == 0.0

        # Alternating prices = nonzero volatility
        closes = [100 + (i % 2) * 2 for i in range(25)]
        vol = _compute_historical_volatility(closes)
        assert vol is not None
        assert vol > 0


# ---------------------------------------------------------------------------
# 10. Earnings Urgency Formatting
# ---------------------------------------------------------------------------

class TestEarningsUrgency:
    """Test that earnings get TODAY/TOMORROW prefixes in the RAG toolkit."""

    def test_today_earnings_get_prefix(self):
        from app.services.rag_toolkit import _format_fundamentals

        today_str = date.today().isoformat()
        brief = {
            "fundamentals": {},
            "analyst_recommendations": {},
            "insider_transactions": {},
            "earnings_calendar": [
                {"symbol": "AAPL", "date": today_str, "estimate_eps": 1.52},
            ],
        }

        result = _format_fundamentals(brief)
        assert ">>> TODAY" in result

    def test_regular_earnings_get_date_prefix(self):
        from app.services.rag_toolkit import _format_fundamentals

        future = (date.today() + timedelta(days=5)).isoformat()
        brief = {
            "fundamentals": {},
            "analyst_recommendations": {},
            "insider_transactions": {},
            "earnings_calendar": [
                {"symbol": "MSFT", "date": future, "estimate_eps": 2.10},
            ],
        }

        result = _format_fundamentals(brief)
        assert future in result
        assert "TODAY" not in result


# ---------------------------------------------------------------------------
# 11. AI Trading Loop Integration Test
# ---------------------------------------------------------------------------

class TestRunTraderIntegration:
    """End-to-end test of _run_trader with mocked DB and LLM."""

    def _mock_db(self, *, has_traded_today: bool = False, positions=None, cash=100_000.0):
        """Build a mock Supabase client."""
        db = MagicMock()

        # transactions check (already traded today?)
        tx_chain = db.table("transactions").select("id").eq("user_id", "ai-1").gte("created_at", MagicMock())
        tx_result = MagicMock()
        tx_result.data = [{"id": "tx1"}] if has_traded_today else []
        tx_chain.limit.return_value.execute.return_value = tx_result

        # More flexible: handle arbitrary .table().select().eq().gte().limit().execute() chains
        def table_router(name):
            t = MagicMock()
            if name == "transactions":
                sel = MagicMock()
                eq1 = MagicMock()
                gte1 = MagicMock()
                lim = MagicMock()
                result = MagicMock()
                result.data = [{"id": "tx1"}] if has_traded_today else []
                t.select.return_value = sel
                sel.eq.return_value = eq1
                eq1.gte.return_value = gte1
                gte1.limit.return_value = lim
                lim.execute.return_value = result
            return t

        db.table.side_effect = table_router
        return db

    def _sample_brief(self):
        return {
            "stock_prices": {"AAPL": {"price": 175.0, "change_pct": 1.2}},
            "crypto_prices": {},
            "news": [{"headline": "Apple beats earnings", "source": "Reuters"}],
            "stock_technicals": {"AAPL": {"atr": 3.5, "atr_pct": 2.0}},
            "crypto_technicals": {},
            "fundamentals": {},
            "analyst_recommendations": {},
            "earnings_calendar": [],
            "economic_calendar": [],
            "insider_transactions": {},
            "social_sentiment": {},
            "options_flow": {"vix": 18.5, "signal": "NEUTRAL"},
            "yield_curve": {"10y": 4.3, "2y": 4.1, "spread": 0.2},
        }

    def _sample_profile(self):
        return {
            "id": "ai-1",
            "display_name": "Vanilla (Mistral Large)",
            "ai_model": "mistral",
            "is_ai": True,
        }

    @pytest.mark.asyncio
    async def test_skip_when_already_traded(self):
        """Trader that already traded today should be skipped."""
        from app.services.ai_trader import _run_trader

        db = self._mock_db(has_traded_today=True)
        result = await _run_trader(db, self._sample_brief(), self._sample_profile())
        assert result["status"] == "skipped"
        assert "already traded" in result["reason"]

    @pytest.mark.asyncio
    async def test_full_cycle_executes_trades(self):
        """Mock LLM returns a trade → _run_trader should execute it."""
        from app.services.ai_trader import _run_trader

        db = self._mock_db(has_traded_today=False)

        mock_portfolio = {
            "cash": 100_000.0,
            "positions": [],
        }

        mock_trades = [
            {"symbol": "AAPL", "asset_type": "stock", "side": "buy",
             "quantity": 10, "reasoning": "Strong earnings beat",
             "modules_used": ["fundamentals", "technicals"]},
        ]

        mock_execute_result = {
            "symbol": "AAPL", "side": "buy", "quantity": 10,
            "price": 175.0, "total": 1750.0,
        }

        with patch("app.services.ai_trader._get_ai_portfolio", new_callable=AsyncMock, return_value=mock_portfolio), \
             patch("app.services.ai_trader._get_ai_trade_history", return_value=[]), \
             patch("app.services.ai_trader._format_trade_memory", return_value="No recent trades."), \
             patch("app.services.reflection.get_reflection_memory", return_value=""), \
             patch("app.services.ai_trader._get_ai_trades", new_callable=AsyncMock, return_value=(mock_trades, [])), \
             patch("app.services.ai_trader._execute_ai_trade", new_callable=AsyncMock, return_value=mock_execute_result):

            result = await _run_trader(db, self._sample_brief(), self._sample_profile())

        assert result["status"] == "ok"
        assert result["trades_proposed"] == 1
        assert result["trades_executed"] == 1
        assert result["trades"][0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_llm_returns_no_trades(self):
        """LLM decides to hold — no trades executed."""
        from app.services.ai_trader import _run_trader

        db = self._mock_db(has_traded_today=False)

        mock_portfolio = {"cash": 100_000.0, "positions": []}

        with patch("app.services.ai_trader._get_ai_portfolio", new_callable=AsyncMock, return_value=mock_portfolio), \
             patch("app.services.ai_trader._get_ai_trade_history", return_value=[]), \
             patch("app.services.ai_trader._format_trade_memory", return_value=""), \
             patch("app.services.reflection.get_reflection_memory", return_value=""), \
             patch("app.services.ai_trader._get_ai_trades", new_callable=AsyncMock, return_value=([], [])), \
             patch("app.services.ai_trader._execute_ai_trade", new_callable=AsyncMock) as mock_exec:

            result = await _run_trader(db, self._sample_brief(), self._sample_profile())

        assert result["status"] == "ok"
        assert result["trades_proposed"] == 0
        assert result["trades_executed"] == 0
        mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_personality_skipped(self):
        """Profile with unrecognized personality name should be skipped."""
        from app.services.ai_trader import _run_trader

        db = self._mock_db()
        profile = {"id": "ai-99", "display_name": "Unknown Bot", "ai_model": "mistral", "is_ai": True}

        result = await _run_trader(db, self._sample_brief(), profile)
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_unknown_model_skipped(self):
        """Profile with unrecognized model key should be skipped."""
        from app.services.ai_trader import _run_trader

        db = self._mock_db()
        profile = {"id": "ai-1", "display_name": "Vanilla (BadModel)", "ai_model": "nonexistent", "is_ai": True}

        result = await _run_trader(db, self._sample_brief(), profile)
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_trader_error_returns_error_status(self):
        """If _get_ai_portfolio raises, _run_trader should return error status."""
        from app.services.ai_trader import _run_trader

        db = self._mock_db(has_traded_today=False)

        with patch("app.services.ai_trader._get_ai_portfolio", new_callable=AsyncMock, side_effect=Exception("DB connection lost")):
            result = await _run_trader(db, self._sample_brief(), self._sample_profile())

        assert result["status"] == "error"
        assert "DB connection lost" in result["error"]


# ---------------------------------------------------------------------------
# 10. Cross-module name binding (regression)
# ---------------------------------------------------------------------------

class TestResolverNameBinding:
    """Regression for the 2026-06-13 resolver sweep: ai_commentary.py gained a
    call to resolve_personality_key() but not the import. py_compile and module
    import both pass on that bug — it only NameErrors at call time, which
    silently killed the nightly commentary phase for 18 days (zero daily
    journals 6/14-7/01). Assert the name is bound in every module that calls
    it at module scope. (analytics.py imports it function-locally and is
    covered by its own usage paths.)"""

    def test_resolve_personality_key_bound_in_all_consumers(self):
        import app.services.ai_commentary as ai_commentary
        import app.services.backtest as backtest
        import app.services.journal_summary as journal_summary
        import app.routers.ai as ai_router
        import app.services.ai_trader as ai_trader

        for mod in (ai_commentary, backtest, journal_summary, ai_router, ai_trader):
            assert hasattr(mod, "resolve_personality_key"), (
                f"{mod.__name__} calls resolve_personality_key but does not "
                f"bind it — nightly phase using it will NameError at runtime"
            )
