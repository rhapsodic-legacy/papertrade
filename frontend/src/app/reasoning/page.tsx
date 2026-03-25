"use client";

import { useEffect, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import Navbar from "@/components/Navbar";

const PERSONALITY_COLORS: Record<string, string> = {
  Vanilla: "bg-blue-900/40 text-blue-400 border-blue-800",
  "Steady Eddie": "bg-green-900/40 text-green-400 border-green-800",
  "YOLO Bot": "bg-red-900/40 text-red-400 border-red-800",
  "Contrarian Carl": "bg-purple-900/40 text-purple-400 border-purple-800",
  "Crypto Chad": "bg-yellow-900/40 text-yellow-400 border-yellow-800",
};

function getPersonalityColor(traderName: string): string {
  for (const [personality, color] of Object.entries(PERSONALITY_COLORS)) {
    if (traderName.includes(personality)) return color;
  }
  return "bg-gray-800 text-gray-400 border-gray-700";
}

const MODULE_COLORS: Record<string, string> = {
  technicals: "bg-blue-900/40 text-blue-300 border-blue-700",
  fundamentals: "bg-purple-900/40 text-purple-300 border-purple-700",
  sentiment: "bg-green-900/40 text-green-300 border-green-700",
  macro: "bg-amber-900/40 text-amber-300 border-amber-700",
  momentum: "bg-red-900/40 text-red-300 border-red-700",
  optimizer: "bg-teal-900/40 text-teal-300 border-teal-700",
  memory: "bg-indigo-900/40 text-indigo-300 border-indigo-700",
};

type Trade = {
  trader: string;
  model: string;
  symbol: string;
  asset_type: string;
  side: string;
  quantity: number;
  price: number;
  total: number;
  reasoning: string;
  modules_used: string[];
  time: string;
};

type ConvergenceAlert = {
  date: string;
  symbol: string;
  side: string;
  traders: string[];
  count: number;
  warning: string;
};

type TraderSummary = {
  model: string;
  trades: number;
  top_modules: [string, number][];
};

type ReasoningData = {
  days: number;
  total_trades: number;
  dates: Record<string, Trade[]>;
  convergence_alerts: ConvergenceAlert[];
  trader_summaries: Record<string, TraderSummary>;
};

function ConvergenceCard({ alert }: { alert: ConvergenceAlert }) {
  return (
    <div className="flex items-start gap-3 p-3 bg-amber-900/20 border border-amber-800/50 rounded-lg">
      <div className="text-amber-400 mt-0.5 shrink-0">
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
          />
        </svg>
      </div>
      <div>
        <p className="text-sm text-amber-300 font-medium">{alert.warning}</p>
        <p className="text-xs text-gray-400 mt-1">
          {alert.date} &middot; {alert.traders.join(", ")}
        </p>
      </div>
    </div>
  );
}

function TradeRow({ trade, isHighlighted }: { trade: Trade; isHighlighted: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const sideColor = trade.side === "buy" ? "text-green-400" : "text-red-400";
  const sideBg = trade.side === "buy" ? "bg-green-900/30" : "bg-red-900/30";
  const highlightBorder = isHighlighted ? "border-amber-800/50" : "border-gray-800";

  return (
    <div className={`bg-gray-900 rounded-lg border ${highlightBorder} p-4 hover:border-gray-700 transition`}>
      {/* Header row */}
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs font-medium px-2 py-0.5 rounded border ${getPersonalityColor(trade.trader)}`}>
            {trade.trader}
          </span>
          <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">
            {trade.model}
          </span>
          {isHighlighted && (
            <span className="text-xs text-amber-400 bg-amber-900/30 px-2 py-0.5 rounded border border-amber-800/50">
              convergence
            </span>
          )}
        </div>
        <span className="text-xs text-gray-500 whitespace-nowrap">{trade.time}</span>
      </div>

      {/* Trade action */}
      <div className="flex items-center gap-3 mb-3">
        <span className={`text-sm font-bold uppercase ${sideColor} ${sideBg} px-2 py-0.5 rounded`}>
          {trade.side}
        </span>
        <span className="text-white font-semibold">{trade.symbol}</span>
        <span className="text-gray-400 text-sm">
          {trade.quantity} @ {formatCurrency(trade.price)}
        </span>
        <span className="text-gray-500 text-sm ml-auto">
          {formatCurrency(trade.total)}
        </span>
      </div>

      {/* Module badges */}
      {trade.modules_used.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {trade.modules_used.map((m) => (
            <span
              key={m}
              className={`text-xs px-2 py-0.5 rounded border ${MODULE_COLORS[m] || "bg-gray-800/40 text-gray-300 border-gray-700"}`}
            >
              {m}
            </span>
          ))}
        </div>
      )}

      {/* Reasoning */}
      <div className="bg-gray-950 rounded-md p-3 border border-gray-800">
        <div className="flex items-center gap-2 mb-1">
          <svg className="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
            />
          </svg>
          <span className="text-xs font-medium text-blue-400">AI Reasoning</span>
        </div>
        <p className={`text-sm text-gray-300 leading-relaxed ${!expanded && "line-clamp-3"}`}>
          {trade.reasoning || "No reasoning recorded."}
        </p>
        {trade.reasoning && trade.reasoning.length > 200 && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-blue-400 hover:text-blue-300 mt-1 transition"
          >
            {expanded ? "Show less" : "Read more"}
          </button>
        )}
      </div>
    </div>
  );
}

function TraderSummaryCard({
  name,
  summary,
}: {
  name: string;
  summary: TraderSummary;
}) {
  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-xs font-medium px-2 py-0.5 rounded border ${getPersonalityColor(name)}`}>
          {name}
        </span>
        <span className="text-xs text-gray-500">{summary.model}</span>
      </div>
      <p className="text-sm text-white mb-2">
        {summary.trades} trade{summary.trades !== 1 ? "s" : ""}
      </p>
      {summary.top_modules.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {summary.top_modules.map(([mod, count]) => (
            <span
              key={mod}
              className={`text-[10px] px-1.5 py-0.5 rounded border ${MODULE_COLORS[mod] || "bg-gray-800/40 text-gray-300 border-gray-700"}`}
            >
              {mod} ({count})
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ReasoningPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<ReasoningData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(7);
  const [filterSymbol, setFilterSymbol] = useState("");
  const [filterTrader, setFilterTrader] = useState("");
  const [tab, setTab] = useState<"timeline" | "summaries">("timeline");

  useEffect(() => {
    if (!authLoading && !user) router.push("/auth");
  }, [user, authLoading, router]);

  useEffect(() => {
    if (user) {
      setLoading(true);
      api
        .getTradeReasoning({
          days,
          symbol: filterSymbol || undefined,
        })
        .then(setData)
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
    }
  }, [user, days, filterSymbol]);

  // Build set of convergence symbols for highlighting
  const convergenceKeys = useMemo(() => {
    if (!data) return new Set<string>();
    return new Set(
      data.convergence_alerts.map((a) => `${a.date}:${a.symbol}:${a.side}`)
    );
  }, [data]);

  // Filter trades by trader name if selected
  const filteredDates = useMemo(() => {
    if (!data) return {};
    if (!filterTrader) return data.dates;
    const result: Record<string, Trade[]> = {};
    for (const [date, trades] of Object.entries(data.dates)) {
      const filtered = trades.filter((t) => t.trader === filterTrader);
      if (filtered.length > 0) result[date] = filtered;
    }
    return result;
  }, [data, filterTrader]);

  // Get unique trader names for filter dropdown
  const traderNames = useMemo(() => {
    if (!data) return [];
    return Object.keys(data.trader_summaries).sort();
  }, [data]);

  if (authLoading || !user) return null;

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-white mb-2">AI Reasoning Viewer</h1>
          <p className="text-gray-400">
            See exactly why each AI trader made their decisions. Spot patterns,
            detect herd behavior, and understand what data drives each trade.
          </p>
        </div>

        {/* Convergence Alerts */}
        {data && data.convergence_alerts.length > 0 && (
          <div className="mb-6 space-y-2">
            <h2 className="text-sm font-medium text-amber-400 mb-2">
              Convergence Alerts ({data.convergence_alerts.length})
            </h2>
            {data.convergence_alerts.map((alert, i) => (
              <ConvergenceCard key={i} alert={alert} />
            ))}
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-1 mb-6 bg-gray-900 rounded-lg p-1 w-fit">
          <button
            onClick={() => setTab("timeline")}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${
              tab === "timeline" ? "bg-gray-800 text-white" : "text-gray-400 hover:text-white"
            }`}
          >
            Timeline
          </button>
          <button
            onClick={() => setTab("summaries")}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${
              tab === "summaries" ? "bg-gray-800 text-white" : "text-gray-400 hover:text-white"
            }`}
          >
            Trader Summaries
          </button>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap gap-3 mb-6">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="bg-gray-900 border border-gray-800 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
          >
            <option value={1}>Today</option>
            <option value={3}>Last 3 days</option>
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
          </select>

          {tab === "timeline" && (
            <>
              <select
                value={filterTrader}
                onChange={(e) => setFilterTrader(e.target.value)}
                className="bg-gray-900 border border-gray-800 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              >
                <option value="">All Traders</option>
                {traderNames.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>

              <input
                type="text"
                placeholder="Filter by symbol..."
                value={filterSymbol}
                onChange={(e) => setFilterSymbol(e.target.value.toUpperCase())}
                className="bg-gray-900 border border-gray-800 text-white text-sm rounded-lg px-3 py-2 w-40 focus:outline-none focus:border-blue-500"
              />
            </>
          )}

          {(filterTrader || filterSymbol) && (
            <button
              onClick={() => {
                setFilterTrader("");
                setFilterSymbol("");
              }}
              className="text-sm text-gray-400 hover:text-white px-3 py-2 transition"
            >
              Clear filters
            </button>
          )}

          {data && (
            <span className="text-xs text-gray-500 self-center ml-auto">
              {data.total_trades} trades total
            </span>
          )}
        </div>

        {/* Content */}
        {loading ? (
          <p className="text-gray-400">Loading trade reasoning...</p>
        ) : error ? (
          <p className="text-red-400">Error: {error}</p>
        ) : !data || data.total_trades === 0 ? (
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-8 text-center">
            <p className="text-gray-400">No AI trades found for this period.</p>
          </div>
        ) : tab === "timeline" ? (
          <div className="space-y-8">
            {Object.entries(filteredDates).map(([date, trades]) => (
              <div key={date}>
                <div className="flex items-center gap-3 mb-4">
                  <h3 className="text-lg font-semibold text-white">{date}</h3>
                  <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">
                    {trades.length} trade{trades.length !== 1 ? "s" : ""}
                  </span>
                </div>
                <div className="space-y-3">
                  {trades.map((trade, i) => {
                    const isHighlighted = convergenceKeys.has(
                      `${date}:${trade.symbol}:${trade.side}`
                    );
                    return (
                      <TradeRow
                        key={`${trade.trader}-${trade.symbol}-${i}`}
                        trade={trade}
                        isHighlighted={isHighlighted}
                      />
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(data.trader_summaries)
              .sort(([, a], [, b]) => b.trades - a.trades)
              .map(([name, summary]) => (
                <TraderSummaryCard key={name} name={name} summary={summary} />
              ))}
          </div>
        )}
      </main>
    </div>
  );
}
