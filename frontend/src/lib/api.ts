const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class ApiClient {
  private token: string | null = null;

  setToken(token: string | null) {
    this.token = token;
  }

  private async request<T>(
    path: string,
    options: RequestInit = {}
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

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Request failed" }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }

    return res.json();
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

  async getLeaderboard(limit = 20) {
    return this.request<
      {
        rank: number;
        display_name: string;
        total_portfolio_value: number;
        cash_balance: number;
        invested_value: number;
      }[]
    >(`/api/portfolio/leaderboard?limit=${limit}`);
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
}

export const api = new ApiClient();
