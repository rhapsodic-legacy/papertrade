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
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/auth");
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    if (user) {
      Promise.all([api.getPortfolio(), api.getSnapshots(30)])
        .then(([p, s]) => {
          setPortfolio(p);
          setSnapshots(s);
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
