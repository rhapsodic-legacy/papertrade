"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import Navbar from "@/components/Navbar";

type Module = {
  key: string;
  label: string;
  description: string;
  icon: string;
  color: string;
};

const RISK_LEVELS = [
  {
    key: "low",
    label: "Conservative",
    desc: "Tight stops, smaller positions, longer holds",
    color: "border-green-500 bg-green-900/20 text-green-400",
  },
  {
    key: "medium",
    label: "Balanced",
    desc: "Moderate risk/reward, diversified approach",
    color: "border-yellow-500 bg-yellow-900/20 text-yellow-400",
  },
  {
    key: "high",
    label: "Aggressive",
    desc: "Wider stops, larger bets, momentum-focused",
    color: "border-red-500 bg-red-900/20 text-red-400",
  },
];

const ASSET_OPTIONS = [
  { key: "both", label: "Stocks & Crypto", desc: "Trade everything" },
  { key: "stocks", label: "Stocks Only", desc: "No crypto positions" },
  { key: "crypto", label: "Crypto Only", desc: "No stock positions" },
];

const MODULE_COLORS: Record<string, string> = {
  red: "border-red-700 bg-red-900/20",
  blue: "border-blue-700 bg-blue-900/20",
  green: "border-green-700 bg-green-900/20",
  yellow: "border-yellow-700 bg-yellow-900/20",
  purple: "border-purple-700 bg-purple-900/20",
  orange: "border-orange-700 bg-orange-900/20",
  cyan: "border-cyan-700 bg-cyan-900/20",
  pink: "border-pink-700 bg-pink-900/20",
  gray: "border-gray-700 bg-gray-900/20",
};

export default function CreateTraderPage() {
  const { user } = useAuth();
  const router = useRouter();

  const [modules, setModules] = useState<Module[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Form state
  const [name, setName] = useState("");
  const [strategyPrompt, setStrategyPrompt] = useState("");
  const [riskLevel, setRiskLevel] = useState("medium");
  const [assetFocus, setAssetFocus] = useState("both");
  const [selectedModules, setSelectedModules] = useState<string[]>([]);

  useEffect(() => {
    if (!user) {
      router.push("/auth/signin");
      return;
    }
    api
      .getCustomTraderModules()
      .then((res) => setModules(res.modules))
      .catch(() => setError("Failed to load modules"))
      .finally(() => setLoading(false));
  }, [user, router]);

  const toggleModule = (key: string) => {
    setSelectedModules((prev) =>
      prev.includes(key)
        ? prev.filter((m) => m !== key)
        : prev.length < 6
          ? [...prev, key]
          : prev
    );
  };

  const handleSubmit = async () => {
    setError("");
    if (name.length < 3) {
      setError("Name must be at least 3 characters");
      return;
    }
    if (strategyPrompt.length < 10) {
      setError("Strategy prompt must be at least 10 characters");
      return;
    }
    if (selectedModules.length === 0) {
      setError("Select at least 1 data module");
      return;
    }

    setSubmitting(true);
    try {
      await api.createCustomTrader({
        name,
        strategy_prompt: strategyPrompt,
        risk_level: riskLevel,
        asset_focus: assetFocus,
        toolkit_modules: selectedModules,
      });
      router.push("/my-traders");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create trader");
    } finally {
      setSubmitting(false);
    }
  };

  if (!user) return null;

  return (
    <div className="min-h-screen bg-black text-white">
      <Navbar />
      <div className="max-w-3xl mx-auto px-4 py-8">
        <div className="mb-8">
          <h1 className="text-2xl font-bold">Create AI Trader</h1>
          <p className="text-gray-400 mt-1">
            Build a custom AI that trades with your strategy and competes on the
            leaderboard.
          </p>
        </div>

        {loading ? (
          <div className="text-gray-500 text-center py-12">Loading...</div>
        ) : (
          <div className="space-y-8">
            {/* Name */}
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Trader Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={30}
                placeholder="e.g. Momentum Mike"
                className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-white placeholder-gray-600 focus:border-blue-500 focus:outline-none"
              />
              <p className="text-xs text-gray-600 mt-1">
                {name.length}/30 characters
              </p>
            </div>

            {/* Strategy Prompt */}
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Strategy Prompt
              </label>
              <p className="text-xs text-gray-500 mb-2">
                Describe your trading strategy in natural language. The AI will
                follow these instructions when making buy/sell decisions.
              </p>
              <textarea
                value={strategyPrompt}
                onChange={(e) => setStrategyPrompt(e.target.value)}
                maxLength={2000}
                rows={5}
                placeholder="e.g. Focus on high-momentum tech stocks. Buy when RSI crosses above 30 from oversold territory. Take profits at +15%. Avoid holding through earnings unless conviction is very high. Allocate 20-30% to top crypto by market cap as a hedge."
                className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-white placeholder-gray-600 focus:border-blue-500 focus:outline-none resize-none"
              />
              <p className="text-xs text-gray-600 mt-1">
                {strategyPrompt.length}/2000 characters
              </p>
            </div>

            {/* Risk Level */}
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-3">
                Risk Level
              </label>
              <div className="grid grid-cols-3 gap-3">
                {RISK_LEVELS.map((r) => (
                  <button
                    key={r.key}
                    onClick={() => setRiskLevel(r.key)}
                    className={`border rounded-lg p-3 text-left transition ${
                      riskLevel === r.key
                        ? r.color + " ring-1 ring-current"
                        : "border-gray-700 bg-gray-900/50 text-gray-400 hover:border-gray-600"
                    }`}
                  >
                    <div className="text-sm font-medium">{r.label}</div>
                    <div className="text-xs mt-1 opacity-70">{r.desc}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* Asset Focus */}
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-3">
                Asset Focus
              </label>
              <div className="grid grid-cols-3 gap-3">
                {ASSET_OPTIONS.map((a) => (
                  <button
                    key={a.key}
                    onClick={() => setAssetFocus(a.key)}
                    className={`border rounded-lg p-3 text-left transition ${
                      assetFocus === a.key
                        ? "border-blue-500 bg-blue-900/20 text-blue-400 ring-1 ring-blue-500"
                        : "border-gray-700 bg-gray-900/50 text-gray-400 hover:border-gray-600"
                    }`}
                  >
                    <div className="text-sm font-medium">{a.label}</div>
                    <div className="text-xs mt-1 opacity-70">{a.desc}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* Data Modules */}
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Data Modules ({selectedModules.length}/6 selected)
              </label>
              <p className="text-xs text-gray-500 mb-3">
                Choose what market data your AI receives each day. More modules
                = more context, but the AI must process more information.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {modules.map((m) => {
                  const selected = selectedModules.includes(m.key);
                  const colorClass =
                    MODULE_COLORS[m.color] || MODULE_COLORS.gray;
                  return (
                    <button
                      key={m.key}
                      onClick={() => toggleModule(m.key)}
                      className={`border rounded-lg p-3 text-left transition ${
                        selected
                          ? colorClass + " ring-1 ring-current"
                          : "border-gray-700 bg-gray-900/50 text-gray-400 hover:border-gray-600"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {m.icon && <span className="text-lg">{m.icon}</span>}
                        <span className="text-sm font-medium">{m.label}</span>
                      </div>
                      <p className="text-xs mt-1 opacity-70">{m.description}</p>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="bg-red-900/30 border border-red-800 text-red-400 px-4 py-3 rounded-lg text-sm">
                {error}
              </div>
            )}

            {/* Submit */}
            <div className="flex items-center gap-4 pt-2">
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white px-6 py-3 rounded-lg font-medium transition"
              >
                {submitting ? "Creating..." : "Create AI Trader"}
              </button>
              <button
                onClick={() => router.back()}
                className="text-gray-400 hover:text-white transition px-4 py-3"
              >
                Cancel
              </button>
            </div>

            <p className="text-xs text-gray-600">
              Your AI trader starts with $100,000 in virtual cash and will begin
              trading at the next daily pipeline run (5 PM ET). It competes on
              the same leaderboard as the 20 built-in AI traders. Max 3 custom
              traders per account.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
