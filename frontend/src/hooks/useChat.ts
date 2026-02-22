"use client";

import { useState } from "react";
import { fetchApi } from "@/lib/api";

export interface StructuredData {
  type: "value_bets" | "ticket" | "analysis";
  function: string;
  data: Record<string, unknown>;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  structured_data?: StructuredData;
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [history, setHistory] = useState<Array<{ role: string; content: string }>>([]);
  const [isLoading, setIsLoading] = useState(false);

  const sendMessage = async (content: string) => {
    const userMessage: ChatMessage = { role: "user", content };
    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const response = await fetchApi<{
        response: string;
        history: Array<{ role: string; content: string }>;
        structured_data?: StructuredData;
      }>("/api/chat", {
        method: "POST",
        body: JSON.stringify({
          message: content,
          history,
        }),
        auth: false,
      });

      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: response.response,
        structured_data: response.structured_data,
      };
      setMessages((prev) => [...prev, assistantMessage]);
      setHistory(response.history);
    } catch {
      const errorMessage: ChatMessage = {
        role: "assistant",
        content: "Sorry, something went wrong connecting to the server. Please try again.",
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const clearChat = () => {
    setMessages([]);
    setHistory([]);
  };

  return { messages, sendMessage, isLoading, clearChat };
}
