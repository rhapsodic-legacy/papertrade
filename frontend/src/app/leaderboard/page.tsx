"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import Navbar from "@/components/Navbar";

interface LeaderboardEntry {
  rank: number;
  display_name: string;
  score: number;
  return_1d: number;
  return_7d: number;
  return_30d: number;
  return_90d: number;
  is_ai: boolean;
  ai_model: string | null;
}

function formatReturn(val: number) {
  const sign = val > 0 ? "+" : "";
  return `${sign}${val.toFixed(2)}%`;
}

export default function LeaderboardPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [category, setCategory] = useState<"human" | "ai">("human");
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [userEntry, setUserEntry] = useState<LeaderboardEntry | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!authLoading && !user) router.push("/auth");
  }, [user, authLoading, router]);

  useEffect(() => {
    if (user) {
      setLoading(true);
      api
        .getLeaderboard(category)
        .then((data) => {
          setEntries(data.entries);
          setUserEntry(data.user_entry);
        })
        .catch(console.error)
        .finally(() => setLoading(false));
    }
  }, [user, category]);

  if (authLoading || !user) return null;

  const returnColor = (val: number) =>
    val >= 0 ? "text-green-400" : "text-red-400";

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-5xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-white mb-6">Leaderboard</h1>

        {/* Tab Switcher */}
        <div className="flex mb-6">
          <button
            onClick={() => setCategory("human")}
            className={`flex-1 py-2 text-center text-sm font-medium border-b-2 transition ${
              category === "human"
                ? "border-blue-500 text-white"
                : "border-transparent text-gray-400 hover:text-white"
            }`}
          >
            Traders
          </button>
          <button
            onClick={() => setCategory("ai")}
            className={`flex-1 py-2 text-center text-sm font-medium border-b-2 transition ${
              category === "ai"
                ? "border-blue-500 text-white"
                : "border-transparent text-gray-400 hover:text-white"
            }`}
          >
            AI Traders
          </button>
        </div>

        {/* User Rank Banner */}
        {category === "human" && userEntry && (
          <div className="bg-blue-900/30 border border-blue-800 rounded-lg px-6 py-4 mb-4 flex items-center justify-between">
            <div className="text-white">
              <span className="text-gray-400 text-sm">Your Rank</span>
              <span className="ml-3 text-xl font-bold">#{userEntry.rank}</span>
            </div>
            <div className="text-right">
              <span className="text-gray-400 text-sm mr-3">Score</span>
              <span className={`text-xl font-bold ${returnColor(userEntry.score)}`}>
                {userEntry.score > 0 ? "+" : ""}
                {userEntry.score.toFixed(2)}
              </span>
            </div>
          </div>
        )}

        {/* Leaderboard Table */}
        <div className="bg-gray-900 rounded-lg border border-gray-800">
          {loading ? (
            <p className="p-6 text-gray-400">Loading...</p>
          ) : entries.length === 0 ? (
            <p className="p-6 text-center text-gray-400">
              {category === "ai"
                ? "No AI traders yet. Coming soon!"
                : "No traders yet. Be the first!"}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-sm text-gray-400 border-b border-gray-800">
                    <th className="px-4 py-3">Rank</th>
                    <th className="px-4 py-3">Trader</th>
                    {category === "ai" && (
                      <th className="px-4 py-3">Model</th>
                    )}
                    <th className="px-4 py-3 text-right">Score</th>
                    <th className="px-4 py-3 text-right">1D</th>
                    <th className="px-4 py-3 text-right">7D</th>
                    <th className="px-4 py-3 text-right">30D</th>
                    <th className="px-4 py-3 text-right">90D</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((entry) => {
                    const isCurrentUser =
                      category === "human" &&
                      userEntry &&
                      entry.rank === userEntry.rank;
                    return (
                      <tr
                        key={entry.rank}
                        className={`border-b border-gray-800/50 ${
                          isCurrentUser
                            ? "bg-blue-900/20"
                            : "hover:bg-gray-800/30"
                        }`}
                      >
                        <td className="px-4 py-4">
                          <span
                            className={`font-bold ${
                              entry.rank === 1
                                ? "text-yellow-400"
                                : entry.rank === 2
                                  ? "text-gray-300"
                                  : entry.rank === 3
                                    ? "text-amber-600"
                                    : "text-gray-500"
                            }`}
                          >
                            #{entry.rank}
                          </span>
                        </td>
                        <td className="px-4 py-4 font-medium text-white">
                          {entry.display_name}
                        </td>
                        {category === "ai" && (
                          <td className="px-4 py-4 text-gray-400 text-sm">
                            {entry.ai_model || "—"}
                          </td>
                        )}
                        <td
                          className={`px-4 py-4 text-right font-bold ${returnColor(
                            entry.score
                          )}`}
                        >
                          {entry.score > 0 ? "+" : ""}
                          {entry.score.toFixed(2)}
                        </td>
                        <td
                          className={`px-4 py-4 text-right text-sm ${returnColor(
                            entry.return_1d
                          )}`}
                        >
                          {formatReturn(entry.return_1d)}
                        </td>
                        <td
                          className={`px-4 py-4 text-right text-sm ${returnColor(
                            entry.return_7d
                          )}`}
                        >
                          {formatReturn(entry.return_7d)}
                        </td>
                        <td
                          className={`px-4 py-4 text-right text-sm ${returnColor(
                            entry.return_30d
                          )}`}
                        >
                          {formatReturn(entry.return_30d)}
                        </td>
                        <td
                          className={`px-4 py-4 text-right text-sm ${returnColor(
                            entry.return_90d
                          )}`}
                        >
                          {formatReturn(entry.return_90d)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
