"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { formatCurrency, formatPrice } from "@/lib/utils";
import Navbar from "@/components/Navbar";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface Asset {
  symbol: string;
  name: string;
}

interface Quote {
  symbol: string;
  asset_type: string;
  price: number;
  change: number | null;
  change_pct: number | null;
  name: string | null;
}

export default function TradePage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [assets, setAssets] = useState<{ stocks: Asset[]; crypto: Asset[] }>({
    stocks: [],
    crypto: [],
  });
  const [assetType, setAssetType] = useState<"stock" | "crypto">("stock");
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [quantity, setQuantity] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [chartData, setChartData] = useState<{ date: string; price: number }[]>(
    []
  );
  const [chartDays, setChartDays] = useState(30);
  const [chartLoading, setChartLoading] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) router.push("/auth");
  }, [user, authLoading, router]);

  useEffect(() => {
    api.getAssets().then(setAssets).catch(console.error);
  }, []);

  useEffect(() => {
    if (!selectedSymbol) {
      setQuote(null);
      return;
    }
    const fetchQuote = () => {
      api
        .getQuote(assetType, selectedSymbol)
        .then(setQuote)
        .catch(() => setQuote(null));
    };
    fetchQuote();
    const interval = setInterval(fetchQuote, 30000); // refresh every 30s
    return () => clearInterval(interval);
  }, [selectedSymbol, assetType]);

  useEffect(() => {
    if (!selectedSymbol) {
      setChartData([]);
      return;
    }
    setChartLoading(true);
    api
      .getPriceHistory(assetType, selectedSymbol, chartDays)
      .then((resp) => {
        const points = resp.candles.map((c) => ({
          date: new Date(c.time * 1000).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
          }),
          price: c.close,
        }));
        setChartData(points);
      })
      .catch(() => setChartData([]))
      .finally(() => setChartLoading(false));
  }, [selectedSymbol, assetType, chartDays]);

  const currentAssets = assetType === "stock" ? assets.stocks : assets.crypto;

  const handleTrade = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSymbol || !quantity) return;
    setLoading(true);
    setMessage(null);

    try {
      const result = await api.placeTrade(
        selectedSymbol,
        assetType,
        side,
        parseFloat(quantity)
      );
      setMessage({
        type: "success",
        text: `${side === "buy" ? "Bought" : "Sold"} ${result.quantity} ${result.symbol} at ${formatPrice(result.price)} for ${formatCurrency(result.total)}`,
      });
      setQuantity("");
    } catch (err: unknown) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Trade failed",
      });
    } finally {
      setLoading(false);
    }
  };

  if (authLoading || !user) return null;

  const estimatedTotal = quote && quantity ? quote.price * parseFloat(quantity) : 0;

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-4xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-white mb-6">Trade</h1>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Asset Selection */}
          <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
            <div className="flex gap-2 mb-4">
              <button
                onClick={() => {
                  setAssetType("stock");
                  setSelectedSymbol("");
                }}
                className={`px-4 py-2 rounded text-sm font-medium transition ${
                  assetType === "stock"
                    ? "bg-blue-600 text-white"
                    : "bg-gray-800 text-gray-400 hover:text-white"
                }`}
              >
                Stocks
              </button>
              <button
                onClick={() => {
                  setAssetType("crypto");
                  setSelectedSymbol("");
                }}
                className={`px-4 py-2 rounded text-sm font-medium transition ${
                  assetType === "crypto"
                    ? "bg-blue-600 text-white"
                    : "bg-gray-800 text-gray-400 hover:text-white"
                }`}
              >
                Crypto
              </button>
            </div>

            <div className="space-y-1 max-h-96 overflow-y-auto">
              {currentAssets.map((asset) => (
                <button
                  key={asset.symbol}
                  onClick={() => setSelectedSymbol(asset.symbol)}
                  className={`w-full text-left px-3 py-2 rounded transition ${
                    selectedSymbol === asset.symbol
                      ? "bg-blue-600/20 text-blue-400 border border-blue-500/30"
                      : "text-gray-300 hover:bg-gray-800"
                  }`}
                >
                  <span className="font-medium">{asset.symbol}</span>
                  <span className="text-gray-500 ml-2 text-sm">
                    {asset.name}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Quote + Chart + Trade Form */}
          <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
            {quote ? (
              <>
                <div className="mb-4">
                  <h2 className="text-xl font-bold text-white">
                    {quote.name || quote.symbol}
                  </h2>
                  <p className="text-3xl font-bold text-white mt-1">
                    {formatPrice(quote.price)}
                  </p>
                  {quote.change_pct !== null && (
                    <p
                      className={`text-sm mt-1 ${
                        (quote.change_pct ?? 0) >= 0
                          ? "text-green-400"
                          : "text-red-400"
                      }`}
                    >
                      {(quote.change_pct ?? 0) > 0 ? "+" : ""}
                      {quote.change_pct}% today
                    </p>
                  )}
                </div>

                {/* Price Chart */}
                <div className="mb-6">
                  <div className="flex gap-2 mb-3">
                    {[
                      { label: "7D", value: 7 },
                      { label: "1M", value: 30 },
                      { label: "3M", value: 90 },
                      { label: "1Y", value: 365 },
                    ].map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => setChartDays(opt.value)}
                        className={`px-3 py-1 rounded text-xs font-medium transition ${
                          chartDays === opt.value
                            ? "bg-blue-600 text-white"
                            : "bg-gray-800 text-gray-400 hover:text-white"
                        }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                  {chartLoading ? (
                    <div className="h-40 flex items-center justify-center text-gray-500 text-sm">
                      Loading chart...
                    </div>
                  ) : chartData.length > 0 ? (
                    <ResponsiveContainer width="100%" height={160}>
                      <AreaChart data={chartData}>
                        <defs>
                          <linearGradient id="priceGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.3} />
                            <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <XAxis
                          dataKey="date"
                          tick={{ fill: "#6b7280", fontSize: 10 }}
                          axisLine={false}
                          tickLine={false}
                          interval="preserveStartEnd"
                        />
                        <YAxis
                          domain={["auto", "auto"]}
                          tick={{ fill: "#6b7280", fontSize: 10 }}
                          axisLine={false}
                          tickLine={false}
                          width={60}
                          tickFormatter={(v) =>
                            v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : `$${v.toFixed(2)}`
                          }
                        />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: "#1f2937",
                            border: "1px solid #374151",
                            borderRadius: "8px",
                            color: "#fff",
                            fontSize: "12px",
                          }}
                          formatter={(value) => [
                            formatPrice(Number(value)),
                            "Price",
                          ]}
                        />
                        <Area
                          type="monotone"
                          dataKey="price"
                          stroke="#3b82f6"
                          fill="url(#priceGrad)"
                          strokeWidth={2}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="h-40 flex items-center justify-center text-gray-500 text-sm">
                      No chart data available
                    </div>
                  )}
                </div>

                <form onSubmit={handleTrade} className="space-y-4">
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setSide("buy")}
                      className={`flex-1 py-2 rounded font-medium transition ${
                        side === "buy"
                          ? "bg-green-600 text-white"
                          : "bg-gray-800 text-gray-400 hover:text-white"
                      }`}
                    >
                      Buy
                    </button>
                    <button
                      type="button"
                      onClick={() => setSide("sell")}
                      className={`flex-1 py-2 rounded font-medium transition ${
                        side === "sell"
                          ? "bg-red-600 text-white"
                          : "bg-gray-800 text-gray-400 hover:text-white"
                      }`}
                    >
                      Sell
                    </button>
                  </div>

                  <div>
                    <label className="block text-sm text-gray-400 mb-1">
                      Quantity
                    </label>
                    <input
                      type="number"
                      value={quantity}
                      onChange={(e) => setQuantity(e.target.value)}
                      min="0"
                      step={assetType === "crypto" ? "0.0001" : "1"}
                      required
                      className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white focus:outline-none focus:border-blue-500"
                      placeholder={
                        assetType === "crypto" ? "0.5" : "10"
                      }
                    />
                  </div>

                  {estimatedTotal > 0 && (
                    <div className="bg-gray-800 rounded p-3">
                      <div className="flex justify-between text-sm">
                        <span className="text-gray-400">Estimated Total</span>
                        <span className="text-white font-medium">
                          {formatCurrency(estimatedTotal)}
                        </span>
                      </div>
                    </div>
                  )}

                  {message && (
                    <p
                      className={`text-sm ${
                        message.type === "success"
                          ? "text-green-400"
                          : "text-red-400"
                      }`}
                    >
                      {message.text}
                    </p>
                  )}

                  <button
                    type="submit"
                    disabled={loading || !quantity}
                    className={`w-full py-3 rounded font-medium transition disabled:cursor-not-allowed ${
                      side === "buy"
                        ? "bg-green-600 hover:bg-green-700 disabled:bg-green-800 text-white"
                        : "bg-red-600 hover:bg-red-700 disabled:bg-red-800 text-white"
                    }`}
                  >
                    {loading
                      ? "Processing..."
                      : `${side === "buy" ? "Buy" : "Sell"} ${selectedSymbol}`}
                  </button>
                </form>
              </>
            ) : (
              <div className="flex items-center justify-center h-full text-gray-500">
                Select an asset to trade
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
