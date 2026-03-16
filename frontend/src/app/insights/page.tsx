"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
  commentary: string;
  trades_summary: TradeSummary[];
  date: string;
}

const PERSONALITY_COLORS: Record<string, string> = {
  vanilla: "border-gray-500",
  steady_eddie: "border-blue-500",
  yolo_bot: "border-red-500",
  contrarian_carl: "border-purple-500",
  crypto_chad: "border-orange-500",
};

const PERSONALITY_BADGES: Record<string, string> = {
  vanilla: "bg-gray-800 text-gray-300",
  steady_eddie: "bg-blue-900/50 text-blue-300",
  yolo_bot: "bg-red-900/50 text-red-300",
  contrarian_carl: "bg-purple-900/50 text-purple-300",
  crypto_chad: "bg-orange-900/50 text-orange-300",
};

const MODEL_LABELS: Record<string, string> = {
  "gemini-flash": "Flash",
  "gemini-pro": "Pro",
};

export default function InsightsPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [entries, setEntries] = useState<CommentaryEntry[]>([]);
  const [dates, setDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!authLoading && !user) router.push("/auth");
  }, [user, authLoading, router]);

  // Load available dates
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
    }
  }, [user]);

  // Load commentary for selected date
  useEffect(() => {
    if (user && selectedDate) {
      setLoading(true);
      api
        .getCommentary(selectedDate, 20)
        .then((data) => setEntries(data.entries))
        .catch(console.error)
        .finally(() => setLoading(false));
    }
  }, [user, selectedDate]);

  if (authLoading || !user) return null;

  const formatDateLabel = (dateStr: string) => {
    const d = new Date(dateStr + "T12:00:00");
    return d.toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  };

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-4xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-white">AI Insights</h1>
          {dates.length > 0 && (
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

        {loading ? (
          <p className="text-gray-400">Loading commentary...</p>
        ) : entries.length === 0 ? (
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-8 text-center">
            <p className="text-gray-400 text-lg mb-2">
              No AI commentary yet
            </p>
            <p className="text-gray-500 text-sm">
              Commentary is generated daily after AI traders make their moves.
              Check back after the next trading session!
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {entries.map((entry, i) => (
              <article
                key={`${entry.display_name}-${i}`}
                className={`bg-gray-900 rounded-lg border-l-4 ${
                  PERSONALITY_COLORS[entry.personality] || "border-gray-500"
                } border border-gray-800 border-l-4 p-6`}
              >
                {/* Header */}
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <h2 className="text-lg font-semibold text-white">
                      {entry.display_name}
                    </h2>
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full ${
                        PERSONALITY_BADGES[entry.personality] ||
                        "bg-gray-800 text-gray-300"
                      }`}
                    >
                      {MODEL_LABELS[entry.model] || entry.model}
                    </span>
                  </div>
                </div>

                {/* Commentary */}
                <div className="text-gray-300 text-sm leading-relaxed whitespace-pre-line mb-4">
                  {entry.commentary}
                </div>

                {/* Trades Summary */}
                {entry.trades_summary.length > 0 && (
                  <div className="border-t border-gray-800 pt-3 mt-3">
                    <p className="text-xs text-gray-500 mb-2">
                      Trades executed:
                    </p>
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
              </article>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
