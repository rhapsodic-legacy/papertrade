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

  async getMarketStatus() {
    return this.request<{
      stock_market_open: boolean;
      crypto_market_open: boolean;
    }>("/api/market/status");
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
  async getCommentary(date?: string, limit = 10) {
    const params = new URLSearchParams();
    if (date) params.set("date", date);
    params.set("limit", String(limit));
    return this.request<{
      entries: {
        display_name: string;
        personality: string;
        model: string;
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
}

export const api = new ApiClient();
