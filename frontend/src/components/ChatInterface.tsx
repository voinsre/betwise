"use client";

import { useState, useRef, useEffect } from "react";
import { useChat, type ChatMessage, type StructuredData } from "@/hooks/useChat";
import TicketCard, { type TicketData } from "@/components/TicketCard";
import ValueBetsList from "@/components/ValueBetsList";
import { type ValueBet } from "@/components/ValueBetCard";

const QUICK_ACTIONS = [
  {
    label: "Best bets today",
    message: "What are today's best value bets?",
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
      </svg>
    ),
  },
  {
    label: "Safe 3-game ticket",
    message: "Build me a safe 3-game ticket with high confidence picks",
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
  {
    label: "High value picks",
    message: "Show me the highest edge value bets today",
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    label: "Top match analysis",
    message: "Analyze today's top match with the best value opportunities",
    icon: (
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
    ),
  },
];

function extractValueBets(data: StructuredData): ValueBet[] | null {
  if (data.type !== "value_bets") return null;
  const raw = data.data as { predictions?: unknown[] };
  const predictions = raw.predictions;
  if (!Array.isArray(predictions)) return null;
  return predictions as ValueBet[];
}

function extractTicket(data: StructuredData): TicketData | null {
  if (data.type !== "ticket") return null;
  const raw = data.data as Record<string, unknown>;
  if (raw.ticket_id && raw.games && Array.isArray(raw.games)) {
    return raw as unknown as TicketData;
  }
  return null;
}

function formatMessageText(text: string): React.ReactNode[] {
  const lines = text.split("\n");
  const nodes: React.ReactNode[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Empty lines
    if (!line.trim()) {
      nodes.push(<div key={i} className="h-2" />);
      continue;
    }

    // Bold text: **text**
    const parts = line.split(/(\*\*[^*]+\*\*)/g);
    const rendered = parts.map((part, j) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return (
          <span key={j} className="font-semibold text-white">
            {part.slice(2, -2)}
          </span>
        );
      }
      return part;
    });

    // Detect star ratings
    if (line.includes("\u2605") || line.includes("\u2606")) {
      nodes.push(
        <div key={i} className="text-accent-amber">
          {rendered}
        </div>
      );
      continue;
    }

    // Detect separator lines (markdown tables)
    if (/^[-=|:\s]+$/.test(line.trim())) {
      nodes.push(<hr key={i} className="border-brand-border my-1" />);
      continue;
    }

    // Detect table rows
    if (line.includes("|") && line.trim().startsWith("|")) {
      const cells = line.split("|").filter(Boolean).map((c) => c.trim());
      nodes.push(
        <div key={i} className="font-mono text-xs text-gray-400 py-0.5">
          {cells.join("  |  ")}
        </div>
      );
      continue;
    }

    // Bullet points
    if (line.trim().startsWith("- ") || line.trim().startsWith("* ")) {
      nodes.push(
        <div key={i} className="pl-3 flex gap-1.5">
          <span className="text-accent-green">&#8226;</span>
          <span>{rendered.slice(0, 1)}{String(parts[0]).replace(/^[\s-*]+/, "")}{rendered.slice(1)}</span>
        </div>
      );
      continue;
    }

    nodes.push(<div key={i}>{rendered}</div>);
  }

  return nodes;
}

export default function ChatInterface() {
  const { messages, sendMessage, isLoading, clearChat } = useChat();
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;
    setInput("");
    sendMessage(trimmed);
  }

  function handleQuickAction(message: string) {
    if (isLoading) return;
    sendMessage(message);
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        {messages.length === 0 ? (
          <EmptyState onAction={handleQuickAction} />
        ) : (
          <div className="max-w-3xl mx-auto space-y-4">
            {messages.map((msg, i) => (
              <MessageBubble key={i} message={msg} />
            ))}

            {/* Loading indicator */}
            {isLoading && (
              <div className="flex gap-3">
                <div className="w-8 h-8 rounded-full bg-brand-card border border-brand-border flex items-center justify-center flex-shrink-0 overflow-hidden">
                  <img src="/icon-192.png" alt="WB" className="w-full h-full" />
                </div>
                <div className="bg-brand-card border border-brand-border rounded-2xl rounded-tl-sm px-4 py-3">
                  <div className="flex gap-1.5">
                    <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                    <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                    <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Quick actions (show when there are messages) */}
      {messages.length > 0 && !isLoading && (
        <div className="px-4 pb-2">
          <div className="max-w-3xl mx-auto flex gap-2 overflow-x-auto pb-1">
            {QUICK_ACTIONS.map((action) => (
              <button
                key={action.label}
                onClick={() => handleQuickAction(action.message)}
                className="flex-shrink-0 text-xs px-3 py-1.5 bg-brand-card border border-brand-border rounded-full text-gray-400 hover:text-white hover:border-gray-500 transition-colors flex items-center gap-1.5"
              >
                <span className="text-accent-green">{action.icon}</span>
                {action.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input bar */}
      <div className="border-t border-brand-border bg-brand-surface/50 px-4 py-3">
        <form onSubmit={handleSubmit} className="max-w-3xl mx-auto flex gap-3">
          <div className="flex-1 relative">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about bets, tickets, or match analysis..."
              disabled={isLoading}
              className="w-full bg-brand-card border border-brand-border rounded-xl px-4 py-3 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-accent-green/50 focus:ring-1 focus:ring-accent-green/30 disabled:opacity-50 transition-colors"
            />
          </div>
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="px-4 py-3 bg-accent-green hover:bg-accent-green/90 disabled:opacity-30 disabled:cursor-not-allowed rounded-xl transition-colors flex-shrink-0"
          >
            <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
            </svg>
          </button>
        </form>
        <div className="max-w-3xl mx-auto flex items-center justify-between mt-2">
          <p className="text-[10px] text-gray-700">
            Powered by Gemini 2.0 Flash &middot; Predictions are not guaranteed &middot; Bet responsibly
          </p>
          {messages.length > 0 && (
            <button
              onClick={clearChat}
              className="text-[10px] text-gray-600 hover:text-gray-400 transition-colors"
            >
              Clear chat
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function EmptyState({ onAction }: { onAction: (msg: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full max-w-md mx-auto text-center">
      <div className="w-14 h-14 bg-accent-green/10 rounded-2xl flex items-center justify-center mb-6">
        <svg className="w-7 h-7 text-accent-green" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
        </svg>
      </div>
      <h2 className="text-xl font-bold text-white mb-2">WizerBet AI</h2>
      <p className="text-gray-500 text-sm mb-8">
        Your AI football betting assistant. Ask about predictions, build tickets, or analyze matches.
      </p>
      <div className="grid grid-cols-2 gap-2 w-full">
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action.label}
            onClick={() => onAction(action.message)}
            className="text-left px-4 py-3 bg-brand-card border border-brand-border rounded-xl text-sm text-gray-400 hover:text-white hover:border-gray-500 transition-colors flex items-center gap-2"
          >
            <span className="text-accent-green flex-shrink-0">{action.icon}</span>
            {action.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end gap-3">
        <div className="bg-accent-green/10 border border-accent-green/20 rounded-2xl rounded-tr-sm px-4 py-3 max-w-[85%]">
          <p className="text-sm text-white whitespace-pre-wrap">{message.content}</p>
        </div>
        <div className="w-8 h-8 rounded-full bg-accent-green/20 flex items-center justify-center flex-shrink-0">
          <svg className="w-4 h-4 text-accent-green" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
          </svg>
        </div>
      </div>
    );
  }

  // Extract structured data
  const sd = message.structured_data;
  const valueBets = sd ? extractValueBets(sd) : null;
  const ticket = sd ? extractTicket(sd) : null;

  return (
    <div className="flex gap-3">
      <div className="w-8 h-8 rounded-full bg-brand-card border border-brand-border flex items-center justify-center flex-shrink-0 overflow-hidden">
        <img src="/icon-192.png" alt="WB" className="w-full h-full" />
      </div>
      <div className="max-w-[85%] min-w-0">
        {/* Text content */}
        <div className="bg-brand-card border border-brand-border rounded-2xl rounded-tl-sm px-4 py-3">
          <div className="text-sm text-gray-200 whitespace-pre-wrap leading-relaxed">
            {formatMessageText(message.content)}
          </div>
        </div>

        {/* Structured data: Value Bets */}
        {valueBets && valueBets.length > 0 && <ValueBetsList bets={valueBets} />}

        {/* Structured data: Ticket */}
        {ticket && <TicketCard ticket={ticket} />}
      </div>
    </div>
  );
}
