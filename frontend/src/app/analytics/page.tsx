"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
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
  Cell,
  PieChart,
  Pie,
  LineChart,
  Line,
  Legend,
  ReferenceLine,
} from "recharts";

const PERSONALITY_COLORS: Record<string, string> = {
  vanilla: "#9ca3af",
  steady_eddie: "#60a5fa",
  yolo_bot: "#f87171",
  contrarian_carl: "#a78bfa",
  crypto_chad: "#fb923c",
};

const PERSONALITY_LABELS: Record<string, string> = {
  vanilla: "Vanilla",
  steady_eddie: "Steady Eddie",
  yolo_bot: "YOLO Bot",
  contrarian_carl: "Contrarian Carl",
  crypto_chad: "Crypto Chad",
};

const MODEL_COLORS: Record<string, string> = {
  "Gemini Flash": "#34d399",
  "Gemini Pro": "#3b82f6",
  Mistral: "#f59e0b",
  GPT: "#8b5cf6",
};

const SECTOR_COLORS: Record<string, string> = {
  Technology: "#60a5fa",
  Finance: "#34d399",
  Healthcare: "#f87171",
  Consumer: "#fb923c",
  Industrial: "#a78bfa",
  Energy: "#fbbf24",
  Crypto: "#f97316",
  ETF: "#9ca3af",
  Other: "#6b7280",
};

type Tab = "overview" | "benchmark" | "individual";

interface ComparisonData {
  traders: {
    id: string;
    display_name: string;
    model: string;
    personality: string;
    win_rate: number;
    total_trades: number;
    total_realized_pnl: number;
    profit_factor: number;
    sharpe_ratio: number;
    max_drawdown_pct: number;
    total_return_pct: number;
    annualized_volatility: number;
  }[];
  by_model: Record<string, GroupStats>;
  by_personality: Record<string, GroupStats>;
}

interface GroupStats {
  count: number;
  avg_win_rate: number;
  avg_return_pct: number;
  avg_sharpe: number;
  avg_max_drawdown: number;
  avg_profit_factor: number;
  total_trades: number;
  best_trader: string;
  worst_trader: string;
}

interface TraderAnalytics {
  trader: { id: string; display_name: string; ai_model: string | null; is_ai: boolean };
  analytics: {
    total_trades: number;
    buy_count: number;
    sell_count: number;
    win_rate: number;
    avg_win: number;
    avg_loss: number;
    largest_win: number;
    largest_loss: number;
    total_realized_pnl: number;
    profit_factor: number;
    sharpe_ratio: number;
    max_drawdown_pct: number;
    max_drawdown_date: string | null;
    annualized_volatility: number;
    current_drawdown_pct: number;
    total_return_pct: number;
    daily_returns: { date: string; total_value: number; return_pct: number }[];
    sector_exposure: { sector: string; value: number; pct: number }[];
    trade_history: { date: string; buys: number; sells: number; volume: number }[];
    total_snapshots: number;
  };
}

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
      <p className="text-xs text-gray-400 mb-1">{label}</p>
      <p className={`text-lg font-bold ${color || "text-white"}`}>{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-0.5">{sub}</p>}
    </div>
  );
}

function MetricBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min((Math.abs(value) / max) * 100, 100) : 0;
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-gray-400 w-28 shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-white w-16 text-right">{value.toFixed(1)}%</span>
    </div>
  );
}

export default function AnalyticsPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("overview");
  const [comparison, setComparison] = useState<ComparisonData | null>(null);
  const [selectedTrader, setSelectedTrader] = useState<string | null>(null);
  const [traderDetail, setTraderDetail] = useState<TraderAnalytics | null>(null);
  const [benchmarkData, setBenchmarkData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) router.push("/auth");
  }, [user, authLoading, router]);

  useEffect(() => {
    if (user) {
      setLoading(true);
      Promise.all([
        api.getAiComparison().then(setComparison),
        api.getBenchmark(90).then(setBenchmarkData),
      ])
        .catch(console.error)
        .finally(() => setLoading(false));
    }
  }, [user]);

  useEffect(() => {
    if (selectedTrader) {
      setDetailLoading(true);
      api
        .getTraderAnalytics(selectedTrader)
        .then(setTraderDetail)
        .catch(console.error)
        .finally(() => setDetailLoading(false));
    }
  }, [selectedTrader]);

  if (authLoading || !user) return null;

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-6xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-white">AI Performance Analytics</h1>
          <Link
            href="/how-it-works"
            className="text-sm text-blue-400 hover:text-blue-300 transition"
          >
            Trading Glossary →
          </Link>
        </div>

        {/* Tab Switcher */}
        <div className="flex mb-6">
          {([
            ["overview", "Model & Personality"],
            ["benchmark", "vs SPY Benchmark"],
            ["individual", "Trader Deep Dive"],
          ] as [Tab, string][]).map(([t, label]) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex-1 py-2 text-center text-sm font-medium border-b-2 transition ${
                tab === t
                  ? "border-blue-500 text-white"
                  : "border-transparent text-gray-400 hover:text-white"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {loading ? (
          <p className="text-gray-400">Loading analytics...</p>
        ) : tab === "overview" && comparison ? (
          <OverviewTab data={comparison} onSelectTrader={(id) => { setSelectedTrader(id); setTab("individual"); }} />
        ) : tab === "benchmark" && benchmarkData ? (
          <BenchmarkTab data={benchmarkData} />
        ) : tab === "individual" ? (
          <IndividualTab
            traders={comparison?.traders || []}
            selectedTrader={selectedTrader}
            onSelectTrader={setSelectedTrader}
            detail={traderDetail}
            loading={detailLoading}
          />
        ) : null}
      </main>
    </div>
  );
}

function OverviewTab({ data, onSelectTrader }: { data: ComparisonData; onSelectTrader: (id: string) => void }) {
  const returnColor = (v: number) => (v >= 0 ? "text-green-400" : "text-red-400");

  // Prepare chart data for return comparison
  const returnChartData = data.traders.map((t) => ({
    name: t.display_name.replace(/ \(.*\)/, ""),
    return: t.total_return_pct,
    personality: t.personality,
    model: t.model,
  }));

  return (
    <div className="space-y-6">
      {/* Return Comparison Bar Chart */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Total Return by Trader</h2>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={returnChartData} margin={{ top: 5, right: 10, left: 10, bottom: 60 }}>
            <XAxis
              dataKey="name"
              tick={{ fill: "#9ca3af", fontSize: 10 }}
              tickLine={false}
              axisLine={{ stroke: "#374151" }}
              angle={-45}
              textAnchor="end"
              interval={0}
            />
            <YAxis
              tick={{ fill: "#9ca3af", fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => `${v}%`}
            />
            <Tooltip
              contentStyle={{ backgroundColor: "#1f2937", border: "1px solid #374151", borderRadius: "8px", color: "#fff" }}
              formatter={(value: unknown, _name: unknown, props: { payload?: { personality?: string; model?: string } }) => {
                const personality = PERSONALITY_LABELS[props?.payload?.personality || ""] || "";
                const model = props?.payload?.model || "";
                return [`${Number(value).toFixed(2)}%`, `${personality} · ${model}`];
              }}
            />
            <Bar dataKey="return" radius={[4, 4, 0, 0]}>
              {returnChartData.map((entry, i) => (
                <Cell
                  key={i}
                  fill={MODEL_COLORS[entry.model] || "#6b7280"}
                  cursor="pointer"
                  onClick={() => onSelectTrader(data.traders[i].id)}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <div className="flex flex-wrap gap-4 mt-4 justify-center">
          {Object.entries(MODEL_COLORS).map(([model, color]) => (
            <div key={model} className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm" style={{ backgroundColor: color }} />
              <span className="text-xs text-gray-400">{model}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Model Comparison */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Performance by Model</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-400 border-b border-gray-800">
                <th className="px-4 py-2">Model</th>
                <th className="px-4 py-2 text-right">Avg Return</th>
                <th className="px-4 py-2 text-right">Avg Win Rate</th>
                <th className="px-4 py-2 text-right">Avg Sharpe</th>
                <th className="px-4 py-2 text-right">Avg Drawdown</th>
                <th className="px-4 py-2 text-right">Profit Factor</th>
                <th className="px-4 py-2 text-right">Trades</th>
                <th className="px-4 py-2">Best</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.by_model).map(([model, stats]) => (
                <tr key={model} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-4 py-3">
                    <span className="font-medium text-white">{model}</span>
                    <span className="text-gray-500 text-xs ml-2">({stats.count} traders)</span>
                  </td>
                  <td className={`px-4 py-3 text-right font-medium ${returnColor(stats.avg_return_pct)}`}>
                    {stats.avg_return_pct > 0 ? "+" : ""}{stats.avg_return_pct.toFixed(2)}%
                  </td>
                  <td className="px-4 py-3 text-right text-gray-300">{stats.avg_win_rate.toFixed(1)}%</td>
                  <td className={`px-4 py-3 text-right ${stats.avg_sharpe >= 1 ? "text-green-400" : stats.avg_sharpe >= 0 ? "text-yellow-400" : "text-red-400"}`}>
                    {stats.avg_sharpe.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-red-400">-{stats.avg_max_drawdown.toFixed(1)}%</td>
                  <td className="px-4 py-3 text-right text-gray-300">{stats.avg_profit_factor.toFixed(2)}</td>
                  <td className="px-4 py-3 text-right text-gray-300">{stats.total_trades}</td>
                  <td className="px-4 py-3 text-gray-300 text-xs">{stats.best_trader}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Personality Comparison */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Performance by Personality</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-400 border-b border-gray-800">
                <th className="px-4 py-2">Personality</th>
                <th className="px-4 py-2 text-right">Avg Return</th>
                <th className="px-4 py-2 text-right">Avg Win Rate</th>
                <th className="px-4 py-2 text-right">Avg Sharpe</th>
                <th className="px-4 py-2 text-right">Avg Drawdown</th>
                <th className="px-4 py-2 text-right">Profit Factor</th>
                <th className="px-4 py-2 text-right">Trades</th>
                <th className="px-4 py-2">Best</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.by_personality).map(([personality, stats]) => (
                <tr key={personality} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-4 py-3">
                    <span
                      className="inline-block w-2 h-2 rounded-full mr-2"
                      style={{ backgroundColor: PERSONALITY_COLORS[personality] }}
                    />
                    <span className="font-medium text-white">{PERSONALITY_LABELS[personality] || personality}</span>
                  </td>
                  <td className={`px-4 py-3 text-right font-medium ${returnColor(stats.avg_return_pct)}`}>
                    {stats.avg_return_pct > 0 ? "+" : ""}{stats.avg_return_pct.toFixed(2)}%
                  </td>
                  <td className="px-4 py-3 text-right text-gray-300">{stats.avg_win_rate.toFixed(1)}%</td>
                  <td className={`px-4 py-3 text-right ${stats.avg_sharpe >= 1 ? "text-green-400" : stats.avg_sharpe >= 0 ? "text-yellow-400" : "text-red-400"}`}>
                    {stats.avg_sharpe.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-red-400">-{stats.avg_max_drawdown.toFixed(1)}%</td>
                  <td className="px-4 py-3 text-right text-gray-300">{stats.avg_profit_factor.toFixed(2)}</td>
                  <td className="px-4 py-3 text-right text-gray-300">{stats.total_trades}</td>
                  <td className="px-4 py-3 text-gray-300 text-xs">{stats.best_trader}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Full Trader Rankings */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">All AI Traders Ranked</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-400 border-b border-gray-800">
                <th className="px-4 py-2">#</th>
                <th className="px-4 py-2">Trader</th>
                <th className="px-4 py-2">Model</th>
                <th className="px-4 py-2 text-right">Return</th>
                <th className="px-4 py-2 text-right">Win Rate</th>
                <th className="px-4 py-2 text-right">Sharpe</th>
                <th className="px-4 py-2 text-right">Max DD</th>
                <th className="px-4 py-2 text-right">Realized P&L</th>
              </tr>
            </thead>
            <tbody>
              {data.traders.map((t, i) => (
                <tr
                  key={t.id}
                  className="border-b border-gray-800/50 hover:bg-gray-800/30 cursor-pointer"
                  onClick={() => onSelectTrader(t.id)}
                >
                  <td className="px-4 py-3 text-gray-500">{i + 1}</td>
                  <td className="px-4 py-3">
                    <span
                      className="inline-block w-2 h-2 rounded-full mr-2"
                      style={{ backgroundColor: PERSONALITY_COLORS[t.personality] }}
                    />
                    <span className="font-medium text-white">{t.display_name}</span>
                  </td>
                  <td className="px-4 py-3 text-gray-400">{t.model}</td>
                  <td className={`px-4 py-3 text-right font-medium ${returnColor(t.total_return_pct)}`}>
                    {t.total_return_pct > 0 ? "+" : ""}{t.total_return_pct.toFixed(2)}%
                  </td>
                  <td className="px-4 py-3 text-right text-gray-300">{t.win_rate.toFixed(1)}%</td>
                  <td className={`px-4 py-3 text-right ${t.sharpe_ratio >= 1 ? "text-green-400" : t.sharpe_ratio >= 0 ? "text-yellow-400" : "text-red-400"}`}>
                    {t.sharpe_ratio.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-red-400">-{t.max_drawdown_pct.toFixed(1)}%</td>
                  <td className={`px-4 py-3 text-right ${returnColor(t.total_realized_pnl)}`}>
                    {formatCurrency(t.total_realized_pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function IndividualTab({
  traders,
  selectedTrader,
  onSelectTrader,
  detail,
  loading,
}: {
  traders: ComparisonData["traders"];
  selectedTrader: string | null;
  onSelectTrader: (id: string) => void;
  detail: TraderAnalytics | null;
  loading: boolean;
}) {
  return (
    <div className="space-y-6">
      {/* Trader Selector */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
        <label className="text-sm text-gray-400 block mb-2">Select Trader</label>
        <select
          value={selectedTrader || ""}
          onChange={(e) => onSelectTrader(e.target.value)}
          className="w-full bg-gray-800 text-white border border-gray-700 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="">Choose a trader...</option>
          {traders.map((t) => (
            <option key={t.id} value={t.id}>
              {t.display_name} ({t.model})
            </option>
          ))}
        </select>
      </div>

      {loading && <p className="text-gray-400">Loading trader analytics...</p>}

      {!loading && detail && <TraderDetail data={detail} />}

      {!loading && !detail && selectedTrader && (
        <p className="text-gray-400">No analytics data available for this trader.</p>
      )}
    </div>
  );
}

function TraderDetail({ data }: { data: TraderAnalytics }) {
  const { trader, analytics: a } = data;
  const returnColor = (v: number) => (v >= 0 ? "text-green-400" : "text-red-400");

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-white">{trader.display_name}</h2>
            <p className="text-gray-400 text-sm">{trader.ai_model}</p>
          </div>
          <div className="text-right">
            <p className={`text-2xl font-bold ${returnColor(a.total_return_pct)}`}>
              {a.total_return_pct > 0 ? "+" : ""}{a.total_return_pct.toFixed(2)}%
            </p>
            <p className="text-xs text-gray-400">Total Return</p>
          </div>
        </div>
      </div>

      {/* Key Metrics Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard
          label="Win Rate"
          value={`${a.win_rate.toFixed(1)}%`}
          sub={`${a.sell_count} closed trades`}
          color={a.win_rate >= 50 ? "text-green-400" : "text-red-400"}
        />
        <StatCard
          label="Sharpe Ratio"
          value={a.sharpe_ratio.toFixed(2)}
          sub={a.sharpe_ratio >= 1 ? "Good" : a.sharpe_ratio >= 0.5 ? "Moderate" : "Poor"}
          color={a.sharpe_ratio >= 1 ? "text-green-400" : a.sharpe_ratio >= 0 ? "text-yellow-400" : "text-red-400"}
        />
        <StatCard
          label="Max Drawdown"
          value={`-${a.max_drawdown_pct.toFixed(1)}%`}
          sub={a.max_drawdown_date || undefined}
          color="text-red-400"
        />
        <StatCard
          label="Volatility (Ann.)"
          value={`${a.annualized_volatility.toFixed(1)}%`}
          sub={a.annualized_volatility < 15 ? "Low" : a.annualized_volatility < 30 ? "Moderate" : "High"}
        />
        <StatCard
          label="Profit Factor"
          value={a.profit_factor.toFixed(2)}
          sub={a.profit_factor >= 1.5 ? "Profitable" : a.profit_factor >= 1 ? "Marginal" : "Unprofitable"}
          color={a.profit_factor >= 1.5 ? "text-green-400" : a.profit_factor >= 1 ? "text-yellow-400" : "text-red-400"}
        />
        <StatCard
          label="Avg Win"
          value={formatCurrency(a.avg_win)}
          color="text-green-400"
        />
        <StatCard
          label="Avg Loss"
          value={formatCurrency(Math.abs(a.avg_loss))}
          color="text-red-400"
        />
        <StatCard
          label="Realized P&L"
          value={formatCurrency(a.total_realized_pnl)}
          color={returnColor(a.total_realized_pnl)}
        />
      </div>

      {/* Largest Win/Loss */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <p className="text-xs text-gray-400 mb-1">Largest Win</p>
          <p className="text-xl font-bold text-green-400">{formatCurrency(a.largest_win)}</p>
        </div>
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <p className="text-xs text-gray-400 mb-1">Largest Loss</p>
          <p className="text-xl font-bold text-red-400">{formatCurrency(Math.abs(a.largest_loss))}</p>
        </div>
      </div>

      {/* Sector Exposure Pie Chart */}
      {a.sector_exposure.length > 0 && (
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
          <h3 className="text-lg font-semibold text-white mb-4">Sector Exposure</h3>
          <div className="flex flex-col sm:flex-row items-center gap-6">
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={a.sector_exposure}
                  dataKey="pct"
                  nameKey="sector"
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  innerRadius={50}
                  paddingAngle={2}
                  label={({ sector, pct }: any) => `${sector} ${pct}%`}
                  labelLine={false}
                >
                  {a.sector_exposure.map((entry, i) => (
                    <Cell key={i} fill={SECTOR_COLORS[entry.sector] || "#6b7280"} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ backgroundColor: "#1f2937", border: "1px solid #374151", borderRadius: "8px", color: "#fff" }}
                  formatter={(value, name) => [`${Number(value).toFixed(1)}%`, name]}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="space-y-2 text-sm shrink-0">
              {a.sector_exposure.map((s) => (
                <div key={s.sector} className="flex items-center gap-2">
                  <span
                    className="w-3 h-3 rounded-sm shrink-0"
                    style={{ backgroundColor: SECTOR_COLORS[s.sector] || "#6b7280" }}
                  />
                  <span className="text-gray-300">{s.sector}</span>
                  <span className="text-white font-medium ml-auto">{s.pct.toFixed(1)}%</span>
                  <span className="text-gray-500">{formatCurrency(s.value)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Trade Activity */}
      {a.trade_history.length > 0 && (
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
          <h3 className="text-lg font-semibold text-white mb-4">Trade Activity</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={a.trade_history} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
              <XAxis
                dataKey="date"
                tick={{ fill: "#9ca3af", fontSize: 10 }}
                tickLine={false}
                axisLine={{ stroke: "#374151" }}
                tickFormatter={(d: string) => {
                  const dt = new Date(d + "T12:00:00");
                  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
                }}
              />
              <YAxis
                tick={{ fill: "#9ca3af", fontSize: 12 }}
                tickLine={false}
                axisLine={false}
                allowDecimals={false}
              />
              <Tooltip
                contentStyle={{ backgroundColor: "#1f2937", border: "1px solid #374151", borderRadius: "8px", color: "#fff" }}
              />
              <Bar dataKey="buys" fill="#22c55e" name="Buys" radius={[2, 2, 0, 0]} />
              <Bar dataKey="sells" fill="#ef4444" name="Sells" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Trade Breakdown */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
        <h3 className="text-lg font-semibold text-white mb-4">Trade Breakdown</h3>
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="text-2xl font-bold text-white">{a.total_trades}</p>
            <p className="text-xs text-gray-400">Total Trades</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-green-400">{a.buy_count}</p>
            <p className="text-xs text-gray-400">Buys</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-red-400">{a.sell_count}</p>
            <p className="text-xs text-gray-400">Sells</p>
          </div>
        </div>
        {a.current_drawdown_pct > 0 && (
          <div className="mt-4 pt-4 border-t border-gray-800">
            <MetricBar label="Current DD" value={a.current_drawdown_pct} max={a.max_drawdown_pct || 10} color="bg-red-500" />
          </div>
        )}
      </div>

      {/* Link to trader profile */}
      <div className="text-center">
        <Link
          href={`/traders/${data.trader.id}`}
          className="text-blue-400 hover:text-blue-300 text-sm transition"
        >
          View full trader profile &rarr;
        </Link>
      </div>
    </div>
  );
}

function BenchmarkTab({ data }: { data: any }) {
  const returnColor = (v: number) => (v >= 0 ? "text-green-400" : "text-red-400");

  // Guard against error responses or missing data
  if (!data || data.error || !data.benchmark || !data.traders || !data.summary) {
    return (
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-8 text-center">
        <p className="text-gray-400 mb-2">Benchmark data is not available yet.</p>
        <p className="text-gray-500 text-sm">
          {data?.error || "The AI traders need at least a few days of trading data before benchmark comparisons can be generated."}
        </p>
      </div>
    );
  }

  const { benchmark, traders, summary } = data;

  // Build chart data — merge SPY series with top 5 traders
  const topTraders = traders.slice(0, 5);
  const dateMap: Record<string, any> = {};

  for (const point of benchmark.series) {
    dateMap[point.date] = { date: point.date, SPY: point.return_pct };
  }

  const LINE_COLORS = ["#60a5fa", "#f87171", "#34d399", "#fb923c", "#a78bfa"];
  for (let i = 0; i < topTraders.length; i++) {
    const t = topTraders[i];
    for (const point of t.series) {
      if (!dateMap[point.date]) dateMap[point.date] = { date: point.date };
      dateMap[point.date][t.display_name] = point.return_pct;
    }
  }

  const chartData = Object.values(dateMap).sort((a: any, b: any) => a.date.localeCompare(b.date));

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard
          label="SPY Return"
          value={`${benchmark.return_pct > 0 ? "+" : ""}${benchmark.return_pct.toFixed(2)}%`}
          sub={`${data.period_days} days`}
          color={returnColor(benchmark.return_pct)}
        />
        <StatCard
          label="Beating SPY"
          value={`${summary.beating_spy} / ${summary.total_traders}`}
          color={summary.beating_spy > summary.losing_to_spy ? "text-green-400" : "text-red-400"}
        />
        <StatCard
          label="Avg Alpha"
          value={`${summary.avg_alpha > 0 ? "+" : ""}${summary.avg_alpha.toFixed(2)}%`}
          sub="vs SPY buy-and-hold"
          color={returnColor(summary.avg_alpha)}
        />
        <StatCard
          label="Best Trader"
          value={summary.best_trader?.replace(/ \(.*\)/, "") || "N/A"}
          sub={traders.length > 0 ? `${traders[0].total_return_pct > 0 ? "+" : ""}${traders[0].total_return_pct.toFixed(2)}%` : ""}
        />
      </div>

      {/* Performance Chart */}
      {chartData.length > 1 && (
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Top 5 Traders vs SPY</h2>
          <ResponsiveContainer width="100%" height={350}>
            <LineChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
              <XAxis
                dataKey="date"
                tick={{ fill: "#9ca3af", fontSize: 10 }}
                tickLine={false}
                axisLine={{ stroke: "#374151" }}
                tickFormatter={(d: string) => {
                  const dt = new Date(d + "T12:00:00");
                  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
                }}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fill: "#9ca3af", fontSize: 12 }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: number) => `${v}%`}
              />
              <Tooltip
                contentStyle={{ backgroundColor: "#1f2937", border: "1px solid #374151", borderRadius: "8px", color: "#fff" }}
                formatter={(value: any) => [`${Number(value).toFixed(2)}%`]}
                labelFormatter={(d: any) => {
                  const dt = new Date(String(d) + "T12:00:00");
                  return dt.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
                }}
              />
              <Legend />
              <ReferenceLine y={0} stroke="#6b7280" strokeDasharray="4 4" />
              <Line type="monotone" dataKey="SPY" stroke="#fbbf24" strokeWidth={2} dot={false} />
              {topTraders.map((t: any, i: number) => (
                <Line
                  key={t.id}
                  type="monotone"
                  dataKey={t.display_name}
                  stroke={LINE_COLORS[i]}
                  strokeWidth={1.5}
                  dot={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Alpha Ranking Table */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Alpha vs SPY ({benchmark.return_pct > 0 ? "+" : ""}{benchmark.return_pct.toFixed(2)}%)</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-400 border-b border-gray-800">
                <th className="px-4 py-2">#</th>
                <th className="px-4 py-2">Trader</th>
                <th className="px-4 py-2">Model</th>
                <th className="px-4 py-2 text-right">Return</th>
                <th className="px-4 py-2 text-right">Alpha</th>
                <th className="px-4 py-2 text-center">Beats SPY?</th>
              </tr>
            </thead>
            <tbody>
              {traders.map((t: any, i: number) => (
                <tr key={t.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-4 py-3 text-gray-500">{i + 1}</td>
                  <td className="px-4 py-3">
                    <span
                      className="inline-block w-2 h-2 rounded-full mr-2"
                      style={{ backgroundColor: PERSONALITY_COLORS[t.personality] || "#6b7280" }}
                    />
                    <span className="font-medium text-white">{t.display_name}</span>
                  </td>
                  <td className="px-4 py-3 text-gray-400">{t.model}</td>
                  <td className={`px-4 py-3 text-right font-medium ${returnColor(t.total_return_pct)}`}>
                    {t.total_return_pct > 0 ? "+" : ""}{t.total_return_pct.toFixed(2)}%
                  </td>
                  <td className={`px-4 py-3 text-right font-medium ${returnColor(t.alpha)}`}>
                    {t.alpha > 0 ? "+" : ""}{t.alpha.toFixed(2)}%
                  </td>
                  <td className="px-4 py-3 text-center">
                    {t.beats_spy ? (
                      <span className="text-green-400 font-bold">YES</span>
                    ) : (
                      <span className="text-red-400">NO</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
