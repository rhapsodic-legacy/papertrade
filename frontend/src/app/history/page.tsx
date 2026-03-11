"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/utils";
import Navbar from "@/components/Navbar";

interface Transaction {
  id: string;
  symbol: string;
  asset_type: string;
  side: string;
  quantity: number;
  price: number;
  total: number;
  created_at: string;
}

export default function HistoryPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!authLoading && !user) router.push("/auth");
  }, [user, authLoading, router]);

  useEffect(() => {
    if (user) {
      api
        .getHistory()
        .then(setTransactions)
        .catch(console.error)
        .finally(() => setLoading(false));
    }
  }, [user]);

  if (authLoading || !user) return null;

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-white mb-6">
          Transaction History
        </h1>

        <div className="bg-gray-900 rounded-lg border border-gray-800">
          {loading ? (
            <p className="p-6 text-gray-400">Loading...</p>
          ) : transactions.length === 0 ? (
            <div className="p-6 text-center text-gray-400">
              No transactions yet.{" "}
              <button
                onClick={() => router.push("/trade")}
                className="text-blue-400 hover:text-blue-300"
              >
                Make your first trade
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-sm text-gray-400 border-b border-gray-800">
                    <th className="px-6 py-3">Date</th>
                    <th className="px-6 py-3">Symbol</th>
                    <th className="px-6 py-3">Type</th>
                    <th className="px-6 py-3">Side</th>
                    <th className="px-6 py-3 text-right">Qty</th>
                    <th className="px-6 py-3 text-right">Price</th>
                    <th className="px-6 py-3 text-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((tx) => (
                    <tr
                      key={tx.id}
                      className="border-b border-gray-800/50 hover:bg-gray-800/30"
                    >
                      <td className="px-6 py-4 text-gray-400 text-sm">
                        {formatDate(tx.created_at)}
                      </td>
                      <td className="px-6 py-4 font-medium text-white">
                        {tx.symbol}
                      </td>
                      <td className="px-6 py-4 text-gray-400 capitalize">
                        {tx.asset_type}
                      </td>
                      <td className="px-6 py-4">
                        <span
                          className={`px-2 py-1 rounded text-xs font-medium ${
                            tx.side === "buy"
                              ? "bg-green-500/10 text-green-400"
                              : "bg-red-500/10 text-red-400"
                          }`}
                        >
                          {tx.side.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-right text-gray-300">
                        {tx.quantity}
                      </td>
                      <td className="px-6 py-4 text-right text-gray-300">
                        {formatCurrency(tx.price)}
                      </td>
                      <td className="px-6 py-4 text-right text-white font-medium">
                        {formatCurrency(tx.total)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
