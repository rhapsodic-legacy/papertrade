"use client";

import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import { formatCurrency } from "@/lib/utils";

export default function Navbar() {
  const { user, signOut } = useAuth();

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
                <Link
                  href="/dashboard"
                  className="text-gray-300 hover:text-white transition"
                >
                  Dashboard
                </Link>
                <Link
                  href="/trade"
                  className="text-gray-300 hover:text-white transition"
                >
                  Trade
                </Link>
                <Link
                  href="/history"
                  className="text-gray-300 hover:text-white transition"
                >
                  History
                </Link>
                <Link
                  href="/leaderboard"
                  className="text-gray-300 hover:text-white transition"
                >
                  Leaderboard
                </Link>
              </div>
            )}
          </div>
          {user && (
            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-400">
                {user.display_name} &middot;{" "}
                <span className="text-green-400">
                  {formatCurrency(user.cash_balance)}
                </span>
              </span>
              <button
                onClick={signOut}
                className="text-sm text-gray-400 hover:text-white transition"
              >
                Sign Out
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
}
