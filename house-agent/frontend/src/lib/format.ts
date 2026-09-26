const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

export const money = (n: number | null | undefined) => (n == null ? "—" : usd.format(n));

export const num = (n: number | null | undefined, digits = 1) =>
  n == null ? "—" : Number(n.toFixed(digits)).toString();

export function shortDate(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = iso.length === 10 ? new Date(iso + "T12:00:00") : new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function dateTime(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function duration(start: string | null, end: string | null) {
  if (!start || !end) return "";
  const s = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

/** "1.4 hr" or, when a distance is known (Canadian searches), "1.4 hr · 120 km". */
export function driveLabel(hours: number | null | undefined, km?: number | null) {
  if (hours == null) return "—";
  const h = `${Number(hours.toFixed(1))} hr`;
  return km != null ? `${h} · ${Math.round(km)} km` : h;
}
