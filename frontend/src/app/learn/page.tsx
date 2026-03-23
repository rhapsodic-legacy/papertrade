"use client";

import { useEffect, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import Navbar from "@/components/Navbar";

const PERSONALITY_LABELS: Record<string, string> = {
  vanilla: "Vanilla",
  steady_eddie: "Steady Eddie",
  yolo_bot: "YOLO Bot",
  contrarian_carl: "Contrarian Carl",
  crypto_chad: "Crypto Chad",
};

const PERSONALITY_COLORS: Record<string, string> = {
  vanilla: "bg-blue-900/40 text-blue-400 border-blue-800",
  steady_eddie: "bg-green-900/40 text-green-400 border-green-800",
  yolo_bot: "bg-red-900/40 text-red-400 border-red-800",
  contrarian_carl: "bg-purple-900/40 text-purple-400 border-purple-800",
  crypto_chad: "bg-yellow-900/40 text-yellow-400 border-yellow-800",
};

const MODEL_LABELS: Record<string, string> = {
  gemini: "Gemini",
  mistral: "Mistral",
  groq: "Groq",
};

type Trade = {
  trader_name: string;
  personality: string | null;
  model: string | null;
  symbol: string;
  asset_type: string;
  side: string;
  quantity: number;
  price: number;
  total: number;
  reasoning: string;
  created_at: string;
};

function TradeCard({ trade }: { trade: Trade }) {
  const [expanded, setExpanded] = useState(false);
  const personalityClass =
    PERSONALITY_COLORS[trade.personality || ""] || "bg-gray-800 text-gray-400 border-gray-700";
  const sideColor = trade.side === "buy" ? "text-green-400" : "text-red-400";
  const sideBg = trade.side === "buy" ? "bg-green-900/30" : "bg-red-900/30";

  const modelShort = trade.model || "Unknown";

  const timeAgo = getTimeAgo(trade.created_at);

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 hover:border-gray-700 transition">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs font-medium px-2 py-0.5 rounded border ${personalityClass}`}>
            {PERSONALITY_LABELS[trade.personality || ""] || trade.trader_name}
          </span>
          <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">
            {modelShort}
          </span>
        </div>
        <span className="text-xs text-gray-500 whitespace-nowrap">{timeAgo}</span>
      </div>

      {/* Trade Action */}
      <div className="flex items-center gap-3 mb-3">
        <span className={`text-sm font-bold uppercase ${sideColor} ${sideBg} px-2 py-0.5 rounded`}>
          {trade.side}
        </span>
        <span className="text-white font-semibold">{trade.symbol}</span>
        <span className="text-gray-400 text-sm">
          {trade.quantity} shares @ {formatCurrency(trade.price)}
        </span>
        <span className="text-gray-500 text-sm ml-auto">
          {formatCurrency(trade.total)}
        </span>
      </div>

      {/* Reasoning */}
      <div className="bg-gray-950 rounded-md p-3 border border-gray-800">
        <div className="flex items-center gap-2 mb-1">
          <svg className="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
          <span className="text-xs font-medium text-blue-400">AI Reasoning</span>
        </div>
        <p className={`text-sm text-gray-300 leading-relaxed ${!expanded && "line-clamp-3"}`}>
          {trade.reasoning}
        </p>
        {trade.reasoning.length > 200 && (
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

function ComparisonView({ trades }: { trades: Trade[] }) {
  const [traderA, setTraderA] = useState<string>("");
  const [traderB, setTraderB] = useState<string>("");

  // Get unique trader names
  const traderNames = useMemo(() => {
    const names = new Set(trades.map((t) => t.trader_name));
    return Array.from(names).sort();
  }, [trades]);

  // Set defaults
  useEffect(() => {
    if (traderNames.length >= 2 && !traderA && !traderB) {
      setTraderA(traderNames[0]);
      setTraderB(traderNames[1]);
    }
  }, [traderNames, traderA, traderB]);

  const tradesA = useMemo(
    () => trades.filter((t) => t.trader_name === traderA).slice(0, 10),
    [trades, traderA]
  );
  const tradesB = useMemo(
    () => trades.filter((t) => t.trader_name === traderB).slice(0, 10),
    [trades, traderB]
  );

  // Find symbols both traders traded
  const sharedSymbols = useMemo(() => {
    const symbolsA = new Set(tradesA.map((t) => t.symbol));
    const symbolsB = new Set(tradesB.map((t) => t.symbol));
    return Array.from(symbolsA).filter((s) => symbolsB.has(s));
  }, [tradesA, tradesB]);

  if (traderNames.length < 2) {
    return (
      <div className="text-center text-gray-500 py-8">
        Need at least 2 active traders to compare strategies.
      </div>
    );
  }

  return (
    <div>
      {/* Trader Selectors */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 mb-6">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-400">Trader A:</span>
          <select
            value={traderA}
            onChange={(e) => setTraderA(e.target.value)}
            className="bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-blue-500"
          >
            {traderNames.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <span className="text-gray-600 text-lg font-bold">vs</span>
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-400">Trader B:</span>
          <select
            value={traderB}
            onChange={(e) => setTraderB(e.target.value)}
            className="bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-blue-500"
          >
            {traderNames.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Shared symbols highlight */}
      {sharedSymbols.length > 0 && (
        <div className="mb-4 p-3 bg-blue-900/20 border border-blue-800/50 rounded-lg">
          <span className="text-xs text-blue-400 font-medium">
            Both traded: {sharedSymbols.join(", ")} — compare their reasoning below
          </span>
        </div>
      )}

      {/* Side-by-side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <h3 className="text-sm font-medium text-gray-400 mb-3">{traderA}</h3>
          <div className="space-y-3">
            {tradesA.length > 0 ? (
              tradesA.map((t, i) => (
                <MiniTradeCard
                  key={i}
                  trade={t}
                  highlighted={sharedSymbols.includes(t.symbol)}
                />
              ))
            ) : (
              <p className="text-gray-500 text-sm">No recent trades with reasoning.</p>
            )}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-medium text-gray-400 mb-3">{traderB}</h3>
          <div className="space-y-3">
            {tradesB.length > 0 ? (
              tradesB.map((t, i) => (
                <MiniTradeCard
                  key={i}
                  trade={t}
                  highlighted={sharedSymbols.includes(t.symbol)}
                />
              ))
            ) : (
              <p className="text-gray-500 text-sm">No recent trades with reasoning.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function MiniTradeCard({ trade, highlighted }: { trade: Trade; highlighted: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const sideColor = trade.side === "buy" ? "text-green-400" : "text-red-400";
  const borderColor = highlighted ? "border-blue-700 bg-blue-950/20" : "border-gray-800";

  return (
    <div className={`rounded-lg border p-3 ${borderColor}`}>
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-xs font-bold uppercase ${sideColor}`}>{trade.side}</span>
        <span className="text-white text-sm font-medium">{trade.symbol}</span>
        <span className="text-gray-500 text-xs">
          {trade.quantity} @ {formatCurrency(trade.price)}
        </span>
        {highlighted && (
          <span className="text-xs text-blue-400 ml-auto">shared</span>
        )}
      </div>
      <p className={`text-xs text-gray-400 leading-relaxed ${!expanded && "line-clamp-2"}`}>
        {trade.reasoning}
      </p>
      {trade.reasoning.length > 150 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-blue-400 hover:text-blue-300 mt-1 transition"
        >
          {expanded ? "Less" : "More"}
        </button>
      )}
    </div>
  );
}

function getTimeAgo(dateStr: string): string {
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays === 1) return "yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export default function LearnPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"feed" | "compare">("feed");

  // Filters
  const [filterPersonality, setFilterPersonality] = useState<string>("");
  const [filterModel, setFilterModel] = useState<string>("");
  const [filterSymbol, setFilterSymbol] = useState<string>("");

  useEffect(() => {
    if (!authLoading && !user) router.push("/auth");
  }, [user, authLoading, router]);

  useEffect(() => {
    if (user) {
      setLoading(true);
      api
        .getAiTradeFeed({
          personality: filterPersonality || undefined,
          model: filterModel || undefined,
          symbol: filterSymbol || undefined,
          limit: 100,
        })
        .then((res) => setTrades(res.trades))
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
    }
  }, [user, filterPersonality, filterModel, filterSymbol]);

  if (authLoading || !user) return null;

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-white mb-2">Learn from AI</h1>
          <p className="text-gray-400">
            See exactly what our 20 AI traders are doing and why. Study their reasoning,
            compare strategies, and find patterns to improve your own trading.
          </p>
          <div className="mt-3 inline-flex items-center gap-2 bg-blue-900/20 border border-blue-800/50 rounded-lg px-3 py-2">
            <span className="text-sm text-gray-400">New to trading terms?</span>
            <Link href="/how-it-works" className="text-sm text-blue-400 hover:text-blue-300 font-medium transition">
              Trading Basics & Glossary →
            </Link>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-6 bg-gray-900 rounded-lg p-1 w-fit">
          <button
            onClick={() => setTab("feed")}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${
              tab === "feed"
                ? "bg-gray-800 text-white"
                : "text-gray-400 hover:text-white"
            }`}
          >
            Live Trade Feed
          </button>
          <button
            onClick={() => setTab("compare")}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${
              tab === "compare"
                ? "bg-gray-800 text-white"
                : "text-gray-400 hover:text-white"
            }`}
          >
            Strategy Comparison
          </button>
        </div>

        {tab === "feed" && (
          <>
            {/* Filters */}
            <div className="flex flex-wrap gap-3 mb-6">
              <select
                value={filterPersonality}
                onChange={(e) => setFilterPersonality(e.target.value)}
                className="bg-gray-900 border border-gray-800 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              >
                <option value="">All Personalities</option>
                {Object.entries(PERSONALITY_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>

              <select
                value={filterModel}
                onChange={(e) => setFilterModel(e.target.value)}
                className="bg-gray-900 border border-gray-800 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              >
                <option value="">All Models</option>
                {Object.entries(MODEL_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
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

              {(filterPersonality || filterModel || filterSymbol) && (
                <button
                  onClick={() => {
                    setFilterPersonality("");
                    setFilterModel("");
                    setFilterSymbol("");
                  }}
                  className="text-sm text-gray-400 hover:text-white px-3 py-2 transition"
                >
                  Clear filters
                </button>
              )}
            </div>

            {/* Trade Feed */}
            {loading ? (
              <p className="text-gray-400">Loading AI trades...</p>
            ) : error ? (
              <p className="text-red-400">Error: {error}</p>
            ) : trades.length === 0 ? (
              <div className="bg-gray-900 rounded-lg border border-gray-800 p-8 text-center">
                <p className="text-gray-400">
                  No AI trades found{filterPersonality || filterModel || filterSymbol ? " with those filters" : ""}.
                  Trades appear here after AI traders execute their daily strategies.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {trades.map((trade, i) => (
                  <TradeCard key={`${trade.created_at}-${trade.symbol}-${i}`} trade={trade} />
                ))}
              </div>
            )}
          </>
        )}

        {tab === "compare" && (
          <>
            {loading ? (
              <p className="text-gray-400">Loading trades for comparison...</p>
            ) : error ? (
              <p className="text-red-400">Error: {error}</p>
            ) : (
              <ComparisonView trades={trades} />
            )}
          </>
        )}
      </main>
    </div>
  );
}
