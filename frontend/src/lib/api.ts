const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class ApiClient {
  private token: string | null = null;
  private onSessionExpired: (() => void) | null = null;
  private refreshing: Promise<boolean> | null = null;

  setToken(token: string | null) {
    this.token = token;
  }

  setOnSessionExpired(callback: () => void) {
    this.onSessionExpired = callback;
  }

  private async request<T>(
    path: string,
    options: RequestInit = {},
    isRetry = false
  ): Promise<T> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    };

    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }

    const res = await fetch(`${API_URL}${path}`, {
      ...options,
      headers,
    });

    if (res.status === 401 && !isRetry && path !== "/api/auth/refresh") {
      const refreshed = await this.tryRefresh();
      if (refreshed) {
        return this.request<T>(path, options, true);
      }
      if (this.onSessionExpired) this.onSessionExpired();
    }

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Request failed" }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }

    return res.json();
  }

  private async tryRefresh(): Promise<boolean> {
    if (this.refreshing) return this.refreshing;

    this.refreshing = (async () => {
      const refreshToken = localStorage.getItem("refresh_token");
      if (!refreshToken) return false;

      try {
        const res = await fetch(`${API_URL}/api/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!res.ok) return false;

        const data = await res.json();
        this.token = data.access_token;
        localStorage.setItem("access_token", data.access_token);
        localStorage.setItem("refresh_token", data.refresh_token);
        return true;
      } catch {
        return false;
      } finally {
        this.refreshing = null;
      }
    })();

    return this.refreshing;
  }

  // Auth
  async signUp(email: string, password: string, displayName?: string) {
    return this.request<{
      access_token: string;
      refresh_token: string;
      user_id: string;
      email: string;
    }>("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password, display_name: displayName }),
    });
  }

  async signIn(email: string, password: string) {
    return this.request<{
      access_token: string;
      refresh_token: string;
      user_id: string;
      email: string;
    }>("/api/auth/signin", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  }

  async resetPassword(email: string) {
    return this.request<{ message: string }>("/api/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  }

  async updatePassword(accessToken: string, refreshToken: string, newPassword: string) {
    return this.request<{ message: string }>("/api/auth/update-password", {
      method: "POST",
      body: JSON.stringify({ access_token: accessToken, refresh_token: refreshToken, new_password: newPassword }),
    });
  }

  async refreshSession(refreshToken: string) {
    return this.request<{
      access_token: string;
      refresh_token: string;
    }>("/api/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  }

  async getProfile() {
    return this.request<{
      id: string;
      display_name: string;
      cash_balance: number;
    }>("/api/auth/profile");
  }

  // Market
  async getAssets() {
    return this.request<{
      stocks: { symbol: string; name: string }[];
      crypto: { symbol: string; name: string }[];
    }>("/api/market/assets");
  }

  async getQuote(assetType: string, symbol: string) {
    return this.request<{
      symbol: string;
      asset_type: string;
      price: number;
      change: number | null;
      change_pct: number | null;
      name: string | null;
    }>(`/api/market/quote/${assetType}/${symbol}`);
  }

  async getPriceHistory(assetType: string, symbol: string, days = 30) {
    return this.request<{
      symbol: string;
      asset_type: string;
      candles: { time: number; close: number; open?: number; high?: number; low?: number }[];
    }>(`/api/market/history/${assetType}/${symbol}?days=${days}`);
  }

  async getMarketStatus() {
    return this.request<{
      stock_market_open: boolean;
      crypto_market_open: boolean;
    }>("/api/market/status");
  }

  async getAssetDetails(assetType: string, symbol: string) {
    return this.request<{
      symbol: string;
      asset_type: string;
      fundamentals?: {
        pe_ratio: number | null;
        market_cap_m: number | null;
        "52w_high": number | null;
        "52w_low": number | null;
        beta: number | null;
        dividend_yield: number | null;
      };
      technicals?: {
        sma_20?: number;
        sma_50?: number;
        vs_sma_20?: number;
        vs_sma_50?: number;
        rsi_14?: number;
        "7d_return"?: number;
        "30d_return"?: number;
      };
      analyst?: {
        buy: number;
        hold: number;
        sell: number;
      };
      earnings?: {
        symbol: string;
        date: string | null;
        estimate_eps: number | null;
      };
      market_data?: {
        market_cap_rank: number | null;
        market_cap_b: number | null;
        volume_24h_m: number | null;
        ath: number | null;
        ath_drop_pct: number | null;
      };
    }>(`/api/market/details/${assetType}/${symbol}`);
  }

  // Portfolio
  async getPortfolio() {
    return this.request<{
      cash_balance: number;
      invested_value: number;
      total_value: number;
      positions: {
        symbol: string;
        asset_type: string;
        quantity: number;
        avg_cost_basis: number;
        current_price: number;
        market_value: number;
        unrealized_pnl: number;
        unrealized_pnl_pct: number;
      }[];
    }>("/api/portfolio/");
  }

  async getHistory(limit = 50) {
    return this.request<
      {
        id: string;
        symbol: string;
        asset_type: string;
        side: string;
        quantity: number;
        price: number;
        total: number;
        created_at: string;
      }[]
    >(`/api/portfolio/history?limit=${limit}`);
  }

  async getLeaderboard(category: "human" | "ai" = "human", limit = 25) {
    return this.request<{
      entries: {
        rank: number;
        display_name: string;
        score: number;
        return_1d: number;
        return_7d: number;
        return_30d: number;
        return_90d: number;
        is_ai: boolean;
        ai_model: string | null;
        user_id?: string;
      }[];
      user_entry: {
        rank: number;
        display_name: string;
        score: number;
        return_1d: number;
        return_7d: number;
        return_30d: number;
        return_90d: number;
        is_ai: boolean;
        ai_model: string | null;
      } | null;
    }>(`/api/portfolio/leaderboard?category=${category}&limit=${limit}`);
  }

  async getSnapshots(days = 30) {
    return this.request<
      {
        snapshot_date: string;
        total_value: number;
        cash_balance: number;
        invested_value: number;
      }[]
    >(`/api/portfolio/snapshots?days=${days}`);
  }

  // Trading
  async placeTrade(
    symbol: string,
    assetType: "stock" | "crypto",
    side: "buy" | "sell",
    quantity: number
  ) {
    return this.request<{
      id: string;
      symbol: string;
      asset_type: string;
      side: string;
      quantity: number;
      price: number;
      total: number;
      created_at: string;
    }>("/api/trading/trade", {
      method: "POST",
      body: JSON.stringify({
        symbol,
        asset_type: assetType,
        side,
        quantity,
      }),
    });
  }
  // Watchlist
  async getWatchlist() {
    return this.request<
      {
        id: string;
        symbol: string;
        asset_type: string;
        price: number | null;
        change: number | null;
        change_pct: number | null;
        name: string;
      }[]
    >("/api/watchlist/");
  }

  async addToWatchlist(symbol: string, assetType: "stock" | "crypto") {
    return this.request<{ id: string; symbol: string; asset_type: string }>(
      "/api/watchlist/",
      {
        method: "POST",
        body: JSON.stringify({ symbol, asset_type: assetType }),
      }
    );
  }

  async removeFromWatchlist(symbol: string) {
    return this.request<{ message: string }>(`/api/watchlist/${symbol}`, {
      method: "DELETE",
    });
  }

  // AI Commentary
  async getCommentary(date?: string, limit = 50) {
    const params = new URLSearchParams();
    if (date) params.set("date", date);
    params.set("limit", String(limit));
    return this.request<{
      entries: {
        display_name: string;
        personality: string;
        model: string;
        headline: string;
        commentary: string;
        trades_summary: {
          symbol: string;
          side: string;
          quantity: number;
          price: number;
        }[];
        date: string;
      }[];
    }>(`/api/ai/commentary?${params.toString()}`);
  }

  async getCommentaryDates(limit = 30) {
    return this.request<{ dates: string[] }>(
      `/api/ai/commentary/dates?limit=${limit}`
    );
  }

  async getTraderCommentary(traderId: string, limit = 30) {
    return this.request<{
      entries: {
        display_name: string;
        personality: string;
        model: string;
        headline: string;
        commentary: string;
        trades_summary: {
          symbol: string;
          side: string;
          quantity: number;
          price: number;
        }[];
        date: string;
      }[];
    }>(`/api/ai/traders/${traderId}/commentary?limit=${limit}`);
  }

  // AI Traders
  async getAiTraders() {
    return this.request<{
      traders: {
        id: string;
        display_name: string;
        ai_model: string;
        personality: string;
      }[];
    }>("/api/ai/traders");
  }

  // Analytics
  async getTraderAnalytics(traderId: string) {
    return this.request<{
      trader: {
        id: string;
        display_name: string;
        ai_model: string | null;
        is_ai: boolean;
      };
      analytics: {
        total_trades: number;
        buy_count: number;
        sell_count: number;
        win_rate: number;
        avg_win: number;
        avg_loss: number;
        largest_win: number;
        largest_loss: number;
        total_realized_pnl: number;
        profit_factor: number;
        sharpe_ratio: number;
        max_drawdown_pct: number;
        max_drawdown_date: string | null;
        annualized_volatility: number;
        current_drawdown_pct: number;
        total_return_pct: number;
        daily_returns: { date: string; total_value: number; return_pct: number }[];
        sector_exposure: { sector: string; value: number; pct: number }[];
        trade_history: { date: string; buys: number; sells: number; volume: number }[];
        total_snapshots: number;
      };
    }>(`/api/analytics/trader/${traderId}`);
  }

  async getAiComparison() {
    return this.request<{
      traders: {
        id: string;
        display_name: string;
        model: string;
        personality: string;
        win_rate: number;
        total_trades: number;
        total_realized_pnl: number;
        profit_factor: number;
        sharpe_ratio: number;
        max_drawdown_pct: number;
        total_return_pct: number;
        annualized_volatility: number;
      }[];
      by_model: Record<string, {
        count: number;
        avg_win_rate: number;
        avg_return_pct: number;
        avg_sharpe: number;
        avg_max_drawdown: number;
        avg_profit_factor: number;
        total_trades: number;
        best_trader: string;
        worst_trader: string;
      }>;
      by_personality: Record<string, {
        count: number;
        avg_win_rate: number;
        avg_return_pct: number;
        avg_sharpe: number;
        avg_max_drawdown: number;
        avg_profit_factor: number;
        total_trades: number;
        best_trader: string;
        worst_trader: string;
      }>;
    }>("/api/analytics/comparison");
  }

  async getBenchmark(days = 90) {
    return this.request<{
      period_days: number;
      start_date: string;
      end_date: string;
      benchmark: {
        symbol: string;
        return_pct: number;
        start_price: number;
        end_price: number;
        series: { date: string; return_pct: number }[];
      };
      traders: {
        id: string;
        display_name: string;
        model: string;
        personality: string;
        total_return_pct: number;
        beats_spy: boolean;
        alpha: number;
        series: { date: string; return_pct: number }[];
      }[];
      summary: {
        total_traders: number;
        beating_spy: number;
        losing_to_spy: number;
        avg_alpha: number;
        best_trader: string | null;
        worst_trader: string | null;
      };
    }>(`/api/analytics/benchmark?days=${days}`);
  }

  async getEnhancementComparison() {
    return this.request<{
      enhancement_date: string;
      traders: {
        display_name: string;
        model: string;
        personality: string;
        pre_enhancement: { days: number; total_return_pct: number; daily_return_avg: number; start_value: number; end_value: number };
        post_enhancement: { days: number; total_return_pct: number; daily_return_avg: number; start_value: number; end_value: number };
        improved: boolean | null;
      }[];
      summary: {
        total_traders: number;
        with_both_periods: number;
        improved: number;
        not_improved: number;
      };
    }>("/api/analytics/enhancement");
  }

  async getAiTraderProfile(traderId: string) {
    return this.request<{
      display_name: string;
      ai_model: string;
      personality: string;
      personality_description: string | null;
      cash_balance: number;
      invested_value: number;
      total_value: number;
      positions: {
        symbol: string;
        asset_type: string;
        quantity: number;
        avg_cost: number;
        current_price: number;
        market_value: number;
      }[];
      trades: {
        symbol: string;
        asset_type: string;
        side: string;
        quantity: number;
        price: number;
        total: number;
        created_at: string;
        reasoning: string | null;
      }[];
      commentary: {
        commentary: string;
        trades_summary: string;
        commentary_date: string;
      }[];
      snapshots: {
        snapshot_date: string;
        total_value: number;
      }[];
    }>(`/api/ai/traders/${traderId}`);
  }

  // Portfolio Health
  async getPortfolioHealth() {
    return this.request<{
      score: number;
      grade: string;
      score_breakdown: {
        name: string;
        score: number;
        max: number;
        tip: string;
      }[];
      metrics: {
        total_trades: number;
        buy_count: number;
        sell_count: number;
        win_rate: number;
        avg_win: number;
        avg_loss: number;
        largest_win: number;
        largest_loss: number;
        total_realized_pnl: number;
        profit_factor: number;
        sharpe_ratio: number;
        max_drawdown_pct: number;
        max_drawdown_date: string | null;
        annualized_volatility: number;
        current_drawdown_pct: number;
        total_return_pct: number;
        daily_returns: { date: string; total_value: number; return_pct: number }[];
        sector_exposure: { sector: string; value: number; pct: number }[];
        trade_history: { date: string; buys: number; sells: number; volume: number }[];
        total_snapshots: number;
      };
      ai_comparison: {
        avg_return_pct: number;
        avg_sharpe: number;
        avg_win_rate: number;
        avg_max_drawdown: number;
        avg_profit_factor: number;
        total_ai_traders: number;
        user_beats_n: number;
        user_rank: number;
      };
    }>("/api/portfolio/health");
  }
}

export const api = new ApiClient();
