"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import Navbar from "@/components/Navbar";

interface TradeSummary {
  symbol: string;
  side: string;
  quantity: number;
  price: number;
}

interface CommentaryEntry {
  display_name: string;
  personality: string;
  model: string;
  headline: string;
  commentary: string;
  trades_summary: TradeSummary[];
  date: string;
}

interface AiTrader {
  id: string;
  display_name: string;
  ai_model: string;
  personality: string;
}

const PERSONALITY_COLORS: Record<string, string> = {
  vanilla: "border-l-gray-500",
  steady_eddie: "border-l-blue-500",
  yolo_bot: "border-l-red-500",
  contrarian_carl: "border-l-purple-500",
  crypto_chad: "border-l-orange-500",
};

const PERSONALITY_BADGES: Record<string, string> = {
  vanilla: "bg-gray-800 text-gray-300",
  steady_eddie: "bg-blue-900/50 text-blue-300",
  yolo_bot: "bg-red-900/50 text-red-300",
  contrarian_carl: "bg-purple-900/50 text-purple-300",
  crypto_chad: "bg-orange-900/50 text-orange-300",
};

const PERSONALITY_LABELS: Record<string, string> = {
  vanilla: "Vanilla",
  steady_eddie: "Steady Eddie",
  yolo_bot: "YOLO Bot",
  contrarian_carl: "Contrarian Carl",
  crypto_chad: "Crypto Chad",
};

const MODEL_LABELS: Record<string, string> = {
  "gemini-flash": "Gemini Flash",
  "gemini-pro": "Gemini Pro",
  mistral: "Mistral",
  llama: "Llama",
};

type ViewMode = "daily" | "trader-history";

export default function InsightsPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [entries, setEntries] = useState<CommentaryEntry[]>([]);
  const [dates, setDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  // Trader history mode
  const [viewMode, setViewMode] = useState<ViewMode>("daily");
  const [traders, setTraders] = useState<AiTrader[]>([]);
  const [selectedTrader, setSelectedTrader] = useState<AiTrader | null>(null);
  const [traderHistory, setTraderHistory] = useState<CommentaryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyExpanded, setHistoryExpanded] = useState<number | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.push("/auth");
  }, [user, authLoading, router]);

  // Load available dates and trader list
  useEffect(() => {
    if (user) {
      api
        .getCommentaryDates()
        .then((data) => {
          setDates(data.dates);
          if (data.dates.length > 0 && !selectedDate) {
            setSelectedDate(data.dates[0]);
          } else if (data.dates.length === 0) {
            setLoading(false);
          }
        })
        .catch((err) => {
          console.error(err);
          setLoading(false);
        });

      api.getAiTraders().then((data) => setTraders(data.traders)).catch(console.error);
    }
  }, [user]);

  // Load commentary for selected date
  useEffect(() => {
    if (user && selectedDate && viewMode === "daily") {
      setLoading(true);
      setExpandedIndex(null);
      api
        .getCommentary(selectedDate, 50)
        .then((data) => setEntries(data.entries))
        .catch(console.error)
        .finally(() => setLoading(false));
    }
  }, [user, selectedDate, viewMode]);

  // Load trader history
  useEffect(() => {
    if (selectedTrader && viewMode === "trader-history") {
      setHistoryLoading(true);
      setHistoryExpanded(null);
      api
        .getTraderCommentary(selectedTrader.id, 30)
        .then((data) => setTraderHistory(data.entries))
        .catch(console.error)
        .finally(() => setHistoryLoading(false));
    }
  }, [selectedTrader, viewMode]);

  if (authLoading || !user) return null;

  const formatDateLabel = (dateStr: string) => {
    const d = new Date(dateStr + "T12:00:00");
    return d.toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  };

  const handleTraderClick = (trader: AiTrader) => {
    setSelectedTrader(trader);
    setViewMode("trader-history");
  };

  const handleBackToDaily = () => {
    setViewMode("daily");
    setSelectedTrader(null);
    setTraderHistory([]);
  };

  // Group entries by personality for the daily view
  const groupedByPersonality = entries.reduce<
    Record<string, CommentaryEntry[]>
  >((acc, entry) => {
    const key = entry.personality || "vanilla";
    if (!acc[key]) acc[key] = [];
    acc[key].push(entry);
    return acc;
  }, {});

  const personalityOrder = [
    "vanilla",
    "steady_eddie",
    "yolo_bot",
    "contrarian_carl",
    "crypto_chad",
  ];

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-4xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            {viewMode === "trader-history" && (
              <button
                onClick={handleBackToDaily}
                className="text-gray-400 hover:text-white transition"
              >
                <svg
                  className="w-5 h-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M15 19l-7-7 7-7"
                  />
                </svg>
              </button>
            )}
            <h1 className="text-2xl font-bold text-white">
              {viewMode === "daily"
                ? "AI Insights"
                : selectedTrader?.display_name || "Trader History"}
            </h1>
          </div>
          {viewMode === "daily" && dates.length > 0 && (
            <select
              value={selectedDate || ""}
              onChange={(e) => setSelectedDate(e.target.value)}
              className="bg-gray-900 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:border-blue-500 focus:outline-none"
            >
              {dates.map((d) => (
                <option key={d} value={d}>
                  {formatDateLabel(d)}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Daily View */}
        {viewMode === "daily" && (
          <>
            {loading ? (
              <p className="text-gray-400">Loading commentary...</p>
            ) : entries.length === 0 ? (
              <div className="bg-gray-900 rounded-lg border border-gray-800 p-8 text-center">
                <p className="text-gray-400 text-lg mb-2">
                  No AI commentary yet
                </p>
                <p className="text-gray-500 text-sm">
                  Commentary is generated daily after AI traders make their
                  moves. Check back after the next trading session!
                </p>
              </div>
            ) : (
              <div className="space-y-8">
                {personalityOrder.map((personalityKey) => {
                  const group = groupedByPersonality[personalityKey];
                  if (!group || group.length === 0) return null;

                  return (
                    <div key={personalityKey}>
                      {/* Personality group header */}
                      <div className="flex items-center gap-2 mb-3">
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                            PERSONALITY_BADGES[personalityKey] ||
                            "bg-gray-800 text-gray-300"
                          }`}
                        >
                          {PERSONALITY_LABELS[personalityKey] || personalityKey}
                        </span>
                        <span className="text-xs text-gray-600">
                          {group.length} model{group.length !== 1 ? "s" : ""}
                        </span>
                      </div>

                      {/* Accordion items */}
                      <div className="space-y-2">
                        {group.map((entry, i) => {
                          const globalIndex = entries.indexOf(entry);
                          const isOpen = expandedIndex === globalIndex;
                          const traderId = traders.find(
                            (t) => t.display_name === entry.display_name
                          )?.id;

                          return (
                            <AccordionCard
                              key={`${entry.display_name}-${i}`}
                              entry={entry}
                              isOpen={isOpen}
                              onToggle={() =>
                                setExpandedIndex(isOpen ? null : globalIndex)
                              }
                              onViewHistory={
                                traderId
                                  ? () => {
                                      const trader = traders.find(
                                        (t) => t.id === traderId
                                      );
                                      if (trader) handleTraderClick(trader);
                                    }
                                  : undefined
                              }
                              traderProfileLink={
                                traderId
                                  ? `/traders/${traderId}`
                                  : undefined
                              }
                            />
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}

        {/* Trader History View */}
        {viewMode === "trader-history" && (
          <>
            {selectedTrader && (
              <div className="flex items-center gap-3 mb-6">
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    PERSONALITY_BADGES[selectedTrader.personality] ||
                    "bg-gray-800 text-gray-300"
                  }`}
                >
                  {PERSONALITY_LABELS[selectedTrader.personality] ||
                    selectedTrader.personality}
                </span>
                <span className="text-xs text-gray-500">
                  {MODEL_LABELS[selectedTrader.ai_model] ||
                    selectedTrader.ai_model}
                </span>
                <Link
                  href={`/traders/${selectedTrader.id}`}
                  className="text-xs text-blue-400 hover:text-blue-300 transition ml-auto"
                >
                  View Portfolio
                </Link>
              </div>
            )}

            {historyLoading ? (
              <p className="text-gray-400">Loading history...</p>
            ) : traderHistory.length === 0 ? (
              <div className="bg-gray-900 rounded-lg border border-gray-800 p-8 text-center">
                <p className="text-gray-400">
                  No commentary history for this trader yet.
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {traderHistory.map((entry, i) => (
                  <AccordionCard
                    key={`${entry.date}-${i}`}
                    entry={entry}
                    isOpen={historyExpanded === i}
                    onToggle={() =>
                      setHistoryExpanded(historyExpanded === i ? null : i)
                    }
                    showDate
                  />
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function AccordionCard({
  entry,
  isOpen,
  onToggle,
  onViewHistory,
  traderProfileLink,
  showDate,
}: {
  entry: CommentaryEntry;
  isOpen: boolean;
  onToggle: () => void;
  onViewHistory?: () => void;
  traderProfileLink?: string;
  showDate?: boolean;
}) {
  return (
    <div
      className={`bg-gray-900 rounded-lg border border-gray-800 border-l-4 ${
        PERSONALITY_COLORS[entry.personality] || "border-l-gray-500"
      } overflow-hidden transition-all`}
    >
      {/* Collapsed header - always visible */}
      <button
        onClick={onToggle}
        className="w-full text-left px-5 py-4 flex items-start justify-between gap-3 hover:bg-gray-800/30 transition"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-semibold text-white truncate">
              {showDate
                ? formatDateShort(entry.date)
                : MODEL_LABELS[entry.model] || entry.model}
            </span>
            {entry.trades_summary.length > 0 && (
              <span className="text-xs text-gray-500">
                {entry.trades_summary.length} trade
                {entry.trades_summary.length !== 1 ? "s" : ""}
              </span>
            )}
          </div>
          <p className="text-sm text-gray-400 truncate">
            {entry.headline || entry.commentary.slice(0, 120)}
          </p>
        </div>
        <svg
          className={`w-4 h-4 text-gray-500 shrink-0 mt-1 transition-transform ${
            isOpen ? "rotate-180" : ""
          }`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </button>

      {/* Expanded content */}
      {isOpen && (
        <div className="px-5 pb-5 border-t border-gray-800/50">
          <div className="text-gray-300 text-sm leading-relaxed whitespace-pre-line mt-4 mb-4">
            {entry.commentary}
          </div>

          {/* Trades */}
          {entry.trades_summary.length > 0 && (
            <div className="border-t border-gray-800 pt-3 mt-3">
              <p className="text-xs text-gray-500 mb-2">Trades executed:</p>
              <div className="flex flex-wrap gap-2">
                {entry.trades_summary.map((t, j) => (
                  <span
                    key={j}
                    className={`text-xs px-2 py-1 rounded ${
                      t.side === "buy"
                        ? "bg-green-900/30 text-green-400"
                        : "bg-red-900/30 text-red-400"
                    }`}
                  >
                    {t.side.toUpperCase()} {t.quantity} {t.symbol} @{" "}
                    {formatCurrency(t.price)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Action links */}
          {(onViewHistory || traderProfileLink) && (
            <div className="flex items-center gap-4 mt-4 pt-3 border-t border-gray-800">
              {onViewHistory && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onViewHistory();
                  }}
                  className="text-xs text-blue-400 hover:text-blue-300 transition"
                >
                  View past commentary
                </button>
              )}
              {traderProfileLink && (
                <Link
                  href={traderProfileLink}
                  className="text-xs text-gray-400 hover:text-gray-300 transition"
                >
                  View portfolio
                </Link>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatDateShort(dateStr: string) {
  const d = new Date(dateStr + "T12:00:00");
  return d.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}
