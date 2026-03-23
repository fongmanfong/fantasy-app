"use client";
import { useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { useLeague } from "@/hooks/useLeague";
import { api, ChatMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Send, MessageSquare } from "lucide-react";
import ReactMarkdown from "react-markdown";

const SUGGESTIONS = [
  "Who should I pick up to gain ground in assists?",
  "Is my team in good shape this week?",
  "What does my opponent's roster look like?",
  "Should I stream anyone this week?",
  "What's the injury situation on my team?",
];

export default function ChatPage() {
  const { activeLeague } = useLeague();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function sendMessage(text: string) {
    if (!text.trim() || !activeLeague || loading) return;

    const userMessage: ChatMessage = { role: "user", content: text.trim() };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setInput("");
    setLoading(true);

    try {
      const data = await api.agent.chat(newMessages, activeLeague.id);
      setMessages([...newMessages, { role: "assistant", content: data.response }]);
    } catch (e: any) {
      setMessages([...newMessages, { role: "assistant", content: `Error: ${e.message}` }]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  return (
    <AppShell>
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border">
          <h1 className="text-xl font-bold text-foreground">Chat</h1>
          {activeLeague && (
            <p className="text-sm text-muted-foreground">
              Ask anything about {activeLeague.name}
            </p>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full gap-6 text-center">
              <div className="w-16 h-16 rounded-2xl bg-primary/20 flex items-center justify-center">
                <MessageSquare className="w-8 h-8 text-primary" />
              </div>
              <div>
                <h2 className="text-xl font-semibold text-foreground mb-2">Ask anything about your league</h2>
                <p className="text-muted-foreground text-sm max-w-sm">
                  I have full context of your roster, matchup, free agents, standings, and the latest player news.
                </p>
              </div>
              {activeLeague && (
                <div className="flex flex-wrap gap-2 justify-center max-w-lg">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => sendMessage(s)}
                      className="px-3 py-2 bg-card border border-border rounded-lg text-sm text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors text-left"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={cn(
              "flex gap-3",
              msg.role === "user" ? "justify-end" : "justify-start"
            )}>
              {msg.role === "assistant" && (
                <div className="w-8 h-8 rounded-lg bg-primary/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <span className="text-primary text-xs font-bold">IQ</span>
                </div>
              )}
              <div className={cn(
                "rounded-xl px-4 py-3 max-w-[75%]",
                msg.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-card border border-border text-foreground"
              )}>
                {msg.role === "assistant" ? (
                  <div className="prose prose-invert prose-sm max-w-none">
                    <ReactMarkdown
                      components={{
                        p: ({ children }) => <p className="text-foreground/90 leading-relaxed mb-2 last:mb-0">{children}</p>,
                        ul: ({ children }) => <ul className="space-y-1 mb-2 ml-4">{children}</ul>,
                        li: ({ children }) => <li className="text-foreground/90 list-disc ml-2">{children}</li>,
                        strong: ({ children }) => <strong className="text-foreground font-semibold">{children}</strong>,
                        h1: ({ children }) => <h1 className="text-base font-bold text-foreground mb-2">{children}</h1>,
                        h2: ({ children }) => <h2 className="text-sm font-bold text-foreground mb-1.5">{children}</h2>,
                        h3: ({ children }) => <h3 className="text-sm font-semibold text-foreground mb-1">{children}</h3>,
                        code: ({ children }) => <code className="bg-muted px-1.5 py-0.5 rounded text-xs">{children}</code>,
                      }}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <p className="text-sm">{msg.content}</p>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex gap-3 justify-start">
              <div className="w-8 h-8 rounded-lg bg-primary/20 flex items-center justify-center flex-shrink-0">
                <span className="text-primary text-xs font-bold">IQ</span>
              </div>
              <div className="bg-card border border-border rounded-xl px-4 py-3">
                <div className="flex gap-1.5 items-center">
                  <div className="w-2 h-2 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: "0ms" }} />
                  <div className="w-2 h-2 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: "150ms" }} />
                  <div className="w-2 h-2 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: "300ms" }} />
                </div>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="px-6 py-4 border-t border-border">
          <div className="flex gap-3 items-end">
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={activeLeague ? "Ask about your league..." : "Select a league first"}
              disabled={!activeLeague || loading}
              rows={1}
              className="flex-1 resize-none bg-card border border-border rounded-xl px-4 py-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring placeholder:text-muted-foreground disabled:opacity-50 max-h-32 overflow-y-auto"
              style={{ minHeight: "44px" }}
            />
            <button
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || !activeLeague || loading}
              className="w-10 h-10 rounded-xl bg-primary text-primary-foreground flex items-center justify-center hover:bg-primary/90 disabled:opacity-50 transition-colors flex-shrink-0"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
          <p className="text-xs text-muted-foreground mt-2">Enter to send · Shift+Enter for new line</p>
        </div>
      </div>
    </AppShell>
  );
}
