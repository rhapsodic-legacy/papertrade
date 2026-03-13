"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { formatCurrency, formatPrice, formatDate, pnlColor } from "@/lib/utils";
import Navbar from "@/components/Navbar";

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
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
              <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
                <p className="text-sm text-gray-400 mb-1">Total Value</p>
                <p className="text-2xl font-bold text-white">
                  {formatCurrency(portfolio.total_value)}
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

            {/* Portfolio History Chart */}
            {snapshots.length > 1 && (
              <div className="bg-gray-900 rounded-lg border border-gray-800 p-6 mb-8">
                <h2 className="text-lg font-semibold text-white mb-4">
                  Portfolio Value History
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
  const width = 700;
  const height = 200;
  const padding = { top: 20, right: 20, bottom: 30, left: 80 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  const values = snapshots.map((s) => s.total_value);
  const minVal = Math.min(...values) * 0.999;
  const maxVal = Math.max(...values) * 1.001;
  const range = maxVal - minVal || 1;

  const points = snapshots.map((s, i) => {
    const x = padding.left + (i / (snapshots.length - 1)) * chartW;
    const y = padding.top + chartH - ((s.total_value - minVal) / range) * chartH;
    return { x, y, ...s };
  });

  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");

  const isUp = values[values.length - 1] >= values[0];
  const lineColor = isUp ? "#22c55e" : "#ef4444";

  // Y-axis labels
  const yLabels = [minVal, minVal + range / 2, maxVal];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto">
      {/* Grid lines */}
      {yLabels.map((val) => {
        const y = padding.top + chartH - ((val - minVal) / range) * chartH;
        return (
          <g key={val}>
            <line
              x1={padding.left}
              y1={y}
              x2={width - padding.right}
              y2={y}
              stroke="#374151"
              strokeDasharray="4 4"
            />
            <text x={padding.left - 8} y={y + 4} textAnchor="end" fill="#9ca3af" fontSize="11">
              {formatCurrency(val)}
            </text>
          </g>
        );
      })}

      {/* Line */}
      <path d={linePath} fill="none" stroke={lineColor} strokeWidth="2" />

      {/* Dots on first and last */}
      {[points[0], points[points.length - 1]].map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r="3" fill={lineColor} />
      ))}

      {/* X-axis date labels (first and last) */}
      {[points[0], points[points.length - 1]].map((p, i) => (
        <text
          key={i}
          x={p.x}
          y={height - 5}
          textAnchor={i === 0 ? "start" : "end"}
          fill="#9ca3af"
          fontSize="11"
        >
          {new Date(p.snapshot_date + "T00:00:00").toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
          })}
        </text>
      ))}

      {/* $100k baseline */}
      {minVal <= 100000 && maxVal >= 100000 && (
        <>
          <line
            x1={padding.left}
            y1={padding.top + chartH - ((100000 - minVal) / range) * chartH}
            x2={width - padding.right}
            y2={padding.top + chartH - ((100000 - minVal) / range) * chartH}
            stroke="#6b7280"
            strokeDasharray="2 4"
            strokeWidth="1"
          />
        </>
      )}
    </svg>
  );
}
