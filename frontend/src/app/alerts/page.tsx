"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import Navbar from "@/components/Navbar";

type AlertRule = {
  id: string;
  type: string;
  config: Record<string, unknown>;
  active: boolean;
  triggered_at: string | null;
  created_at: string;
};

type Notification = {
  id: string;
  type: string;
  title: string;
  message: string;
  metadata: Record<string, unknown>;
  read: boolean;
  created_at: string;
};

const ALERT_TYPE_LABELS: Record<string, string> = {
  price_above: "Price Above",
  price_below: "Price Below",
  ai_follow: "Follow AI Trader",
  portfolio_pnl: "Position P&L",
};

const ALERT_TYPE_COLORS: Record<string, string> = {
  price_above: "bg-green-900/40 text-green-400 border-green-800",
  price_below: "bg-red-900/40 text-red-400 border-red-800",
  ai_follow: "bg-blue-900/40 text-blue-400 border-blue-800",
  portfolio_pnl: "bg-purple-900/40 text-purple-400 border-purple-800",
};

function AlertRuleCard({
  rule,
  onDelete,
}: {
  rule: AlertRule;
  onDelete: (id: string) => void;
}) {
  const config = rule.config;
  const typeColor = ALERT_TYPE_COLORS[rule.type] || "bg-gray-800 text-gray-400 border-gray-700";

  let description = "";
  if (rule.type === "price_above") {
    description = `Notify when ${config.symbol} goes above $${Number(config.target_price).toLocaleString()}`;
  } else if (rule.type === "price_below") {
    description = `Notify when ${config.symbol} drops below $${Number(config.target_price).toLocaleString()}`;
  } else if (rule.type === "ai_follow") {
    description = `Notify when ${config.trader_name} makes a trade`;
  } else if (rule.type === "portfolio_pnl") {
    const dir = config.direction === "above" ? "gains" : "loses";
    description = `Notify when ${config.symbol} ${dir} ${config.threshold_pct}%`;
  }

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 flex items-start justify-between gap-4">
      <div className="flex-1">
        <div className="flex items-center gap-2 mb-2">
          <span className={`text-xs font-medium px-2 py-0.5 rounded border ${typeColor}`}>
            {ALERT_TYPE_LABELS[rule.type] || rule.type}
          </span>
          {!rule.active && (
            <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">
              {rule.triggered_at ? "Triggered" : "Inactive"}
            </span>
          )}
        </div>
        <p className="text-sm text-gray-300">{description}</p>
        <p className="text-xs text-gray-500 mt-1">
          Created {new Date(rule.created_at).toLocaleDateString()}
          {rule.triggered_at && (
            <> &middot; Triggered {new Date(rule.triggered_at).toLocaleDateString()}</>
          )}
        </p>
      </div>
      <button
        onClick={() => onDelete(rule.id)}
        className="text-gray-500 hover:text-red-400 transition p-1"
        aria-label="Delete alert"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
      </button>
    </div>
  );
}

function CreateAlertForm({
  onCreated,
  aiTraders,
}: {
  onCreated: () => void;
  aiTraders: { id: string; display_name: string }[];
}) {
  const [alertType, setAlertType] = useState("price_above");
  const [symbol, setSymbol] = useState("");
  const [targetPrice, setTargetPrice] = useState("");
  const [traderName, setTraderName] = useState(aiTraders[0]?.display_name || "");
  const [thresholdPct, setThresholdPct] = useState("");
  const [direction, setDirection] = useState("above");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (alertType === "ai_follow" && aiTraders.length > 0 && !traderName) {
      setTraderName(aiTraders[0].display_name);
    }
  }, [alertType, aiTraders, traderName]);

  const handleCreate = async () => {
    setError("");
    setCreating(true);
    try {
      let config: Record<string, unknown> = {};
      if (alertType === "price_above" || alertType === "price_below") {
        if (!symbol.trim()) throw new Error("Symbol is required");
        if (!targetPrice || isNaN(Number(targetPrice))) throw new Error("Valid target price is required");
        config = { symbol: symbol.toUpperCase(), target_price: Number(targetPrice) };
      } else if (alertType === "ai_follow") {
        if (!traderName) throw new Error("Select an AI trader");
        config = { trader_name: traderName };
      } else if (alertType === "portfolio_pnl") {
        if (!symbol.trim()) throw new Error("Symbol is required");
        if (!thresholdPct || isNaN(Number(thresholdPct))) throw new Error("Valid threshold is required");
        config = {
          symbol: symbol.toUpperCase(),
          threshold_pct: Number(thresholdPct),
          direction,
        };
      }

      await api.createAlertRule(alertType, config);
      setSymbol("");
      setTargetPrice("");
      setThresholdPct("");
      onCreated();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create alert");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-6">
      <h2 className="text-lg font-semibold text-white mb-4">Create Alert</h2>

      <div className="space-y-4">
        {/* Alert Type */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">Alert Type</label>
          <select
            value={alertType}
            onChange={(e) => setAlertType(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
          >
            <option value="price_above">Price Above — notify when price rises above target</option>
            <option value="price_below">Price Below — notify when price drops below target</option>
            <option value="ai_follow">Follow AI Trader — notify when they trade</option>
            <option value="portfolio_pnl">Position P&L — notify on gain/loss threshold</option>
          </select>
        </div>

        {/* Price alerts */}
        {(alertType === "price_above" || alertType === "price_below") && (
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Symbol</label>
              <input
                type="text"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                placeholder="AAPL"
                className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Target Price ($)</label>
              <input
                type="number"
                value={targetPrice}
                onChange={(e) => setTargetPrice(e.target.value)}
                placeholder="150.00"
                step="0.01"
                className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
        )}

        {/* AI follow */}
        {alertType === "ai_follow" && (
          <div>
            <label className="block text-sm text-gray-400 mb-1">AI Trader</label>
            <select
              value={traderName}
              onChange={(e) => setTraderName(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
            >
              {aiTraders.map((t) => (
                <option key={t.id} value={t.display_name}>
                  {t.display_name}
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-1">
              You&apos;ll get notified each time this AI trader makes a trade, with their reasoning.
            </p>
          </div>
        )}

        {/* Portfolio P&L */}
        {alertType === "portfolio_pnl" && (
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Symbol</label>
              <input
                type="text"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                placeholder="AAPL"
                className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Direction</label>
              <select
                value={direction}
                onChange={(e) => setDirection(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              >
                <option value="above">Gains above</option>
                <option value="below">Drops below</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Threshold (%)</label>
              <input
                type="number"
                value={thresholdPct}
                onChange={(e) => setThresholdPct(e.target.value)}
                placeholder="10"
                step="1"
                className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
        )}

        {error && <p className="text-sm text-red-400">{error}</p>}

        <button
          onClick={handleCreate}
          disabled={creating}
          className="w-full px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-500 disabled:opacity-50 transition"
        >
          {creating ? "Creating..." : "Create Alert"}
        </button>
      </div>
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

export default function AlertsPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [aiTraders, setAiTraders] = useState<{ id: string; display_name: string }[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!authLoading && !user) router.push("/auth");
  }, [user, authLoading, router]);

  const fetchData = () => {
    if (!user) return;
    setLoading(true);
    Promise.all([
      api.getAlertRules(),
      api.getNotifications(50),
      api.getAiTraders(),
    ])
      .then(([rulesRes, notifsRes, tradersRes]) => {
        setRules(rulesRes.rules);
        setNotifications(notifsRes.notifications);
        setAiTraders(tradersRes.traders);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const handleDelete = async (ruleId: string) => {
    await api.deleteAlertRule(ruleId);
    setRules((prev) => prev.filter((r) => r.id !== ruleId));
  };

  const handleMarkAllRead = async () => {
    await api.markAllNotificationsRead();
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  };

  if (authLoading || !user) return null;

  const activeRules = rules.filter((r) => r.active);
  const triggeredRules = rules.filter((r) => !r.active);

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-5xl mx-auto px-4 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-white mb-2">
            Alerts & Notifications
          </h1>
          <p className="text-gray-400">
            Set up price alerts, follow AI traders, and track your positions.
            Notifications appear in the bell icon in the navbar.
          </p>
        </div>

        {loading ? (
          <p className="text-gray-400">Loading...</p>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left: Create + Active Rules */}
            <div className="space-y-6">
              <CreateAlertForm onCreated={fetchData} aiTraders={aiTraders} />

              {activeRules.length > 0 && (
                <div>
                  <h2 className="text-sm font-medium text-gray-400 mb-3">
                    Active Alerts ({activeRules.length})
                  </h2>
                  <div className="space-y-3">
                    {activeRules.map((rule) => (
                      <AlertRuleCard key={rule.id} rule={rule} onDelete={handleDelete} />
                    ))}
                  </div>
                </div>
              )}

              {triggeredRules.length > 0 && (
                <div>
                  <h2 className="text-sm font-medium text-gray-500 mb-3">
                    Past Alerts ({triggeredRules.length})
                  </h2>
                  <div className="space-y-3">
                    {triggeredRules.map((rule) => (
                      <AlertRuleCard key={rule.id} rule={rule} onDelete={handleDelete} />
                    ))}
                  </div>
                </div>
              )}

              {rules.length === 0 && (
                <div className="bg-gray-900 rounded-lg border border-gray-800 p-6 text-center">
                  <p className="text-gray-400 text-sm">
                    No alerts yet. Create one above to get started.
                  </p>
                </div>
              )}
            </div>

            {/* Right: Recent Notifications */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-medium text-gray-400">
                  Recent Notifications
                </h2>
                {notifications.some((n) => !n.read) && (
                  <button
                    onClick={handleMarkAllRead}
                    className="text-xs text-blue-400 hover:text-blue-300 transition"
                  >
                    Mark all read
                  </button>
                )}
              </div>

              {notifications.length === 0 ? (
                <div className="bg-gray-900 rounded-lg border border-gray-800 p-6 text-center">
                  <p className="text-gray-400 text-sm">
                    No notifications yet. Set up alerts and they&apos;ll appear here
                    when triggered.
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  {notifications.map((n) => (
                    <div
                      key={n.id}
                      className={`bg-gray-900 rounded-lg border border-gray-800 p-3 ${
                        !n.read ? "border-l-2 border-l-blue-500" : ""
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className={`text-xs px-1.5 py-0.5 rounded ${
                            n.type === "ai_trade"
                              ? "bg-blue-900/50 text-blue-400"
                              : n.type === "price_alert"
                                ? "bg-yellow-900/50 text-yellow-400"
                                : "bg-green-900/50 text-green-400"
                          }`}
                        >
                          {n.type === "ai_trade"
                            ? "AI Trade"
                            : n.type === "price_alert"
                              ? "Price Alert"
                              : "Portfolio"}
                        </span>
                        <span className="text-xs text-gray-500">
                          {getTimeAgo(n.created_at)}
                        </span>
                      </div>
                      <p className="text-sm text-white font-medium">{n.title}</p>
                      <p className="text-xs text-gray-400 mt-0.5 line-clamp-3">
                        {n.message}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
