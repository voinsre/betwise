"use client";

import Link from "next/link";
import ChatInterface from "@/components/ChatInterface";

export default function ChatPage() {
  return (
    <main className="flex flex-col h-screen bg-brand-bg">
      {/* Header */}
      <header className="border-b border-brand-border bg-brand-surface/50 px-4 py-3 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-2.5">
            <div className="w-7 h-7 bg-accent-green rounded-lg flex items-center justify-center">
              <span className="text-white font-bold text-xs">BW</span>
            </div>
            <h1 className="text-lg font-bold text-white">BetWise</h1>
          </Link>
          <span className="text-xs text-gray-600 border-l border-brand-border pl-3 hidden sm:inline">
            AI Betting Intelligence
          </span>
        </div>
        <Link
          href="/admin"
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          Admin
        </Link>
      </header>

      {/* Chat */}
      <div className="flex-1 overflow-hidden">
        <ChatInterface />
      </div>
    </main>
  );
}
