"use client";

import Link from "next/link";
import HistoryView from "@/components/HistoryView";

export default function HistoryPage() {
  return (
    <main className="min-h-screen bg-brand-bg">
      {/* Header */}
      <header className="border-b border-brand-border bg-brand-surface/50 px-4 py-3 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center overflow-hidden">
              <img src="/icon-192.png" alt="WizerBet" className="w-full h-full" />
            </div>
            <h1 className="text-lg font-bold text-white">
              Wizer<span className="text-accent-green">Bet</span>
            </h1>
          </Link>
          <span className="text-xs text-gray-600 border-l border-brand-border pl-3 hidden sm:inline">
            AI Betting Intelligence
          </span>
        </div>
        <nav className="flex items-center gap-4">
          <Link
            href="/chat"
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            Chat
          </Link>
          <Link
            href="/history"
            className="text-xs text-accent-green font-medium"
          >
            History
          </Link>
          <Link
            href="/admin/login"
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            Admin
          </Link>
        </nav>
      </header>

      {/* Content */}
      <HistoryView />
    </main>
  );
}
