"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import Navbar from "@/components/Navbar";
import { formatCurrency } from "@/lib/utils";

type CustomTrader = {
  id: string;
  profile_id: string;
  name: string;
  strategy_prompt: string;
  risk_level: string;
  asset_focus: string;
  toolkit_modules: string[];
  is_active: boolean;
  display_name: string;
  total_value: number;
  created_at: string;
};

const RISK_COLORS: Record<string, string> = {
  low: "bg-green-900/40 text-green-400",
  medium: "bg-yellow-900/40 text-yellow-400",
  high: "bg-red-900/40 text-red-400",
};

const RISK_LABELS: Record<string, string> = {
  low: "Conservative",
  medium: "Balanced",
  high: "Aggressive",
};

const ASSET_LABELS: Record<string, string> = {
  both: "Stocks & Crypto",
  stocks: "Stocks Only",
  crypto: "Crypto Only",
};

export default function MyTradersPage() {
  const { user } = useAuth();
  const router = useRouter();

  const [traders, setTraders] = useState<CustomTrader[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);

  const fetchTraders = () => {
    setLoading(true);
    api
      .getMyCustomTraders()
      .then((res) => setTraders(res.traders))
      .catch(() => setError("Failed to load traders"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!user) {
      router.push("/auth/signin");
      return;
    }
    fetchTraders();
  }, [user, router]);

  const handleDelete = async (traderId: string, traderName: string) => {
    if (!confirm(`Deactivate "${traderName}"? Trade history will be preserved, but it will stop trading.`)) return;
    setDeleting(traderId);
    try {
      await api.deleteCustomTrader(traderId);
      setTraders((prev) => prev.filter((t) => t.id !== traderId));
    } catch {
      setError("Failed to deactivate trader");
    } finally {
      setDeleting(null);
    }
  };

  if (!user) return null;

  const returnPct = (tv: number) => ((tv - 100000) / 100000) * 100;

  return (
    <div className="min-h-screen bg-black text-white">
      <Navbar />
      <div className="max-w-4xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold">My AI Traders</h1>
            <p className="text-gray-400 mt-1">
              Manage your custom AI traders competing on the leaderboard.
            </p>
          </div>
          {traders.length < 3 && (
            <Link
              href="/create-trader"
              className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition"
            >
              + Create Trader
            </Link>
          )}
        </div>

        {error && (
          <div className="bg-red-900/30 border border-red-800 text-red-400 px-4 py-3 rounded-lg text-sm mb-6">
            {error}
          </div>
        )}

        {loading ? (
          <div className="text-gray-500 text-center py-16">Loading...</div>
        ) : traders.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-gray-500 text-lg mb-2">No custom traders yet</div>
            <p className="text-gray-600 text-sm mb-6">
              Create an AI trader with your own strategy. It gets $100k in
              virtual cash and competes against 20 built-in AI traders on the
              leaderboard.
            </p>
            <Link
              href="/create-trader"
              className="bg-blue-600 hover:bg-blue-500 text-white px-6 py-3 rounded-lg font-medium transition inline-block"
            >
              Create Your First AI Trader
            </Link>
          </div>
        ) : (
          <div className="space-y-4">
            {traders.map((t) => {
              const ret = returnPct(t.total_value);
              return (
                <div
                  key={t.id}
                  className="bg-gray-900 border border-gray-800 rounded-lg p-5"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <div className="flex items-center gap-3">
                        <h3 className="text-lg font-semibold">{t.display_name}</h3>
                        <span
                          className={`text-xs px-2 py-0.5 rounded ${RISK_COLORS[t.risk_level]}`}
                        >
                          {RISK_LABELS[t.risk_level]}
                        </span>
                        <span className="text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-400">
                          {ASSET_LABELS[t.asset_focus]}
                        </span>
                      </div>
                      <p className="text-sm text-gray-400 mt-1">
                        Created{" "}
                        {new Date(t.created_at).toLocaleDateString("en-US", {
                          month: "short",
                          day: "numeric",
                          year: "numeric",
                        })}
                      </p>
                    </div>
                    <div className="text-right">
                      <div className="text-lg font-semibold">
                        {formatCurrency(t.total_value)}
                      </div>
                      <div
                        className={`text-sm ${ret >= 0 ? "text-green-400" : "text-red-400"}`}
                      >
                        {ret >= 0 ? "+" : ""}
                        {ret.toFixed(2)}%
                      </div>
                    </div>
                  </div>

                  <div className="bg-gray-800/50 rounded-lg p-3 mb-3">
                    <p className="text-sm text-gray-300 line-clamp-2">
                      {t.strategy_prompt}
                    </p>
                  </div>

                  <div className="flex items-center justify-between">
                    <div className="flex flex-wrap gap-1.5">
                      {t.toolkit_modules.map((m) => (
                        <span
                          key={m}
                          className="text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-500"
                        >
                          {m}
                        </span>
                      ))}
                    </div>
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/traders/${t.profile_id}`}
                        className="text-xs text-blue-400 hover:text-blue-300 transition px-3 py-1.5"
                      >
                        View Profile
                      </Link>
                      <button
                        onClick={() => handleDelete(t.id, t.name)}
                        disabled={deleting === t.id}
                        className="text-xs text-red-400 hover:text-red-300 disabled:text-gray-600 transition px-3 py-1.5"
                      >
                        {deleting === t.id ? "..." : "Deactivate"}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}

            {traders.length < 3 && (
              <p className="text-xs text-gray-600 text-center pt-2">
                {3 - traders.length} trader slot{3 - traders.length !== 1 ? "s" : ""} remaining
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
