import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { api } from "../lib/api";
import { cx, dateTime, duration, money } from "../lib/format";
import type { Run } from "../lib/types";
import { Badge, type Tone } from "./Badge";

const STATUS_TONE: Record<string, Tone> = {
  queued: "gray",
  running: "blue",
  succeeded: "green",
  partial: "amber",
  failed: "red",
};

export function RunsView({ profileId }: { profileId: number }) {
  const { data = [] } = useQuery({
    queryKey: ["runs", profileId],
    queryFn: () => api.runs(profileId),
    refetchInterval: (q) =>
      q.state.data?.some((r) => r.status === "running" || r.status === "queued") ? 4000 : false,
  });
  const [open, setOpen] = useState<number | null>(null);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="font-display text-xl font-semibold">Search runs</h2>
        <p className="text-sm text-stone-500">Each run re-checks tracked houses, then searches every region.</p>
      </div>
      <div className="card divide-y divide-stone-100 dark:divide-stone-800">
        {data.map((run) => (
          <div key={run.id}>
            <button
              className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-left hover:bg-sand-50 dark:hover:bg-stone-800/40"
              onClick={() => setOpen(open === run.id ? null : run.id)}
            >
              <ChevronRight size={16} className={cx("text-stone-400 transition", open === run.id && "rotate-90")} />
              <Badge tone={STATUS_TONE[run.status]}>{run.status}</Badge>
              <span className="font-medium">{dateTime(run.started_at ?? run.created_at)}</span>
              <span className="text-sm text-stone-500">
                {run.trigger}
                {run.finished_at && ` · ${duration(run.started_at, run.finished_at)}`}
              </span>
              <span className="ml-auto text-sm text-stone-600 dark:text-stone-400">{headline(run)}</span>
            </button>
            {open === run.id && <RunDetail id={run.id} />}
          </div>
        ))}
        {!data.length && <p className="px-4 py-8 text-center text-stone-500">No runs yet.</p>}
      </div>
    </div>
  );
}

function headline(run: Run) {
  const s = run.summary;
  if (run.trigger === "import") return `Imported ${s.listings_imported ?? 0} listings`;
  if (run.status === "running" || run.status === "queued") {
    const p = s.progress;
    if (!p) return "Starting…";
    return p.phase === "recheck"
      ? `Re-checking listings ${p.done}/${p.total}`
      : `Searching ${p.current} (${p.done + 1}/${p.total})`;
  }
  const parts = [
    `${s.added?.length ?? 0} added`,
    `${s.removed?.length ?? 0} removed`,
    `${s.price_changes?.length ?? 0} price changes`,
  ];
  return parts.join(" · ");
}

function RunDetail({ id }: { id: number }) {
  const { data } = useQuery({
    queryKey: ["run", id],
    queryFn: () => api.run(id),
    refetchInterval: (q) =>
      q.state.data?.status === "running" || q.state.data?.status === "queued" ? 3000 : false,
  });
  if (!data) return <div className="px-10 pb-4 text-sm text-stone-500">Loading…</div>;
  const s = data.summary;
  return (
    <div className="grid gap-4 bg-sand-50/60 px-10 py-4 text-sm md:grid-cols-2 dark:bg-stone-900/40">
      <Section title="Added" items={s.added} />
      <Section title="Removed" items={s.removed?.map((r) => `${r.listing} — ${r.reason}`)} />
      <Section
        title="Price changes"
        items={s.price_changes?.map((p) => `${p.listing}: ${money(p.old)} → ${money(p.new)}`)}
      />
      <Section title="Back on market" items={s.relisted} />
      <Section title="Skipped (excluded)" items={s.skipped_excluded} />
      <Section title="Regions not checked" items={s.skipped_regions} tone="amber" />
      <Section title="Errors" items={s.errors} tone="red" />
      {s.usage && (
        <div>
          <h4 className="mb-1 font-medium">Usage</h4>
          <p className="text-stone-600 dark:text-stone-400">
            {s.usage.calls} model calls · {s.usage.web_fetches} page fetches · {s.usage.web_searches} searches ·{" "}
            {Math.round((s.usage.input_tokens + s.usage.output_tokens) / 1000)}k tokens
          </p>
        </div>
      )}
      {data.log && (
        <details className="md:col-span-2">
          <summary className="cursor-pointer font-medium">Log</summary>
          <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-stone-900 p-3 text-xs text-stone-100">{data.log}</pre>
        </details>
      )}
    </div>
  );
}

function Section({ title, items, tone }: { title: string; items?: string[]; tone?: "amber" | "red" }) {
  if (!items?.length) return null;
  return (
    <div>
      <h4 className={cx("mb-1 font-medium", tone === "amber" && "text-amber-700", tone === "red" && "text-rose-700")}>
        {title} ({items.length})
      </h4>
      <ul className="list-disc space-y-0.5 pl-5 text-stone-600 dark:text-stone-400">
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </div>
  );
}
