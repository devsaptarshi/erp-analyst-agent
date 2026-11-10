"use client";

export function TenantSwitcher({
  tenants,
  selected,
  onChange,
}: {
  tenants: string[];
  selected: string;
  onChange: (tenant: string) => void;
}) {
  return (
    <label className="tenant-switcher">
      Tenant:
      <select value={selected} onChange={(e) => onChange(e.target.value)}>
        {tenants.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
    </label>
  );
}
