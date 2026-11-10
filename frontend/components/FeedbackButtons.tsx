"use client";

import { useState } from "react";
import { sendFeedback } from "@/lib/api";

export function FeedbackButtons({ traceId }: { traceId: string }) {
  const [voted, setVoted] = useState<"up" | "down" | null>(null);

  async function vote(choice: "up" | "down") {
    setVoted(choice); // optimistic — this is a demo feedback signal, not a critical write
    try {
      await sendFeedback(traceId, choice);
    } catch {
      setVoted(null);
    }
  }

  return (
    <div className="feedback-buttons">
      <button type="button" aria-pressed={voted === "up"} onClick={() => vote("up")} disabled={voted !== null}>
        👍
      </button>
      <button type="button" aria-pressed={voted === "down"} onClick={() => vote("down")} disabled={voted !== null}>
        👎
      </button>
      {voted && <span className="feedback-thanks">Thanks for the feedback</span>}
    </div>
  );
}
