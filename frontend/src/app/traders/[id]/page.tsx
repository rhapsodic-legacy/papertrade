"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { formatCurrency, formatPrice } from "@/lib/utils";
import Navbar from "@/components/Navbar";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
} from "recharts";

const STARTING_BALANCE = 100_000;

const PERSONALITY_COLORS: Record<string, string> = {
  vanilla: "text-gray-300",
  steady_eddie: "text-blue-400",
  yolo_bot: "text-red-400",
  contrarian_carl: "text-purple-400",
  crypto_chad: "text-orange-400",
};

const PERSONALITY_BG: Record<string, string> = {
  vanilla: "bg-gray-800",
  steady_eddie: "bg-blue-900/40",
  yolo_bot: "bg-red-900/40",
  contrarian_carl: "bg-purple-900/40",
  crypto_chad: "bg-orange-900/40",
};

interface TraderProfile {
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
}

export default function TraderProfilePage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const params = useParams();
  const traderId = params.id as string;
  const [profile, setProfile] = useState<TraderProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.push("/auth");
  }, [user, authLoading, router]);

  useEffect(() => {
    if (user && traderId) {
      setLoading(true);
      api
        .getAiTraderProfile(traderId)
        .then(setProfile)
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
    }
  }, [user, traderId]);

  if (authLoading || !user) return null;

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-950">
        <Navbar />
        <main className="max-w-5xl mx-auto px-4 py-8">
          <p className="text-gray-400">Loading trader profile...</p>
        </main>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="min-h-screen bg-gray-950">
        <Navbar />
        <main className="max-w-5xl mx-auto px-4 py-8">
          <p className="text-red-400">{error || "Trader not found"}</p>
          <Link href="/leaderboard" className="text-blue-400 hover:text-blue-300 text-sm mt-2 inline-block">
            Back to Leaderboard
          </Link>
        </main>
      </div>
    );
  }

  const totalReturn = profile.total_value - STARTING_BALANCE;
  const totalReturnPct = (totalReturn / STARTING_BALANCE) * 100;
  const pnlColor = totalReturn >= 0 ? "text-green-400" : "text-red-400";

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-5xl mx-auto px-4 py-8">
        {/* Back Link */}
        <Link
          href="/leaderboard"
          className="text-sm text-gray-400 hover:text-white transition mb-6 inline-block"
        >
          &larr; Back to Leaderboard
        </Link>

        {/* Header */}
        <div className={`rounded-lg border border-gray-800 p-6 mb-6 ${PERSONALITY_BG[profile.personality] || "bg-gray-900"}`}>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className={`text-2xl font-bold ${PERSONALITY_COLORS[profile.personality] || "text-white"}`}>
                {profile.display_name}
              </h1>
              {profile.personality_description && (
                <p className="text-gray-400 text-sm mt-2 max-w-xl">
                  {profile.personality_description}
                </p>
              )}
            </div>
            <div className="text-right">
              <p className="text-sm text-gray-400">Total Value</p>
              <p className="text-2xl font-bold text-white">
                {formatCurrency(profile.total_value)}
              </p>
              <p className={`text-sm font-medium ${pnlColor}`}>
                {totalReturn >= 0 ? "+" : ""}
                {formatCurrency(totalReturn)} ({totalReturnPct >= 0 ? "+" : ""}
                {totalReturnPct.toFixed(2)}%)
              </p>
            </div>
          </div>
        </div>

        {/* Stats Row */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
            <p className="text-xs text-gray-400 mb-1">Cash</p>
            <p className="text-lg font-bold text-white">
              {formatCurrency(profile.cash_balance)}
            </p>
          </div>
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
            <p className="text-xs text-gray-400 mb-1">Invested</p>
            <p className="text-lg font-bold text-white">
              {formatCurrency(profile.invested_value)}
            </p>
          </div>
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
            <p className="text-xs text-gray-400 mb-1">Total Trades</p>
            <p className="text-lg font-bold text-white">{profile.trades.length}</p>
          </div>
        </div>

        {/* Performance Chart */}
        {profile.snapshots.length > 1 && (
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-6 mb-6">
            <h2 className="text-lg font-semibold text-white mb-4">
              Performance
            </h2>
            <PerformanceChart snapshots={profile.snapshots} />
          </div>
        )}

        {/* Two Column: Positions + Recent Trades */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* Positions */}
          <div className="bg-gray-900 rounded-lg border border-gray-800">
            <div className="px-4 py-3 border-b border-gray-800">
              <h2 className="text-base font-semibold text-white">Holdings</h2>
            </div>
            {profile.positions.length === 0 ? (
              <p className="p-4 text-gray-400 text-sm">No positions</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-gray-400 border-b border-gray-800">
                      <th className="px-4 py-2">Symbol</th>
                      <th className="px-4 py-2 text-right">Qty</th>
                      <th className="px-4 py-2 text-right">Price</th>
                      <th className="px-4 py-2 text-right">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {profile.positions.map((p) => (
                      <tr key={p.symbol} className="border-b border-gray-800/50">
                        <td className="px-4 py-2 text-white font-medium">{p.symbol}</td>
                        <td className="px-4 py-2 text-right text-gray-300">
                          {p.quantity < 1 ? p.quantity.toFixed(4) : p.quantity}
                        </td>
                        <td className="px-4 py-2 text-right text-gray-300">
                          {formatPrice(p.current_price)}
                        </td>
                        <td className="px-4 py-2 text-right text-gray-300">
                          {formatCurrency(p.market_value)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Recent Trades */}
          <div className="bg-gray-900 rounded-lg border border-gray-800">
            <div className="px-4 py-3 border-b border-gray-800">
              <h2 className="text-base font-semibold text-white">Recent Trades</h2>
            </div>
            {profile.trades.length === 0 ? (
              <p className="p-4 text-gray-400 text-sm">No trades yet</p>
            ) : (
              <div className="overflow-x-auto max-h-80 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-gray-900">
                    <tr className="text-left text-gray-400 border-b border-gray-800">
                      <th className="px-4 py-2">Date</th>
                      <th className="px-4 py-2">Action</th>
                      <th className="px-4 py-2 text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {profile.trades.map((t, i) => (
                      <tr key={i} className="border-b border-gray-800/50">
                        <td className="px-4 py-2 text-gray-400 text-xs">
                          {new Date(t.created_at).toLocaleDateString("en-US", {
                            month: "short",
                            day: "numeric",
                          })}
                        </td>
                        <td className="px-4 py-2">
                          <span
                            className={
                              t.side === "buy" ? "text-green-400" : "text-red-400"
                            }
                          >
                            {t.side.toUpperCase()}
                          </span>{" "}
                          <span className="text-white">{t.quantity} {t.symbol}</span>
                        </td>
                        <td className="px-4 py-2 text-right text-gray-300">
                          {formatCurrency(t.total)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Commentary */}
        {profile.commentary.length > 0 && (
          <div className="bg-gray-900 rounded-lg border border-gray-800">
            <div className="px-6 py-4 border-b border-gray-800">
              <h2 className="text-lg font-semibold text-white">Commentary</h2>
            </div>
            <div className="divide-y divide-gray-800">
              {profile.commentary.map((c, i) => (
                <div key={i} className="px-6 py-4">
                  <p className="text-xs text-gray-500 mb-2">
                    {new Date(c.commentary_date + "T12:00:00").toLocaleDateString(
                      "en-US",
                      { weekday: "long", month: "long", day: "numeric" }
                    )}
                  </p>
                  <p className="text-gray-300 text-sm leading-relaxed whitespace-pre-line">
                    {c.commentary}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function PerformanceChart({
  snapshots,
}: {
  snapshots: { snapshot_date: string; total_value: number }[];
}) {
  const data = snapshots.map((s) => ({
    date: new Date(s.snapshot_date + "T12:00:00").toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
    value: s.total_value,
  }));

  const isUp = data[data.length - 1].value >= data[0].value;
  const color = isUp ? "#22c55e" : "#ef4444";

  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
        <defs>
          <linearGradient id="traderGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.3} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="date"
          tick={{ fill: "#9ca3af", fontSize: 12 }}
          tickLine={false}
          axisLine={{ stroke: "#374151" }}
        />
        <YAxis
          tick={{ fill: "#9ca3af", fontSize: 12 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
          domain={["auto", "auto"]}
          width={60}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#1f2937",
            border: "1px solid #374151",
            borderRadius: "8px",
            color: "#fff",
          }}
          formatter={(value) => [formatCurrency(Number(value)), "Portfolio"]}
          labelStyle={{ color: "#9ca3af" }}
        />
        <ReferenceLine
          y={STARTING_BALANCE}
          stroke="#6b7280"
          strokeDasharray="4 4"
          strokeWidth={1}
        />
        <Area
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={2}
          fill="url(#traderGradient)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
