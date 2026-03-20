"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import Navbar from "@/components/Navbar";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  ReferenceLine,
} from "recharts";

const SECTOR_COLORS: Record<string, string> = {
  Technology: "#60a5fa",
  Healthcare: "#34d399",
  Finance: "#fbbf24",
  Energy: "#f87171",
  "Consumer Cyclical": "#a78bfa",
  Industrials: "#fb923c",
  "Communication Services": "#e879f9",
  "Consumer Defensive": "#2dd4bf",
  Crypto: "#f59e0b",
  Other: "#6b7280",
};

const GRADE_COLORS: Record<string, string> = {
  "A+": "#22c55e",
  A: "#34d399",
  "B+": "#60a5fa",
  B: "#3b82f6",
  "C+": "#fbbf24",
  C: "#f59e0b",
  D: "#f87171",
  F: "#ef4444",
};

type HealthData = Awaited<ReturnType<typeof api.getPortfolioHealth>>;

function GradeRing({ score, grade }: { score: number; grade: string }) {
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const color = GRADE_COLORS[grade] || "#6b7280";

  return (
    <div className="relative w-36 h-36 mx-auto">
      <svg className="w-full h-full -rotate-90" viewBox="0 0 120 120">
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          stroke="#1f2937"
          strokeWidth="8"
        />
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-1000"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-bold" style={{ color }}>
          {grade}
        </span>
        <span className="text-sm text-gray-400">{score}/100</span>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  aiValue,
  unit,
  tip,
  higher_is_better = true,
}: {
  label: string;
  value: number;
  aiValue: number;
  unit?: string;
  tip: string;
  higher_is_better?: boolean;
}) {
  const beating = higher_is_better ? value > aiValue : value < aiValue;
  const diff = value - aiValue;

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
      <div className="text-sm text-gray-400 mb-1">{label}</div>
      <div className="text-2xl font-bold text-white">
        {unit === "$" ? formatCurrency(value) : `${value.toFixed(2)}${unit || ""}`}
      </div>
      <div className="mt-2 flex items-center gap-2">
        <span
          className={`text-xs font-medium px-2 py-0.5 rounded ${
            beating
              ? "bg-green-900/50 text-green-400"
              : "bg-red-900/50 text-red-400"
          }`}
        >
          {beating ? "Beating" : "Below"} AI avg
        </span>
        <span className="text-xs text-gray-500">
          AI: {unit === "$" ? formatCurrency(aiValue) : `${aiValue.toFixed(2)}${unit || ""}`}
          {" "}({diff > 0 ? "+" : ""}{diff.toFixed(2)})
        </span>
      </div>
      <div className="mt-2 text-xs text-gray-500">{tip}</div>
    </div>
  );
}

function BreakdownBar({ item }: { item: HealthData["score_breakdown"][0] }) {
  const pct = (item.score / item.max) * 100;
  const color =
    pct >= 75 ? "bg-green-500" : pct >= 50 ? "bg-blue-500" : pct >= 25 ? "bg-yellow-500" : "bg-red-500";

  return (
    <div className="mb-3">
      <div className="flex justify-between text-sm mb-1">
        <span className="text-gray-300">{item.name}</span>
        <span className="text-gray-400">
          {item.score}/{item.max}
        </span>
      </div>
      <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
        <div
          className={`h-full ${color} rounded-full transition-all duration-700`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-xs text-gray-500 mt-0.5">{item.tip}</div>
    </div>
  );
}

export default function MyAnalyticsPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.push("/auth");
  }, [user, authLoading, router]);

  useEffect(() => {
    if (user) {
      api
        .getPortfolioHealth()
        .then(setData)
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
    }
  }, [user]);

  if (authLoading || !user) return null;

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-6xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-white mb-6">My Analytics</h1>

        {loading ? (
          <p className="text-gray-400">Loading your portfolio analytics...</p>
        ) : error ? (
          <p className="text-red-400">Error: {error}</p>
        ) : data ? (
          <div className="space-y-8">
            {/* Top Section: Grade + Breakdown + AI Rank */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {/* Health Score Ring */}
              <div className="bg-gray-900 rounded-lg border border-gray-800 p-6 flex flex-col items-center justify-center">
                <h2 className="text-sm text-gray-400 mb-4">Portfolio Health</h2>
                <GradeRing score={data.score} grade={data.grade} />
              </div>

              {/* Score Breakdown */}
              <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
                <h2 className="text-sm text-gray-400 mb-4">Score Breakdown</h2>
                {data.score_breakdown.map((item) => (
                  <BreakdownBar key={item.name} item={item} />
                ))}
              </div>

              {/* AI Rank */}
              <div className="bg-gray-900 rounded-lg border border-gray-800 p-6 flex flex-col items-center justify-center">
                <h2 className="text-sm text-gray-400 mb-4">vs AI Traders</h2>
                <div className="text-5xl font-bold text-white mb-1">
                  #{data.ai_comparison.user_rank}
                </div>
                <div className="text-sm text-gray-400">
                  out of {data.ai_comparison.total_ai_traders + 1}
                </div>
                <div className="mt-4 text-center">
                  <span className="text-2xl font-bold text-green-400">
                    {data.ai_comparison.user_beats_n}
                  </span>
                  <span className="text-sm text-gray-400 ml-1">
                    AI traders beaten
                  </span>
                </div>
                <div className="mt-2 text-xs text-gray-500">
                  Based on total return %
                </div>
              </div>
            </div>

            {/* Stat Cards — Your Metrics vs AI Average */}
            <div>
              <h2 className="text-lg font-semibold text-white mb-4">
                Your Metrics vs AI Average
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <StatCard
                  label="Total Return"
                  value={data.metrics.total_return_pct}
                  aiValue={data.ai_comparison.avg_return_pct}
                  unit="%"
                  tip="Cumulative return since you started trading"
                />
                <StatCard
                  label="Sharpe Ratio"
                  value={data.metrics.sharpe_ratio}
                  aiValue={data.ai_comparison.avg_sharpe}
                  tip="Return per unit of risk. Above 1.0 is good, above 2.0 is excellent"
                />
                <StatCard
                  label="Win Rate"
                  value={data.metrics.win_rate}
                  aiValue={data.ai_comparison.avg_win_rate}
                  unit="%"
                  tip="Percentage of closed trades that were profitable"
                />
                <StatCard
                  label="Max Drawdown"
                  value={data.metrics.max_drawdown_pct}
                  aiValue={data.ai_comparison.avg_max_drawdown}
                  unit="%"
                  tip="Largest peak-to-trough decline. Lower is better"
                  higher_is_better={false}
                />
                <StatCard
                  label="Profit Factor"
                  value={data.metrics.profit_factor}
                  aiValue={data.ai_comparison.avg_profit_factor}
                  tip="Gross profit / gross loss. Above 1.0 means net profitable"
                />
                <StatCard
                  label="Realized P&L"
                  value={data.metrics.total_realized_pnl}
                  aiValue={0}
                  unit="$"
                  tip="Actual profit/loss from closed trades"
                />
                <StatCard
                  label="Volatility"
                  value={data.metrics.annualized_volatility}
                  aiValue={0}
                  unit="%"
                  tip="Annualized portfolio volatility. Lower means smoother returns"
                  higher_is_better={false}
                />
                <StatCard
                  label="Total Trades"
                  value={data.metrics.total_trades}
                  aiValue={0}
                  tip={`${data.metrics.buy_count} buys, ${data.metrics.sell_count} sells`}
                />
              </div>
            </div>

            {/* Charts Row */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Portfolio Value Chart */}
              {data.metrics.daily_returns.length > 1 && (
                <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
                  <h2 className="text-sm text-gray-400 mb-4">
                    Portfolio Value Over Time
                  </h2>
                  <ResponsiveContainer width="100%" height={250}>
                    <LineChart data={data.metrics.daily_returns}>
                      <XAxis
                        dataKey="date"
                        tick={{ fill: "#6b7280", fontSize: 11 }}
                        tickFormatter={(d) =>
                          new Date(d + "T12:00:00").toLocaleDateString("en-US", {
                            month: "short",
                            day: "numeric",
                          })
                        }
                      />
                      <YAxis
                        tick={{ fill: "#6b7280", fontSize: 11 }}
                        tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#1f2937",
                          border: "1px solid #374151",
                          borderRadius: "8px",
                        }}
                        labelFormatter={(d) =>
                          new Date(String(d) + "T12:00:00").toLocaleDateString()
                        }
                        formatter={(value) => [
                          formatCurrency(Number(value)),
                          "Value",
                        ]}
                      />
                      <ReferenceLine
                        y={100000}
                        stroke="#6b7280"
                        strokeDasharray="3 3"
                        label={{
                          value: "Start",
                          fill: "#6b7280",
                          fontSize: 11,
                        }}
                      />
                      <Line
                        type="monotone"
                        dataKey="total_value"
                        stroke="#60a5fa"
                        strokeWidth={2}
                        dot={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              {/* Sector Exposure Pie */}
              {data.metrics.sector_exposure.length > 0 && (
                <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
                  <h2 className="text-sm text-gray-400 mb-4">
                    Sector Exposure
                  </h2>
                  <ResponsiveContainer width="100%" height={250}>
                    <PieChart>
                      <Pie
                        data={data.metrics.sector_exposure}
                        dataKey="pct"
                        nameKey="sector"
                        cx="50%"
                        cy="50%"
                        outerRadius={90}
                        label={({ sector, pct }: any) =>
                          `${sector} ${pct}%`
                        }
                        labelLine={{ stroke: "#6b7280" }}
                      >
                        {data.metrics.sector_exposure.map((entry) => (
                          <Cell
                            key={entry.sector}
                            fill={SECTOR_COLORS[entry.sector] || "#6b7280"}
                          />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#1f2937",
                          border: "1px solid #374151",
                          borderRadius: "8px",
                        }}
                        formatter={(value) => [`${Number(value).toFixed(1)}%`, "Weight"]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* Trade Activity Chart */}
            {data.metrics.trade_history.length > 0 && (
              <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
                <h2 className="text-sm text-gray-400 mb-4">Trade Activity</h2>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={data.metrics.trade_history}>
                    <XAxis
                      dataKey="date"
                      tick={{ fill: "#6b7280", fontSize: 11 }}
                      tickFormatter={(d) =>
                        new Date(d + "T12:00:00").toLocaleDateString("en-US", {
                          month: "short",
                          day: "numeric",
                        })
                      }
                    />
                    <YAxis tick={{ fill: "#6b7280", fontSize: 11 }} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1f2937",
                        border: "1px solid #374151",
                        borderRadius: "8px",
                      }}
                      labelFormatter={(d) =>
                        new Date(String(d) + "T12:00:00").toLocaleDateString()
                      }
                    />
                    <Bar dataKey="buys" fill="#34d399" name="Buys" />
                    <Bar dataKey="sells" fill="#f87171" name="Sells" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Empty state hints */}
            {data.metrics.total_trades === 0 && (
              <div className="bg-gray-900 rounded-lg border border-gray-800 p-8 text-center">
                <h2 className="text-lg font-semibold text-white mb-2">
                  No trades yet!
                </h2>
                <p className="text-gray-400 mb-4">
                  Start trading to see your analytics here. Your performance
                  will be scored and compared against our 20 AI traders.
                </p>
                <a
                  href="/trade"
                  className="inline-block px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-500 transition"
                >
                  Make Your First Trade
                </a>
              </div>
            )}
          </div>
        ) : null}
      </main>
    </div>
  );
}
