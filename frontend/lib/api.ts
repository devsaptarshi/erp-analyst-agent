// Thin client for the erp-analyst-agent FastAPI backend
// (src/erp_analyst/api/app.py). No SDK, just fetch — the API surface is
// small enough that a generated client would be more ceremony than value.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type ChatResponse = {
  trace_id: string;
  thread_id: string;
  answer: string | null;
  sql: string | null;
  rows: Record<string, unknown>[] | null;
  confidence: "high" | "medium" | "low" | null;
  clarification_question: string | null;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new ApiError(response.status, detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export function askQuestion(question: string, tenantName: string, threadId?: string): Promise<ChatResponse> {
  return postJson<ChatResponse>("/chat", { question, tenant_name: tenantName, thread_id: threadId });
}

export function resumeWithAnswer(threadId: string, answer: string): Promise<ChatResponse> {
  return postJson<ChatResponse>("/chat/resume", { thread_id: threadId, answer });
}

export function sendFeedback(traceId: string, vote: "up" | "down"): Promise<void> {
  return postJson<void>("/feedback", { trace_id: traceId, vote });
}

export async function listTenants(): Promise<string[]> {
  const response = await fetch(`${API_URL}/tenants`);
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json() as Promise<string[]>;
}
