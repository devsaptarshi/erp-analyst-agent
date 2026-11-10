"use client";

type Row = Record<string, unknown>;

function isNumeric(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

// Picks a chart over a table only for the shape a bar chart actually
// helps with: a handful of rows, one label column and exactly one numeric
// column — e.g. "yield by supplier". Anything messier (multiple numeric
// columns, too many rows, no obvious label) falls back to a plain table,
// which is always a correct rendering even if less visual.
function pickChartColumns(rows: Row[]): { labelKey: string; valueKey: string } | null {
  if (rows.length === 0 || rows.length > 12) return null;
  const keys = Object.keys(rows[0]);
  const numericKeys = keys.filter((k) => rows.every((r) => isNumeric(r[k])));
  const labelKeys = keys.filter((k) => !numericKeys.includes(k));
  if (numericKeys.length !== 1 || labelKeys.length !== 1) return null;
  return { labelKey: labelKeys[0], valueKey: numericKeys[0] };
}

function BarChart({ rows, labelKey, valueKey }: { rows: Row[]; labelKey: string; valueKey: string }) {
  const max = Math.max(...rows.map((r) => Math.abs(r[valueKey] as number)), 1);
  return (
    <div className="bar-chart" role="img" aria-label={`Bar chart of ${valueKey} by ${labelKey}`}>
      {rows.map((row, i) => {
        const value = row[valueKey] as number;
        const widthPct = (Math.abs(value) / max) * 100;
        return (
          <div className="bar-chart-row" key={i}>
            <span className="bar-chart-label">{String(row[labelKey])}</span>
            <div className="bar-chart-track">
              <div className="bar-chart-fill" style={{ width: `${widthPct}%` }} />
            </div>
            <span className="bar-chart-value">{value}</span>
          </div>
        );
      })}
    </div>
  );
}

function Table({ rows }: { rows: Row[] }) {
  const columns = Object.keys(rows[0] ?? {});
  return (
    <table className="result-table">
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c}>{c}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i}>
            {columns.map((c) => (
              <td key={c}>{String(row[c])}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ResultView({ rows }: { rows: Row[] }) {
  if (rows.length === 0) return <p className="result-empty">No matching rows.</p>;

  const chartColumns = pickChartColumns(rows);
  return (
    <div className="result-view">
      {chartColumns && <BarChart rows={rows} labelKey={chartColumns.labelKey} valueKey={chartColumns.valueKey} />}
      <Table rows={rows} />
    </div>
  );
}
