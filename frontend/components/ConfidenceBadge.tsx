const LABELS: Record<string, string> = {
  high: "High confidence — valid on the first try",
  medium: "Medium confidence — needed a repair or a second look",
  low: "Low confidence — could not produce a safe answer",
};

export function ConfidenceBadge({ confidence }: { confidence: "high" | "medium" | "low" }) {
  return (
    <span className={`confidence-badge confidence-${confidence}`} title={LABELS[confidence]}>
      {confidence}
    </span>
  );
}
