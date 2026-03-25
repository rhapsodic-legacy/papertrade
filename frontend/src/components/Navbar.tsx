"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";

const NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/trade", label: "Trade" },
  { href: "/history", label: "History" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/leaderboard", label: "Leaderboard" },
  { href: "/my-analytics", label: "My Analytics" },
];

const AI_LINKS = [
  { href: "/insights", label: "AI Insights", desc: "Daily AI commentary" },
  { href: "/analytics", label: "AI Analytics", desc: "Model & personality performance" },
  { href: "/reasoning", label: "AI Reasoning", desc: "Why AIs make each trade" },
  { href: "/learn", label: "Learn from AI", desc: "Study AI trade reasoning" },
  { href: "/how-it-works", label: "How It Works", desc: "Trading basics & platform guide" },
];

// All links combined for mobile menu
const ALL_LINKS = [
  ...NAV_LINKS,
  ...AI_LINKS.map((l) => ({ href: l.href, label: l.label })),
];

type Notification = {
  id: string;
  type: string;
  title: string;
  message: string;
  metadata: Record<string, unknown>;
  read: boolean;
  created_at: string;
};

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

const TYPE_ICONS: Record<string, string> = {
  ai_trade: "bg-blue-900/50 text-blue-400",
  price_alert: "bg-yellow-900/50 text-yellow-400",
  portfolio: "bg-green-900/50 text-green-400",
};

function NotificationPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setLoading(true);
      api
        .getNotifications(20)
        .then((res) => setNotifications(res.notifications))
        .catch(() => {})
        .finally(() => setLoading(false));
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open, onClose]);

  const handleMarkAllRead = async () => {
    await api.markAllNotificationsRead();
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  };

  if (!open) return null;

  return (
    <div
      ref={panelRef}
      className="absolute right-0 top-full mt-2 w-80 sm:w-96 bg-gray-900 border border-gray-800 rounded-lg shadow-xl z-50 max-h-[70vh] overflow-hidden flex flex-col"
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <span className="text-sm font-semibold text-white">Notifications</span>
        <div className="flex items-center gap-3">
          {notifications.some((n) => !n.read) && (
            <button
              onClick={handleMarkAllRead}
              className="text-xs text-blue-400 hover:text-blue-300 transition"
            >
              Mark all read
            </button>
          )}
          <Link
            href="/alerts"
            onClick={onClose}
            className="text-xs text-gray-400 hover:text-white transition"
          >
            Manage alerts
          </Link>
        </div>
      </div>
      <div className="overflow-y-auto flex-1">
        {loading ? (
          <div className="p-4 text-center text-gray-500 text-sm">Loading...</div>
        ) : notifications.length === 0 ? (
          <div className="p-6 text-center">
            <p className="text-gray-500 text-sm mb-2">No notifications yet</p>
            <Link
              href="/alerts"
              onClick={onClose}
              className="text-xs text-blue-400 hover:text-blue-300 transition"
            >
              Set up alerts to get notified
            </Link>
          </div>
        ) : (
          notifications.map((n) => (
            <div
              key={n.id}
              className={`px-4 py-3 border-b border-gray-800/50 hover:bg-gray-800/50 transition ${
                !n.read ? "bg-gray-800/30" : ""
              }`}
            >
              <div className="flex items-start gap-3">
                <div
                  className={`mt-0.5 w-2 h-2 rounded-full flex-shrink-0 ${
                    !n.read ? "bg-blue-400" : "bg-transparent"
                  }`}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-xs px-1.5 py-0.5 rounded ${
                        TYPE_ICONS[n.type] || "bg-gray-800 text-gray-400"
                      }`}
                    >
                      {n.type === "ai_trade"
                        ? "AI"
                        : n.type === "price_alert"
                          ? "Price"
                          : "Portfolio"}
                    </span>
                    <span className="text-xs text-gray-500">
                      {getTimeAgo(n.created_at)}
                    </span>
                  </div>
                  <p className="text-sm text-white mt-1 font-medium truncate">
                    {n.title}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5 line-clamp-2">
                    {n.message}
                  </p>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function AiDropdown() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-gray-300 hover:text-white transition"
      >
        AI & Learn
        <svg
          className={`w-3.5 h-3.5 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-2 w-64 bg-gray-900 border border-gray-800 rounded-lg shadow-xl z-50 py-2">
          {AI_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={() => setOpen(false)}
              className="block px-4 py-2.5 hover:bg-gray-800 transition"
            >
              <span className="text-sm text-white">{link.label}</span>
              <span className="block text-xs text-gray-500">{link.desc}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Navbar() {
  const { user, signOut } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);

  useEffect(() => {
    if (!user) return;
    const fetchCount = () => {
      api
        .getUnreadCount()
        .then((res) => setUnreadCount(res.unread_count))
        .catch(() => {});
    };
    fetchCount();
    const interval = setInterval(fetchCount, 60000);
    return () => clearInterval(interval);
  }, [user]);

  useEffect(() => {
    if (!notifOpen && user) {
      api
        .getUnreadCount()
        .then((res) => setUnreadCount(res.unread_count))
        .catch(() => {});
    }
  }, [notifOpen, user]);

  return (
    <nav className="bg-gray-900 border-b border-gray-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-8">
            <Link href="/dashboard" className="text-xl font-bold text-white">
              PaperTrade
            </Link>
            {user && (
              <div className="hidden md:flex items-center gap-6">
                {NAV_LINKS.map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="text-gray-300 hover:text-white transition"
                  >
                    {link.label}
                  </Link>
                ))}
                <AiDropdown />
              </div>
            )}
          </div>
          {user && (
            <div className="flex items-center gap-4">
              <span className="hidden sm:inline text-sm text-gray-400">
                {user.display_name} &middot;{" "}
                <span className="text-green-400">
                  {formatCurrency(user.cash_balance)}
                </span>
              </span>

              {/* Notification bell */}
              <div className="relative">
                <button
                  onClick={() => setNotifOpen(!notifOpen)}
                  className="relative p-1.5 text-gray-400 hover:text-white transition"
                  aria-label="Notifications"
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
                      d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
                    />
                  </svg>
                  {unreadCount > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-red-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center">
                      {unreadCount > 9 ? "9+" : unreadCount}
                    </span>
                  )}
                </button>
                <NotificationPanel
                  open={notifOpen}
                  onClose={() => setNotifOpen(false)}
                />
              </div>

              <button
                onClick={signOut}
                className="hidden md:inline text-sm text-gray-400 hover:text-white transition"
              >
                Sign Out
              </button>
              {/* Mobile hamburger */}
              <button
                onClick={() => setMenuOpen(!menuOpen)}
                className="md:hidden p-2 text-gray-400 hover:text-white transition"
                aria-label="Toggle menu"
              >
                <svg
                  className="w-6 h-6"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  {menuOpen ? (
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M6 18L18 6M6 6l12 12"
                    />
                  ) : (
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M4 6h16M4 12h16M4 18h16"
                    />
                  )}
                </svg>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Mobile menu */}
      {user && menuOpen && (
        <div className="md:hidden border-t border-gray-800">
          <div className="px-4 py-3 space-y-1">
            {ALL_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setMenuOpen(false)}
                className="block px-3 py-2 text-gray-300 hover:text-white hover:bg-gray-800 rounded-md transition"
              >
                {link.label}
              </Link>
            ))}
            <Link
              href="/alerts"
              onClick={() => setMenuOpen(false)}
              className="block px-3 py-2 text-gray-300 hover:text-white hover:bg-gray-800 rounded-md transition"
            >
              Alerts & Notifications
            </Link>
            <div className="border-t border-gray-800 mt-2 pt-2">
              <span className="block px-3 py-2 text-sm text-gray-400">
                {user.display_name} &middot;{" "}
                <span className="text-green-400">
                  {formatCurrency(user.cash_balance)}
                </span>
              </span>
              <button
                onClick={() => {
                  setMenuOpen(false);
                  signOut();
                }}
                className="block w-full text-left px-3 py-2 text-sm text-gray-400 hover:text-white hover:bg-gray-800 rounded-md transition"
              >
                Sign Out
              </button>
            </div>
          </div>
        </div>
      )}
    </nav>
  );
}
