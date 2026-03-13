"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";

export default function AuthPage() {
  const [isSignUp, setIsSignUp] = useState(false);
  const [isForgot, setIsForgot] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const { signIn, signUp } = useAuth();
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);

    try {
      if (isForgot) {
        const resp = await api.resetPassword(email);
        setMessage(resp.message);
      } else if (isSignUp) {
        await signUp(email, password, displayName || undefined);
        router.push("/dashboard");
      } else {
        await signIn(email, password);
        router.push("/dashboard");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center px-4">
      <div className="max-w-md w-full">
        <div className="text-center mb-8">
          <h1 className="text-4xl font-bold text-white mb-2">PaperTrade</h1>
          <p className="text-gray-400">
            Learn to invest risk-free with $100,000 in virtual money
          </p>
        </div>

        <div className="bg-gray-900 rounded-lg p-8 border border-gray-800">
          {!isForgot && (
            <div className="flex mb-6">
              <button
                onClick={() => { setIsSignUp(false); setError(""); setMessage(""); }}
                className={`flex-1 py-2 text-center text-sm font-medium border-b-2 transition ${
                  !isSignUp
                    ? "border-blue-500 text-white"
                    : "border-transparent text-gray-400 hover:text-white"
                }`}
              >
                Sign In
              </button>
              <button
                onClick={() => { setIsSignUp(true); setError(""); setMessage(""); }}
                className={`flex-1 py-2 text-center text-sm font-medium border-b-2 transition ${
                  isSignUp
                    ? "border-blue-500 text-white"
                    : "border-transparent text-gray-400 hover:text-white"
                }`}
              >
                Sign Up
              </button>
            </div>
          )}

          {isForgot && (
            <div className="mb-6">
              <h2 className="text-lg font-semibold text-white">Reset Password</h2>
              <p className="text-sm text-gray-400 mt-1">
                Enter your email and we will send you a reset link.
              </p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {isSignUp && !isForgot && (
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  Display Name
                </label>
                <input
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white focus:outline-none focus:border-blue-500"
                  placeholder="TraderJoe"
                />
              </div>
            )}
            <div>
              <label className="block text-sm text-gray-400 mb-1">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white focus:outline-none focus:border-blue-500"
                placeholder="you@example.com"
              />
            </div>
            {!isForgot && (
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={6}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white focus:outline-none focus:border-blue-500"
                  placeholder="••••••••"
                />
              </div>
            )}

            {error && (
              <p className="text-red-400 text-sm">{error}</p>
            )}

            {message && (
              <p className="text-green-400 text-sm">{message}</p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 disabled:cursor-not-allowed text-white rounded font-medium transition"
            >
              {loading
                ? "..."
                : isForgot
                  ? "Send Reset Link"
                  : isSignUp
                    ? "Create Account"
                    : "Sign In"}
            </button>

            {!isSignUp && !isForgot && (
              <button
                type="button"
                onClick={() => { setIsForgot(true); setError(""); setMessage(""); }}
                className="w-full text-sm text-gray-400 hover:text-white transition"
              >
                Forgot password?
              </button>
            )}

            {isForgot && (
              <button
                type="button"
                onClick={() => { setIsForgot(false); setError(""); setMessage(""); }}
                className="w-full text-sm text-gray-400 hover:text-white transition"
              >
                Back to Sign In
              </button>
            )}
          </form>
        </div>
      </div>
    </div>
  );
}
