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

const TOOLKIT_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  blue: { bg: "bg-blue-900/30", text: "text-blue-400", border: "border-blue-800" },
  purple: { bg: "bg-purple-900/30", text: "text-purple-400", border: "border-purple-800" },
  green: { bg: "bg-green-900/30", text: "text-green-400", border: "border-green-800" },
  amber: { bg: "bg-amber-900/30", text: "text-amber-400", border: "border-amber-800" },
  red: { bg: "bg-red-900/30", text: "text-red-400", border: "border-red-800" },
  teal: { bg: "bg-teal-900/30", text: "text-teal-400", border: "border-teal-800" },
  indigo: { bg: "bg-indigo-900/30", text: "text-indigo-400", border: "border-indigo-800" },
  gray: { bg: "bg-gray-900/30", text: "text-gray-400", border: "border-gray-800" },
};

const PERSONALITY_DESCRIPTIONS: Record<string, { summary: string; strategy: string; buySignals: string; sellSignals: string; riskProfile: string }> = {
  vanilla: {
    summary: "A balanced portfolio manager focused on risk-adjusted returns through diversification.",
    strategy: "Combines fundamental analysis (P/E ratios, analyst consensus) with technical indicators (RSI, SMA trends) for entry and exit timing. Monitors sector exposure to avoid concentration risk and adjusts equity allocation based on market regime.",
    buySignals: "Fairly valued stocks with solid fundamentals, confirmed by positive technical momentum.",
    sellSignals: "Sector overweight above 40%, bearish market regime shift, or position drift from targets.",
    riskProfile: "Maintains a 10 to 20% cash reserve for opportunistic buying. Rebalances when positions drift from target allocations.",
  },
  steady_eddie: {
    summary: "A conservative value investor modeled after Warren Buffett's philosophy, prioritizing capital preservation and steady compounding.",
    strategy: "Favors blue-chip stocks with below-average P/E ratios, strong analyst buy consensus, low beta (under 1.0), and dividend yields above 1%. Targets a portfolio of 60% blue chips, 20% defensive sectors (healthcare, consumer staples), 10% bonds (TLT), and 10% cash.",
    buySignals: "Low P/E relative to sector, strong buy consensus, low volatility, RSI under 60.",
    sellSignals: "RSI above 75 (overbought), position exceeds 15% of portfolio, or analyst consensus shifts to sell.",
    riskProfile: "Avoids high-beta stocks (above 1.5), limits crypto to under 5% of portfolio, and avoids assets with annualized volatility above 50%. Shifts to 40% stocks, 30% bonds, and 30% cash in bearish markets.",
  },
  yolo_bot: {
    summary: "An aggressive momentum trader inspired by high-frequency trend-following strategies. Rides winners hard and cuts losers fast.",
    strategy: "Concentrates in the top 3 to 5 highest-momentum names. Overweights the leading sector based on rotation signals. In bullish markets, goes 90% invested in the strongest momentum assets. In bearish markets, pivots to crypto (which trades 24/7) and reduces stock exposure.",
    buySignals: "7-day momentum above 3%, RSI between 50 and 75, price above SMA20, volume spike, bullish analyst consensus.",
    sellSignals: "RSI above 80 (take profits), 7-day momentum turns negative, price drops below SMA20, or position falls more than 8%.",
    riskProfile: "Keeps less than 5% cash. High concentration, high turnover. Accepts large drawdowns in exchange for outsized upside potential.",
  },
  contrarian_carl: {
    summary: "A contrarian value investor inspired by Michael Burry and mean-reversion strategies. Buys when others are fearful and sells when others are greedy.",
    strategy: "Looks for quality stocks that have been oversold in panic selling. Waits for prices to revert to historical norms before taking profits. In bearish markets with high safe-haven demand, aggressively buys quality names that got dragged down. In bullish markets with elevated RSI, takes profits and builds cash.",
    buySignals: "RSI below 30 (oversold), 7-day return worse than negative 5%, P/E below historical norms, mixed analyst consensus.",
    sellSignals: "RSI above 70 (overextended recovery), 30-day return above 15%, or position profit exceeds 20%.",
    riskProfile: "Holds 15 to 25% cash as dry powder for buying opportunities. Diversifies across 6 to 10 positions. Never chases momentum.",
  },
  crypto_chad: {
    summary: "A crypto-native trader inspired by on-chain analysts and narrative cycle trading, with a strong conviction in digital assets.",
    strategy: "Maintains 60 to 80% crypto allocation, 10 to 20% tech stocks (correlated growth plays), and 10 to 20% cash. Uses Bitcoin as a leading indicator for the entire crypto market. When BTC is bullish, altcoins typically rally harder. When BTC turns bearish, reduces all crypto exposure.",
    buySignals: "Coins with market cap rank under 20, distance from all-time high above 30%, positive 7-day momentum, and Bitcoin RSI above 40.",
    sellSignals: "Distance from all-time high under 5% (near top), RSI above 80, or Bitcoin breaks below its 50-day moving average.",
    riskProfile: "Layers positions into core holdings (BTC/ETH at 40%), mid-cap altcoins (30%), and small-cap momentum plays (30%). Watches interest rate signals as a macro overlay.",
  },
};

interface ToolkitModule {
  module: string;
  label: string;
  description: string;
  icon: string;
  color: string;
  active: boolean;
  weight: number;
  inverted: boolean;
}

interface TraderProfile {
  display_name: string;
  ai_model: string;
  personality: string;
  personality_description: string | null;
  toolkit?: ToolkitModule[];
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
          <Link href="/learn" className="text-blue-400 hover:text-blue-300 text-sm mt-2 inline-block">
            Back to Learn from AI
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
          href="/learn"
          className="text-sm text-gray-400 hover:text-white transition mb-6 inline-block"
        >
          &larr; Back to Learn from AI
        </Link>

        {/* Header */}
        <div className={`rounded-lg border border-gray-800 p-6 mb-6 ${PERSONALITY_BG[profile.personality] || "bg-gray-900"}`}>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className={`text-2xl font-bold ${PERSONALITY_COLORS[profile.personality] || "text-white"}`}>
                {profile.display_name}
              </h1>
              {profile.personality && PERSONALITY_DESCRIPTIONS[profile.personality] && (
                <p className="text-gray-400 text-sm mt-2 max-w-xl">
                  {PERSONALITY_DESCRIPTIONS[profile.personality].summary}
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

        {/* Strategy Overview */}
        {profile.personality && PERSONALITY_DESCRIPTIONS[profile.personality] && (
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-6 mb-6">
            <h2 className="text-lg font-semibold text-white mb-4">Trading Strategy</h2>
            <div className="space-y-4">
              <div>
                <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Approach</h3>
                <p className="text-sm text-gray-300 leading-relaxed">{PERSONALITY_DESCRIPTIONS[profile.personality].strategy}</p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <h3 className="text-xs font-medium text-green-500 uppercase tracking-wide mb-1">Buy Signals</h3>
                  <p className="text-sm text-gray-400 leading-relaxed">{PERSONALITY_DESCRIPTIONS[profile.personality].buySignals}</p>
                </div>
                <div>
                  <h3 className="text-xs font-medium text-red-500 uppercase tracking-wide mb-1">Sell Signals</h3>
                  <p className="text-sm text-gray-400 leading-relaxed">{PERSONALITY_DESCRIPTIONS[profile.personality].sellSignals}</p>
                </div>
              </div>
              <div>
                <h3 className="text-xs font-medium text-blue-500 uppercase tracking-wide mb-1">Risk Profile</h3>
                <p className="text-sm text-gray-400 leading-relaxed">{PERSONALITY_DESCRIPTIONS[profile.personality].riskProfile}</p>
              </div>
            </div>
          </div>
        )}

        {/* Data Toolkit */}
        {profile.toolkit && profile.toolkit.length > 0 && (
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-6 mb-6">
            <h2 className="text-lg font-semibold text-white mb-2">Data Toolkit</h2>
            <p className="text-xs text-gray-500 mb-4">
              Each AI trader uses a curated set of data modules, weighted by priority. Higher weight means the data appears first in the prompt and gets more attention.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {profile.toolkit.map((mod) => {
                const colors = TOOLKIT_COLORS[mod.color] || TOOLKIT_COLORS.gray;
                return (
                  <div
                    key={mod.module}
                    className={`rounded-lg border p-3 transition-opacity ${
                      mod.active
                        ? `${colors.bg} ${colors.border}`
                        : "bg-gray-900/20 border-gray-800/50 opacity-40"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className={`text-sm font-medium ${mod.active ? colors.text : "text-gray-600"}`}>
                        {mod.label}
                        {mod.inverted && (
                          <span className="ml-1.5 text-xs bg-purple-900/50 text-purple-300 px-1.5 py-0.5 rounded">
                            Inverted
                          </span>
                        )}
                      </span>
                      {mod.active ? (
                        <span className="text-xs text-gray-500">
                          Weight {mod.weight}/10
                        </span>
                      ) : (
                        <span className="text-xs text-gray-600">Off</span>
                      )}
                    </div>
                    {mod.active && (
                      <div className="w-full bg-gray-800 rounded-full h-1 mb-2">
                        <div
                          className={`h-1 rounded-full ${colors.text.replace("text-", "bg-")}`}
                          style={{ width: `${mod.weight * 10}%` }}
                        />
                      </div>
                    )}
                    <p className={`text-xs leading-relaxed ${mod.active ? "text-gray-400" : "text-gray-600"}`}>
                      {mod.description}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        )}

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
              <div className="overflow-x-auto max-h-96 overflow-y-auto">
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
                          <div>
                            <span
                              className={
                                t.side === "buy" ? "text-green-400" : "text-red-400"
                              }
                            >
                              {t.side.toUpperCase()}
                            </span>{" "}
                            <span className="text-white">{t.quantity} {t.symbol}</span>
                          </div>
                          {t.reasoning && (
                            <p className="text-xs text-gray-500 mt-0.5 leading-snug">{t.reasoning}</p>
                          )}
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
