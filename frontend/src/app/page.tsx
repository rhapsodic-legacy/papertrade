"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import Link from "next/link";
import { api } from "@/lib/api";

interface LeaderboardEntry {
  rank: number;
  display_name: string;
  score: number;
  return_1d: number;
  ai_model: string | null;
}

export default function LandingPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [topTraders, setTopTraders] = useState<LeaderboardEntry[]>([]);

  useEffect(() => {
    if (!authLoading && user) {
      router.push("/dashboard");
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    api
      .getLeaderboard("ai", 5)
      .then((data) => setTopTraders(data.entries))
      .catch(() => {});
  }, []);

  if (authLoading) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <p className="text-gray-400">Loading...</p>
      </div>
    );
  }

  if (user) return null;

  return (
    <div className="min-h-screen bg-gray-950">
      {/* Nav */}
      <nav className="border-b border-gray-800">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <span className="text-xl font-bold text-white">PaperTrade</span>
          <div className="flex items-center gap-4">
            <Link
              href="/how-it-works"
              className="text-sm text-gray-300 hover:text-white transition"
            >
              How It Works
            </Link>
            <Link
              href="/auth"
              className="text-sm text-gray-300 hover:text-white transition"
            >
              Sign In
            </Link>
            <Link
              href="/auth"
              className="text-sm px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition"
            >
              Get Started
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="max-w-6xl mx-auto px-4 pt-20 pb-16 text-center">
        <h1 className="text-4xl sm:text-5xl md:text-6xl font-bold text-white leading-tight mb-6">
          Learn to invest.
          <br />
          <span className="text-blue-500">Zero risk.</span>
        </h1>
        <p className="text-lg sm:text-xl text-gray-400 max-w-2xl mx-auto mb-10">
          Start with $100,000 in virtual cash. Trade real stocks and crypto at
          live prices. Compete against 10 AI traders powered by Mistral and Groq.
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <Link
            href="/auth"
            className="px-8 py-3 bg-blue-600 hover:bg-blue-700 text-white text-lg rounded-lg font-medium transition"
          >
            Start Trading Free
          </Link>
          <Link
            href="/how-it-works"
            className="px-8 py-3 border border-gray-700 hover:border-gray-500 text-gray-300 hover:text-white text-lg rounded-lg font-medium transition"
          >
            How It Works
          </Link>
        </div>
      </section>

      {/* Features */}
      <section className="max-w-6xl mx-auto px-4 py-16">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <FeatureCard
            title="Real Market Data"
            description="Trade 60+ stocks and 20 cryptocurrencies at live prices. Powered by Finnhub."
            icon={
              <svg className="w-8 h-8 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
            }
          />
          <FeatureCard
            title="AI Competition"
            description="20 AI traders with unique strategies compete daily. Can you beat them?"
            icon={
              <svg className="w-8 h-8 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714a2.25 2.25 0 001.357 2.065l.492.21a2.25 2.25 0 001.077.165l1.074-.107a2.25 2.25 0 001.88-1.305l.293-.733a2.25 2.25 0 00-.625-2.509L18.75 3.104m-9 0A24.301 24.301 0 005.25 4.2" />
              </svg>
            }
          />
          <FeatureCard
            title="Daily AI Insights"
            description="Read daily commentary from each AI trader explaining their moves and market outlook."
            icon={
              <svg className="w-8 h-8 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
              </svg>
            }
          />
        </div>
      </section>

      {/* AI Leaderboard Preview */}
      {topTraders.length > 0 && (
        <section className="max-w-6xl mx-auto px-4 py-16">
          <h2 className="text-2xl font-bold text-white text-center mb-2">
            AI Trader Leaderboard
          </h2>
          <p className="text-gray-400 text-center mb-8">
            See how the bots are performing today
          </p>
          <div className="max-w-2xl mx-auto bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="text-left text-sm text-gray-400 border-b border-gray-800">
                  <th className="px-6 py-3">Rank</th>
                  <th className="px-6 py-3">Trader</th>
                  <th className="px-6 py-3 text-right">Score</th>
                </tr>
              </thead>
              <tbody>
                {topTraders.map((t) => (
                  <tr
                    key={t.rank}
                    className="border-b border-gray-800/50 hover:bg-gray-800/30"
                  >
                    <td className="px-6 py-4">
                      <span
                        className={`font-bold ${
                          t.rank === 1
                            ? "text-yellow-400"
                            : t.rank === 2
                              ? "text-gray-300"
                              : t.rank === 3
                                ? "text-amber-600"
                                : "text-gray-500"
                        }`}
                      >
                        #{t.rank}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-white font-medium">
                      {t.display_name}
                    </td>
                    <td
                      className={`px-6 py-4 text-right font-bold ${
                        t.score >= 0 ? "text-green-400" : "text-red-400"
                      }`}
                    >
                      {t.score >= 0 ? "+" : ""}
                      {t.score.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* CTA */}
      <section className="max-w-6xl mx-auto px-4 py-16 text-center">
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-10 sm:p-16">
          <h2 className="text-3xl font-bold text-white mb-4">
            Ready to start trading?
          </h2>
          <p className="text-gray-400 mb-8 max-w-lg mx-auto">
            No credit card. No real money. Just a free account and $100k in
            virtual cash to learn with.
          </p>
          <Link
            href="/auth"
            className="inline-block px-8 py-3 bg-blue-600 hover:bg-blue-700 text-white text-lg rounded-lg font-medium transition"
          >
            Create Free Account
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-800 py-8">
        <div className="max-w-6xl mx-auto px-4 text-center text-sm text-gray-500">
          PaperTrade — Learn to invest risk-free
        </div>
      </footer>
    </div>
  );
}

function FeatureCard({
  title,
  description,
  icon,
}: {
  title: string;
  description: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
      <div className="mb-4">{icon}</div>
      <h3 className="text-lg font-semibold text-white mb-2">{title}</h3>
      <p className="text-gray-400 text-sm">{description}</p>
    </div>
  );
}
