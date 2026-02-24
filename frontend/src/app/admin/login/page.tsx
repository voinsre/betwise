"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login, setToken } from "@/lib/api";

export default function AdminLoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const data = await login(username, password);
      setToken(data.token);
      router.push("/admin");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Login failed";
      setError(message.includes("401") ? "Invalid credentials" : message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-brand-bg">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="w-12 h-12 rounded-xl flex items-center justify-center mx-auto mb-4 overflow-hidden">
            <img src="/icon-192.png" alt="WizerBet" className="w-full h-full" />
          </div>
          <h1 className="text-2xl font-bold text-white">Wizer<span className="text-accent-green">Bet</span> Admin</h1>
          <p className="text-gray-500 text-sm mt-1">Sign in to your dashboard</p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="bg-brand-card border border-brand-border rounded-xl p-6 space-y-4">
          {error && (
            <div className="bg-accent-red/10 border border-accent-red/20 text-accent-red text-sm px-4 py-3 rounded-lg">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-brand-bg border border-brand-border rounded-lg px-4 py-2.5 text-white placeholder-gray-600 focus:outline-none focus:border-accent-green focus:ring-1 focus:ring-accent-green"
              placeholder="admin"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-brand-bg border border-brand-border rounded-lg px-4 py-2.5 text-white placeholder-gray-600 focus:outline-none focus:border-accent-green focus:ring-1 focus:ring-accent-green"
              placeholder="Enter password"
              required
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-accent-green hover:bg-accent-green/90 disabled:opacity-50 text-white font-medium py-2.5 rounded-lg transition-colors"
          >
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>
      </div>
    </main>
  );
}
