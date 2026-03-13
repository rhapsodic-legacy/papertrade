"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { formatPrice, pnlColor } from "@/lib/utils";
import Navbar from "@/components/Navbar";

interface WatchlistItem {
  id: string;
  symbol: string;
  asset_type: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  name: string;
}

interface AssetOption {
  symbol: string;
  name: string;
}

export default function WatchlistPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [assets, setAssets] = useState<{
    stocks: AssetOption[];
    crypto: AssetOption[];
  } | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [selectedType, setSelectedType] = useState<"stock" | "crypto">("stock");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!authLoading && !user) router.push("/auth");
  }, [user, authLoading, router]);

  useEffect(() => {
    if (user) {
      Promise.all([api.getWatchlist(), api.getAssets()])
        .then(([watchlist, assetList]) => {
          setItems(watchlist);
          setAssets(assetList);
          if (assetList.stocks.length > 0) {
            setSelectedSymbol(assetList.stocks[0].symbol);
          }
        })
        .catch(console.error)
        .finally(() => setLoading(false));
    }
  }, [user]);

  const handleAdd = async () => {
    if (!selectedSymbol) return;
    setAdding(true);
    setError("");
    try {
      await api.addToWatchlist(selectedSymbol, selectedType);
      const updated = await api.getWatchlist();
      setItems(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add");
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (symbol: string) => {
    try {
      await api.removeFromWatchlist(symbol);
      setItems(items.filter((i) => i.symbol !== symbol));
    } catch (err) {
      console.error(err);
    }
  };

  const availableOptions =
    selectedType === "stock" ? assets?.stocks || [] : assets?.crypto || [];

  // Update selected symbol when type changes
  const handleTypeChange = (type: "stock" | "crypto") => {
    setSelectedType(type);
    const options = type === "stock" ? assets?.stocks || [] : assets?.crypto || [];
    if (options.length > 0) {
      setSelectedSymbol(options[0].symbol);
    }
  };

  if (authLoading || !user) return null;

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-4xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-white mb-6">Watchlist</h1>

        {/* Add to watchlist */}
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-6 mb-6">
          <h2 className="text-lg font-semibold text-white mb-4">
            Add to Watchlist
          </h2>
          <div className="flex flex-wrap gap-3 items-end">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Type</label>
              <select
                value={selectedType}
                onChange={(e) =>
                  handleTypeChange(e.target.value as "stock" | "crypto")
                }
                className="bg-gray-800 text-white rounded-lg px-3 py-2 border border-gray-700 focus:border-blue-500 focus:outline-none"
              >
                <option value="stock">Stock</option>
                <option value="crypto">Crypto</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Asset</label>
              <select
                value={selectedSymbol}
                onChange={(e) => setSelectedSymbol(e.target.value)}
                className="bg-gray-800 text-white rounded-lg px-3 py-2 border border-gray-700 focus:border-blue-500 focus:outline-none"
              >
                {availableOptions.map((a) => (
                  <option key={a.symbol} value={a.symbol}>
                    {a.symbol} - {a.name}
                  </option>
                ))}
              </select>
            </div>
            <button
              onClick={handleAdd}
              disabled={adding || !selectedSymbol}
              className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg transition"
            >
              {adding ? "Adding..." : "Add"}
            </button>
          </div>
          {error && <p className="text-red-400 text-sm mt-2">{error}</p>}
        </div>

        {/* Watchlist table */}
        <div className="bg-gray-900 rounded-lg border border-gray-800">
          <div className="px-6 py-4 border-b border-gray-800">
            <h2 className="text-lg font-semibold text-white">Your Watchlist</h2>
          </div>
          {loading ? (
            <p className="p-6 text-gray-400">Loading...</p>
          ) : items.length === 0 ? (
            <p className="p-6 text-center text-gray-400">
              Your watchlist is empty. Add assets above to track them.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-sm text-gray-400 border-b border-gray-800">
                    <th className="px-6 py-3">Symbol</th>
                    <th className="px-6 py-3">Name</th>
                    <th className="px-6 py-3">Type</th>
                    <th className="px-6 py-3 text-right">Price</th>
                    <th className="px-6 py-3 text-right">Change</th>
                    <th className="px-6 py-3 text-right"></th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr
                      key={item.id}
                      className="border-b border-gray-800/50 hover:bg-gray-800/30"
                    >
                      <td className="px-6 py-4 font-medium text-white">
                        {item.symbol}
                      </td>
                      <td className="px-6 py-4 text-gray-300">{item.name}</td>
                      <td className="px-6 py-4 text-gray-400 capitalize">
                        {item.asset_type}
                      </td>
                      <td className="px-6 py-4 text-right text-gray-300">
                        {item.price !== null ? formatPrice(item.price) : "-"}
                      </td>
                      <td
                        className={`px-6 py-4 text-right font-medium ${pnlColor(
                          item.change_pct ?? 0
                        )}`}
                      >
                        {item.change_pct !== null
                          ? `${item.change_pct > 0 ? "+" : ""}${item.change_pct.toFixed(2)}%`
                          : "-"}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <button
                          onClick={() => handleRemove(item.symbol)}
                          className="text-red-400 hover:text-red-300 text-sm transition"
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
