"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useLeague } from "@/hooks/useLeague";

type Step = "credentials" | "authorize" | "verify" | "league" | "done";

export default function SetupPage() {
  const router = useRouter();
  const { refreshLeagues } = useLeague();

  const [step, setStep] = useState<Step>("credentials");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [leagueId, setLeagueId] = useState("28641");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSaveCredentials() {
    if (!clientId || !clientSecret) { setError("Both fields required"); return; }
    setLoading(true); setError("");
    try {
      await api.auth.saveCredentials(clientId, clientSecret);
      setStep("authorize");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleAuthorize() {
    setLoading(true); setError("");
    try {
      const { auth_url } = await api.auth.getLoginUrl();
      window.open(auth_url, "_blank");
      setStep("verify");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifyCode() {
    if (!verificationCode.trim()) { setError("Paste the code from Yahoo"); return; }
    setLoading(true); setError("");
    try {
      await api.auth.submitOobCode(verificationCode.trim());
      setStep("league");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleAddLeague() {
    if (!leagueId) { setError("League ID required"); return; }
    setLoading(true); setError("");
    try {
      await api.leagues.add(leagueId);
      await refreshLeagues();
      setStep("done");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  const steps: Step[] = ["credentials", "authorize", "verify", "league", "done"];

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <div className="w-full max-w-lg">
        {/* Logo */}
        <div className="text-center mb-10">
          <div className="w-16 h-16 rounded-2xl bg-primary flex items-center justify-center text-primary-foreground font-bold text-2xl mx-auto mb-4">IQ</div>
          <h1 className="text-3xl font-bold text-foreground">Fantasy IQ</h1>
          <p className="text-muted-foreground mt-2">AI-powered NBA Fantasy Intelligence</p>
        </div>

        <div className="bg-card border border-border rounded-xl p-8 space-y-6">
          {/* Progress */}
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            {steps.map((s, i) => (
              <div key={s} className="flex items-center gap-2">
                <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
                  step === s ? "bg-primary text-primary-foreground" :
                  steps.indexOf(step) > i ? "bg-primary/30 text-primary" :
                  "bg-muted text-muted-foreground"
                }`}>{i + 1}</div>
                {i < steps.length - 1 && <div className="w-6 h-px bg-border" />}
              </div>
            ))}
          </div>

          {step === "credentials" && (
            <div className="space-y-5">
              <div>
                <h2 className="text-xl font-semibold text-foreground">Yahoo Developer Credentials</h2>
                <p className="text-sm text-muted-foreground mt-1">
                  Create a free app at{" "}
                  <a href="https://developer.yahoo.com/apps/" target="_blank" rel="noopener" className="text-primary underline">
                    developer.yahoo.com/apps
                  </a>. Use these values:
                </p>
                <div className="mt-3 space-y-1.5 text-xs bg-muted rounded-lg p-3">
                  <div><span className="text-muted-foreground">Homepage URL:</span> <code className="text-foreground">http://localhost:3000</code></div>
                  <div><span className="text-muted-foreground">Redirect URI:</span> <code className="text-foreground">https://localhost</code></div>
                </div>
              </div>
              <div className="space-y-3">
                <div>
                  <label className="text-sm font-medium text-foreground block mb-1.5">Client ID</label>
                  <input
                    value={clientId} onChange={e => setClientId(e.target.value)}
                    placeholder="dj0yJm..."
                    className="w-full px-3 py-2 bg-input border border-border rounded-md text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium text-foreground block mb-1.5">Client Secret</label>
                  <input
                    type="password" value={clientSecret} onChange={e => setClientSecret(e.target.value)}
                    placeholder="••••••••••••"
                    className="w-full px-3 py-2 bg-input border border-border rounded-md text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>
              {error && <p className="text-destructive text-sm">{error}</p>}
              <button
                onClick={handleSaveCredentials} disabled={loading}
                className="w-full py-2.5 bg-primary text-primary-foreground rounded-md font-medium text-sm hover:bg-primary/90 disabled:opacity-50 transition-colors"
              >
                {loading ? "Saving..." : "Continue"}
              </button>
            </div>
          )}

          {step === "authorize" && (
            <div className="space-y-5">
              <div>
                <h2 className="text-xl font-semibold text-foreground">Connect Yahoo Account</h2>
                <p className="text-sm text-muted-foreground mt-1">
                  Click below to open Yahoo's authorization page. Yahoo will show you a verification code — copy it and paste it on the next screen.
                </p>
              </div>
              {error && <p className="text-destructive text-sm">{error}</p>}
              <button
                onClick={handleAuthorize} disabled={loading}
                className="w-full py-2.5 bg-primary text-primary-foreground rounded-md font-medium text-sm hover:bg-primary/90 disabled:opacity-50 transition-colors"
              >
                {loading ? "Opening Yahoo..." : "Authorize with Yahoo →"}
              </button>
            </div>
          )}

          {step === "verify" && (
            <div className="space-y-5">
              <div>
                <h2 className="text-xl font-semibold text-foreground">Enter Authorization Code</h2>
                <p className="text-sm text-muted-foreground mt-1">
                  After authorizing, Yahoo redirected to a page that won't load — that's expected. Copy the <strong>full URL</strong> from your browser's address bar and paste it below.
                  It looks like: <code className="text-xs bg-muted px-1 py-0.5 rounded">https://localhost?code=xxxxxx</code>
                </p>
              </div>
              <div>
                <label className="text-sm font-medium text-foreground block mb-1.5">Verification Code</label>
                <input
                  value={verificationCode}
                  onChange={e => setVerificationCode(e.target.value)}
                  placeholder="https://localhost?code=... or just the code"
                  className="w-full px-3 py-2 bg-input border border-border rounded-md text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring font-mono tracking-widest"
                  autoFocus
                />
              </div>
              {error && <p className="text-destructive text-sm">{error}</p>}
              <div className="flex gap-3">
                <button
                  onClick={() => setStep("authorize")}
                  className="flex-1 py-2.5 bg-muted text-foreground rounded-md font-medium text-sm hover:bg-accent transition-colors"
                >
                  Back
                </button>
                <button
                  onClick={handleVerifyCode} disabled={loading}
                  className="flex-1 py-2.5 bg-primary text-primary-foreground rounded-md font-medium text-sm hover:bg-primary/90 disabled:opacity-50 transition-colors"
                >
                  {loading ? "Verifying..." : "Verify"}
                </button>
              </div>
            </div>
          )}

          {step === "league" && (
            <div className="space-y-5">
              <div>
                <h2 className="text-xl font-semibold text-foreground">Add Your League</h2>
                <p className="text-sm text-muted-foreground mt-1">
                  Enter your Yahoo Fantasy league ID. Found in your league's URL:{" "}
                  <code className="text-xs bg-muted px-1 py-0.5 rounded">fantasysports.yahoo.com/nba/XXXXXX</code>
                </p>
              </div>
              <div>
                <label className="text-sm font-medium text-foreground block mb-1.5">League ID</label>
                <input
                  value={leagueId} onChange={e => setLeagueId(e.target.value)}
                  placeholder="28641"
                  className="w-full px-3 py-2 bg-input border border-border rounded-md text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              {error && <p className="text-destructive text-sm">{error}</p>}
              <button
                onClick={handleAddLeague} disabled={loading}
                className="w-full py-2.5 bg-primary text-primary-foreground rounded-md font-medium text-sm hover:bg-primary/90 disabled:opacity-50 transition-colors"
              >
                {loading ? "Loading league..." : "Add League"}
              </button>
            </div>
          )}

          {step === "done" && (
            <div className="space-y-5 text-center">
              <div className="w-16 h-16 rounded-full bg-green-500/20 flex items-center justify-center mx-auto">
                <svg className="w-8 h-8 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <div>
                <h2 className="text-xl font-semibold text-foreground">You're all set!</h2>
                <p className="text-sm text-muted-foreground mt-1">
                  Your league data is syncing in the background. Head to your dashboard to get started.
                </p>
              </div>
              <button
                onClick={() => router.push("/dashboard")}
                className="w-full py-2.5 bg-primary text-primary-foreground rounded-md font-medium text-sm hover:bg-primary/90 transition-colors"
              >
                Go to Dashboard
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
