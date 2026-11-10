"use client";

import { useState } from "react";

export function SqlView({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="sql-view">
      <button type="button" className="sql-view-toggle" onClick={() => setOpen((v) => !v)}>
        {open ? "Hide SQL" : "Show SQL"}
      </button>
      {open && <pre className="sql-view-code">{sql}</pre>}
    </div>
  );
}
