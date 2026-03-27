"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { formatCurrency, formatPrice, pnlColor } from "@/lib/utils";
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

interface MarketRegime {
  date: string | null;
  regime?: {
    market_trend?: string;
    spy_rsi?: number;
    spy_7d?: number;
    spy_30d?: number;
    growth_vs_value?: string;
    rate_signal?: string;
    safe_haven_demand?: string;
    small_cap_signal?: string;
  };
  sectors?: {
    sector: string;
    avg_change_pct: number;
    stocks_up: number;
    stocks_down: number;
  }[];
  crypto_global?: {
    btc_dominance?: number;
    market_cap_change_24h?: number;
  };
  fear_greed?: {
    score?: number;
    classification?: string;
  };
}

interface Snapshot {
  snapshot_date: string;
  total_value: number;
  cash_balance: number;
  invested_value: number;
}

interface Position {
  symbol: string;
  asset_type: string;
  quantity: number;
  avg_cost_basis: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
}

interface Portfolio {
  cash_balance: number;
  invested_value: number;
  total_value: number;
  positions: Position[];
}

const STARTING_BALANCE = 100_000;

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [regime, setRegime] = useState<MarketRegime | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/auth");
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    if (user) {
      Promise.all([
        api.getPortfolio(),
        api.getSnapshots(30),
        api.getMarketRegime().catch(() => null),
      ])
        .then(([p, s, r]) => {
          setPortfolio(p);
          setSnapshots(s);
          setRegime(r);
        })
        .catch(console.error)
        .finally(() => setLoading(false));
    }
  }, [user]);

  if (authLoading || !user) return null;

  const totalReturn = portfolio
    ? portfolio.total_value - STARTING_BALANCE
    : 0;
  const totalReturnPct = portfolio
    ? ((portfolio.total_value - STARTING_BALANCE) / STARTING_BALANCE) * 100
    : 0;

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-white mb-6">Portfolio</h1>

        {loading ? (
          <p className="text-gray-400">Loading portfolio...</p>
        ) : portfolio ? (
          <>
            {/* Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
              <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
                <p className="text-sm text-gray-400 mb-1">Total Value</p>
                <p className="text-2xl font-bold text-white">
                  {formatCurrency(portfolio.total_value)}
                </p>
              </div>
              <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
                <p className="text-sm text-gray-400 mb-1">Total Return</p>
                <p className={`text-2xl font-bold ${pnlColor(totalReturn)}`}>
                  {totalReturn >= 0 ? "+" : ""}
                  {formatCurrency(totalReturn)}
                </p>
                <p className={`text-sm ${pnlColor(totalReturnPct)}`}>
                  {totalReturnPct >= 0 ? "+" : ""}
                  {totalReturnPct.toFixed(2)}%
                </p>
              </div>
              <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
                <p className="text-sm text-gray-400 mb-1">Cash Balance</p>
                <p className="text-2xl font-bold text-white">
                  {formatCurrency(portfolio.cash_balance)}
                </p>
              </div>
              <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
                <p className="text-sm text-gray-400 mb-1">Invested</p>
                <p className="text-2xl font-bold text-white">
                  {formatCurrency(portfolio.invested_value)}
                </p>
              </div>
            </div>

            {/* Market Conditions */}
            {regime?.regime && (
              <div className="bg-gray-900 rounded-lg border border-gray-800 p-6 mb-8">
                <h2 className="text-lg font-semibold text-white mb-4">
                  Market Conditions
                  {regime.date && (
                    <span className="text-sm font-normal text-gray-500 ml-2">
                      {regime.date}
                    </span>
                  )}
                </h2>
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                  {regime.regime.market_trend && (
                    <RegimeCard
                      label="Market Trend"
                      value={regime.regime.market_trend}
                      detail={regime.regime.spy_7d != null ? `SPY 7d: ${regime.regime.spy_7d > 0 ? "+" : ""}${regime.regime.spy_7d.toFixed(1)}%` : undefined}
                      color={regime.regime.market_trend === "BULLISH" ? "green" : regime.regime.market_trend === "BEARISH" ? "red" : "yellow"}
                    />
                  )}
                  {regime.regime.growth_vs_value && (
                    <RegimeCard
                      label="Rotation"
                      value={regime.regime.growth_vs_value.replace(/_/g, " ")}
                      color="blue"
                    />
                  )}
                  {regime.regime.rate_signal && (
                    <RegimeCard
                      label="Rates"
                      value={regime.regime.rate_signal.replace(/_/g, " ")}
                      color={regime.regime.rate_signal === "RATES_FALLING" ? "green" : "red"}
                    />
                  )}
                  {regime.regime.safe_haven_demand && (
                    <RegimeCard
                      label="Safe Haven"
                      value={regime.regime.safe_haven_demand}
                      color={regime.regime.safe_haven_demand === "HIGH" ? "red" : "green"}
                    />
                  )}
                  {regime.fear_greed && (
                    <RegimeCard
                      label="Fear & Greed"
                      value={`${regime.fear_greed.score ?? "—"}/100`}
                      detail={regime.fear_greed.classification}
                      color={(regime.fear_greed.score ?? 50) < 30 ? "red" : (regime.fear_greed.score ?? 50) > 70 ? "green" : "yellow"}
                    />
                  )}
                  {regime.crypto_global?.btc_dominance != null && (
                    <RegimeCard
                      label="BTC Dominance"
                      value={`${regime.crypto_global.btc_dominance}%`}
                      color="blue"
                    />
                  )}
                </div>

                {/* Sector Performance Bar */}
                {regime.sectors && regime.sectors.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-gray-800">
                    <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">
                      Sector Performance
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {regime.sectors.map((s) => (
                        <span
                          key={s.sector}
                          className={`text-xs px-2 py-1 rounded ${
                            s.avg_change_pct > 0.5
                              ? "bg-green-900/30 text-green-400"
                              : s.avg_change_pct < -0.5
                                ? "bg-red-900/30 text-red-400"
                                : "bg-gray-800 text-gray-400"
                          }`}
                        >
                          {s.sector} {s.avg_change_pct > 0 ? "+" : ""}
                          {s.avg_change_pct.toFixed(1)}%
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Portfolio Chart */}
            {snapshots.length > 1 && (
              <div className="bg-gray-900 rounded-lg border border-gray-800 p-6 mb-8">
                <h2 className="text-lg font-semibold text-white mb-4">
                  Portfolio Value — 30 Days
                </h2>
                <PortfolioChart snapshots={snapshots} />
              </div>
            )}

            {/* Positions */}
            <div className="bg-gray-900 rounded-lg border border-gray-800">
              <div className="px-6 py-4 border-b border-gray-800">
                <h2 className="text-lg font-semibold text-white">
                  Positions
                </h2>
              </div>
              {portfolio.positions.length === 0 ? (
                <div className="p-6 text-center text-gray-400">
                  No positions yet.{" "}
                  <button
                    onClick={() => router.push("/trade")}
                    className="text-blue-400 hover:text-blue-300"
                  >
                    Make your first trade
                  </button>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="text-left text-sm text-gray-400 border-b border-gray-800">
                        <th className="px-6 py-3">Symbol</th>
                        <th className="px-6 py-3">Type</th>
                        <th className="px-6 py-3 text-right">Qty</th>
                        <th className="px-6 py-3 text-right">Avg Cost</th>
                        <th className="px-6 py-3 text-right">Price</th>
                        <th className="px-6 py-3 text-right">Value</th>
                        <th className="px-6 py-3 text-right">P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {portfolio.positions.map((pos) => (
                        <tr
                          key={pos.symbol}
                          className="border-b border-gray-800/50 hover:bg-gray-800/30"
                        >
                          <td className="px-6 py-4 font-medium text-white">
                            {pos.symbol}
                          </td>
                          <td className="px-6 py-4 text-gray-400 capitalize">
                            {pos.asset_type}
                          </td>
                          <td className="px-6 py-4 text-right text-gray-300">
                            {pos.quantity}
                          </td>
                          <td className="px-6 py-4 text-right text-gray-300">
                            {formatPrice(pos.avg_cost_basis)}
                          </td>
                          <td className="px-6 py-4 text-right text-gray-300">
                            {formatPrice(pos.current_price)}
                          </td>
                          <td className="px-6 py-4 text-right text-gray-300">
                            {formatCurrency(pos.market_value)}
                          </td>
                          <td
                            className={`px-6 py-4 text-right font-medium ${pnlColor(
                              pos.unrealized_pnl
                            )}`}
                          >
                            {formatCurrency(pos.unrealized_pnl)} (
                            {pos.unrealized_pnl_pct > 0 ? "+" : ""}
                            {pos.unrealized_pnl_pct}%)
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        ) : (
          <p className="text-red-400">Failed to load portfolio</p>
        )}
      </main>
    </div>
  );
}

function RegimeCard({
  label,
  value,
  detail,
  color,
}: {
  label: string;
  value: string;
  detail?: string;
  color: "green" | "red" | "yellow" | "blue";
}) {
  const colors = {
    green: "border-green-800/50 text-green-400",
    red: "border-red-800/50 text-red-400",
    yellow: "border-yellow-800/50 text-yellow-400",
    blue: "border-blue-800/50 text-blue-400",
  };
  return (
    <div className={`bg-gray-800/50 rounded-lg border px-3 py-2 ${colors[color]}`}>
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-sm font-semibold">{value}</p>
      {detail && <p className="text-xs text-gray-400">{detail}</p>}
    </div>
  );
}

function PortfolioChart({ snapshots }: { snapshots: Snapshot[] }) {
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
    <ResponsiveContainer width="100%" height={280}>
      <AreaChart data={data} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
        <defs>
          <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
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
          fill="url(#chartGradient)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
