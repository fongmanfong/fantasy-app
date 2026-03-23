"use client";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { useLeague } from "@/hooks/useLeague";
import { api } from "@/lib/api";
import { Lightbulb, RefreshCw } from "lucide-react";
import ReactMarkdown from "react-markdown";

export default function RecommendationsPage() {
  const { activeLeague } = useLeague();
  const [recommendations, setRecommendations] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  async function fetchRecommendations() {
    if (!activeLeague) return;
    setLoading(true);
    try {
      const data = await api.agent.recommendations(activeLeague.id);
      setRecommendations(data.recommendations);
      setLastUpdated(new Date());
    } catch (e: any) {
      setRecommendations(`Error: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (activeLeague && !recommendations) {
      fetchRecommendations();
    }
  }, [activeLeague]);

  return (
    <AppShell>
      <div className="p-6 space-y-6 max-w-4xl mx-auto">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">Recommendations</h1>
            <p className="text-muted-foreground text-sm">
              AI analysis contextualized to your league's scoring format
              {lastUpdated && ` · Updated ${lastUpdated.toLocaleTimeString()}`}
            </p>
          </div>
          <button
            onClick={fetchRecommendations}
            disabled={loading || !activeLeague}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            {loading ? "Analyzing..." : "Refresh"}
          </button>
        </div>

        {!activeLeague ? (
          <div className="bg-card border border-border rounded-xl p-8 text-center">
            <p className="text-muted-foreground">Select a league to get recommendations.</p>
          </div>
        ) : loading ? (
          <div className="bg-card border border-border rounded-xl p-8">
            <div className="flex flex-col items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-primary/20 flex items-center justify-center">
                <Lightbulb className="w-6 h-6 text-primary animate-pulse" />
              </div>
              <div className="text-center">
                <p className="font-medium text-foreground">Analyzing your league...</p>
                <p className="text-sm text-muted-foreground mt-1">
                  Reviewing your roster, matchup, free agents, and player news
                </p>
              </div>
            </div>
          </div>
        ) : recommendations ? (
          <div className="bg-card border border-border rounded-xl p-6">
            <div className="prose prose-invert prose-sm max-w-none">
              <ReactMarkdown
                components={{
                  h1: ({ children }) => <h1 className="text-xl font-bold text-foreground mt-6 mb-3 first:mt-0">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-lg font-semibold text-foreground mt-5 mb-2">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-base font-semibold text-foreground mt-4 mb-1.5">{children}</h3>,
                  p: ({ children }) => <p className="text-foreground/90 leading-relaxed mb-3">{children}</p>,
                  ul: ({ children }) => <ul className="space-y-1 mb-3 ml-4">{children}</ul>,
                  li: ({ children }) => <li className="text-foreground/90 list-disc ml-2">{children}</li>,
                  strong: ({ children }) => <strong className="text-foreground font-semibold">{children}</strong>,
                  code: ({ children }) => <code className="bg-muted px-1.5 py-0.5 rounded text-xs text-foreground">{children}</code>,
                }}
              >
                {recommendations}
              </ReactMarkdown>
            </div>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
