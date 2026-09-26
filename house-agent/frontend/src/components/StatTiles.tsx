import type { Stats } from "../lib/types";
import { cx } from "../lib/format";

interface Tile {
  label: string;
  value: number;
  hint?: string;
  accent?: string;
}

export function StatTiles({ stats }: { stats: Stats | undefined }) {
  const tiles: Tile[] = [
    { label: "Active listings", value: stats?.active ?? 0, hint: anchorHint(stats) },
    { label: "New this week", value: stats?.new_this_run ?? 0, accent: "text-sky-700 dark:text-sky-300" },
    { label: "Price changes", value: stats?.price_changes_last_run ?? 0, hint: "since last run" },
    { label: "Removed", value: stats?.removed_last_run ?? 0, hint: "sold, pending or gone" },
    { label: "To review", value: stats?.unreviewed ?? 0, accent: "text-amber-700 dark:text-amber-300" },
  ];
  return (
    <div className="grid grid-cols-3 gap-2 sm:gap-3 lg:grid-cols-5">
      {tiles.map((t) => (
        <div key={t.label} className="card min-w-0 px-3 py-2 sm:px-4 sm:py-3">
          <div className="text-[11px] leading-tight font-medium uppercase tracking-wide text-stone-500 sm:text-xs dark:text-stone-400">
            {t.label}
          </div>
          <div className={cx("mt-1 text-xl font-semibold tabular-nums sm:text-2xl", t.accent)}>{t.value}</div>
          {t.hint && <div className="mt-0.5 hidden truncate text-xs text-stone-500 sm:block">{t.hint}</div>}
        </div>
      ))}
    </div>
  );
}

function anchorHint(stats: Stats | undefined) {
  if (!stats) return undefined;
  return Object.entries(stats.by_anchor)
    .sort()
    .map(([k, v]) => `${k} ${v}`)
    .join(" · ");
}
