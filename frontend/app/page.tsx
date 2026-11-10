"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, askQuestion, listTenants, resumeWithAnswer } from "@/lib/api";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { FeedbackButtons } from "@/components/FeedbackButtons";
import { ResultView } from "@/components/ResultView";
import { SqlView } from "@/components/SqlView";
import { TenantSwitcher } from "@/components/TenantSwitcher";

type Turn = {
  question: string;
  // One of these three is set once the turn resolves:
  answer?: { sql: string | null; rows: Record<string, unknown>[] | null; confidence: "high" | "medium" | "low" | null; traceId: string };
  clarification?: { question: string; threadId: string };
  error?: string;
};

export default function ChatPage() {
  const [tenants, setTenants] = useState<string[]>([]);
  const [tenant, setTenant] = useState<string>("");
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pendingClarify, setPendingClarify] = useState<{ question: string; threadId: string; originalQuestion: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listTenants()
      .then((names) => {
        setTenants(names);
        if (names.length > 0) setTenant(names[0]);
      })
      .catch(() => setTenants([]));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, pendingClarify]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || loading) return;
    setInput("");
    setLoading(true);

    try {
      if (pendingClarify) {
        const response = await resumeWithAnswer(pendingClarify.threadId, question);
        setPendingClarify(null);
        appendResolvedTurn(pendingClarify.originalQuestion, response);
      } else {
        const response = await askQuestion(question, tenant);
        if (response.clarification_question) {
          setPendingClarify({ question: response.clarification_question, threadId: response.thread_id, originalQuestion: question });
          setTurns((prev) => [...prev, { question, clarification: { question: response.clarification_question!, threadId: response.thread_id } }]);
        } else {
          appendResolvedTurn(question, response);
        }
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Request failed";
      setTurns((prev) => [...prev, { question, error: message }]);
      setPendingClarify(null);
    } finally {
      setLoading(false);
    }
  }

  function appendResolvedTurn(question: string, response: Awaited<ReturnType<typeof askQuestion>>) {
    setTurns((prev) => [
      ...prev,
      {
        question,
        answer: { sql: response.sql, rows: response.rows, confidence: response.confidence, traceId: response.trace_id },
      },
    ]);
  }

  return (
    <main className="chat-page">
      <header className="chat-header">
        <h1>ERP Analyst</h1>
        <TenantSwitcher tenants={tenants} selected={tenant} onChange={setTenant} />
      </header>

      <div className="chat-transcript">
        {turns.length === 0 && (
          <p className="chat-empty">
            Ask something like &ldquo;which supplier&apos;s hides gave the worst yield last quarter?&rdquo;
          </p>
        )}
        {turns.map((turn, i) => (
          <div className="chat-turn" key={i}>
            <div className="chat-bubble chat-bubble-question">{turn.question}</div>
            {turn.clarification && <div className="chat-bubble chat-bubble-clarify">{turn.clarification.question}</div>}
            {turn.error && <div className="chat-bubble chat-bubble-error">{turn.error}</div>}
            {turn.answer && (
              <div className="chat-bubble chat-bubble-answer">
                <div className="chat-answer-meta">
                  {turn.answer.confidence && <ConfidenceBadge confidence={turn.answer.confidence} />}
                  <FeedbackButtons traceId={turn.answer.traceId} />
                </div>
                {turn.answer.rows !== null && turn.answer.rows !== undefined ? (
                  <ResultView rows={turn.answer.rows} />
                ) : (
                  <p className="result-empty">No rows — see the SQL for what was tried.</p>
                )}
                {turn.answer.sql && <SqlView sql={turn.answer.sql} />}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <form className="chat-input-row" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={pendingClarify ? "Answer the clarifying question…" : "Ask a question about this tenant's ERP data…"}
          disabled={loading || !tenant}
        />
        <button type="submit" disabled={loading || !input.trim() || !tenant}>
          {loading ? "Thinking…" : "Send"}
        </button>
      </form>
    </main>
  );
}
