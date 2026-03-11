"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import Navbar from "@/components/Navbar";

interface LeaderboardEntry {
  rank: number;
  display_name: string;
  total_portfolio_value: number;
  cash_balance: number;
  invested_value: number;
}

export default function LeaderboardPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!authLoading && !user) router.push("/auth");
  }, [user, authLoading, router]);

  useEffect(() => {
    if (user) {
      api
        .getLeaderboard()
        .then(setEntries)
        .catch(console.error)
        .finally(() => setLoading(false));
    }
  }, [user]);

  if (authLoading || !user) return null;

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-4xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-white mb-6">Leaderboard</h1>

        <div className="bg-gray-900 rounded-lg border border-gray-800">
          {loading ? (
            <p className="p-6 text-gray-400">Loading...</p>
          ) : entries.length === 0 ? (
            <p className="p-6 text-center text-gray-400">
              No traders yet. Be the first!
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-sm text-gray-400 border-b border-gray-800">
                    <th className="px-6 py-3">Rank</th>
                    <th className="px-6 py-3">Trader</th>
                    <th className="px-6 py-3 text-right">Portfolio Value</th>
                    <th className="px-6 py-3 text-right">Invested</th>
                    <th className="px-6 py-3 text-right">Cash</th>
                    <th className="px-6 py-3 text-right">Return</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((entry) => {
                    const returnPct =
                      ((entry.total_portfolio_value - 100000) / 100000) * 100;
                    return (
                      <tr
                        key={entry.rank}
                        className="border-b border-gray-800/50 hover:bg-gray-800/30"
                      >
                        <td className="px-6 py-4">
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
                        <td className="px-6 py-4 font-medium text-white">
                          {entry.display_name}
                        </td>
                        <td className="px-6 py-4 text-right text-white font-medium">
                          {formatCurrency(entry.total_portfolio_value)}
                        </td>
                        <td className="px-6 py-4 text-right text-gray-300">
                          {formatCurrency(entry.invested_value)}
                        </td>
                        <td className="px-6 py-4 text-right text-gray-300">
                          {formatCurrency(entry.cash_balance)}
                        </td>
                        <td
                          className={`px-6 py-4 text-right font-medium ${
                            returnPct >= 0
                              ? "text-green-400"
                              : "text-red-400"
                          }`}
                        >
                          {returnPct > 0 ? "+" : ""}
                          {returnPct.toFixed(2)}%
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
