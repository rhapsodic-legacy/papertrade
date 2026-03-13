import { api } from "@/lib/api";

// Mock global fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

beforeEach(() => {
  mockFetch.mockReset();
  api.setToken(null);
});

describe("ApiClient", () => {
  describe("authentication", () => {
    it("sends auth header when token is set", async () => {
      api.setToken("test-token");
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: "1", display_name: "Test", cash_balance: 100000 }),
      });

      await api.getProfile();

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: "Bearer test-token",
          }),
        })
      );
    });

    it("does not send auth header when no token", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ stocks: [], crypto: [] }),
      });

      await api.getAssets();

      const headers = mockFetch.mock.calls[0][1].headers;
      expect(headers.Authorization).toBeUndefined();
    });
  });

  describe("signIn", () => {
    it("sends email and password", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          access_token: "token",
          refresh_token: "refresh",
          user_id: "1",
          email: "test@example.com",
        }),
      });

      const result = await api.signIn("test@example.com", "password123");

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/auth/signin"),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ email: "test@example.com", password: "password123" }),
        })
      );
      expect(result.access_token).toBe("token");
    });
  });

  describe("error handling", () => {
    it("throws on non-ok response", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: "Invalid credentials" }),
      });

      await expect(api.signIn("bad@email.com", "wrong")).rejects.toThrow(
        "Invalid credentials"
      );
    });

    it("handles non-JSON error responses", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => {
          throw new Error("not json");
        },
      });

      await expect(api.getAssets()).rejects.toThrow("Request failed");
    });
  });

  describe("placeTrade", () => {
    it("sends correct trade payload", async () => {
      api.setToken("test-token");
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          id: "tx-1",
          symbol: "AAPL",
          asset_type: "stock",
          side: "buy",
          quantity: 10,
          price: 175.0,
          total: 1750.0,
          created_at: "2026-03-11T00:00:00Z",
        }),
      });

      const result = await api.placeTrade("AAPL", "stock", "buy", 10);

      const body = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(body.symbol).toBe("AAPL");
      expect(body.asset_type).toBe("stock");
      expect(body.side).toBe("buy");
      expect(body.quantity).toBe(10);
      expect(result.total).toBe(1750.0);
    });
  });

  describe("watchlist", () => {
    it("fetches watchlist", async () => {
      api.setToken("test-token");
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => [
          { id: "w1", symbol: "AAPL", asset_type: "stock", price: 175, change: 2, change_pct: 1.15, name: "Apple" },
        ],
      });

      const result = await api.getWatchlist();

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/watchlist/"),
        expect.any(Object)
      );
      expect(result).toHaveLength(1);
      expect(result[0].symbol).toBe("AAPL");
    });

    it("adds to watchlist", async () => {
      api.setToken("test-token");
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: "w2", symbol: "BTC", asset_type: "crypto" }),
      });

      const result = await api.addToWatchlist("BTC", "crypto");

      const body = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(body.symbol).toBe("BTC");
      expect(body.asset_type).toBe("crypto");
      expect(result.symbol).toBe("BTC");
    });

    it("removes from watchlist", async () => {
      api.setToken("test-token");
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ message: "AAPL removed from watchlist" }),
      });

      await api.removeFromWatchlist("AAPL");

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/watchlist/AAPL"),
        expect.objectContaining({ method: "DELETE" })
      );
    });
  });

  describe("snapshots", () => {
    it("fetches portfolio snapshots", async () => {
      api.setToken("test-token");
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => [
          { snapshot_date: "2026-03-12", total_value: 100500, cash_balance: 90000, invested_value: 10500 },
          { snapshot_date: "2026-03-13", total_value: 101000, cash_balance: 90000, invested_value: 11000 },
        ],
      });

      const result = await api.getSnapshots();

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/portfolio/snapshots?days=30"),
        expect.any(Object)
      );
      expect(result).toHaveLength(2);
      expect(result[0].total_value).toBe(100500);
    });
  });

  describe("getQuote", () => {
    it("constructs correct URL", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          symbol: "BTC",
          asset_type: "crypto",
          price: 65000,
          change: null,
          change_pct: null,
          name: "Bitcoin",
        }),
      });

      await api.getQuote("crypto", "BTC");

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/market/quote/crypto/BTC"),
        expect.any(Object)
      );
    });
  });
});
