import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { api } from "../lib/api";
import { cx, dateTime, duration, money } from "../lib/format";
import { SITES } from "../lib/wizard";
import type { Run, RunSummary, Usage, UsageCounts } from "../lib/types";
import { Badge, type Tone } from "./Badge";

const SITE_NAMES: Record<string, string> = Object.fromEntries(SITES.map((x) => [x.key, x.name]));

const STATUS_TONE: Record<string, Tone> = {
  queued: "gray",
  running: "blue",
  succeeded: "green",
  partial: "amber",
  failed: "red",
  cancelled: "gray",
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
        <p className="text-sm text-stone-500">
          Each run searches every county, then checks the tracked listings the searches didn't show.
        </p>
      </div>
      <div className="card divide-y divide-stone-100 dark:divide-stone-800">
        {data.map((run) => (
          <div key={run.id}>
            <button
              className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-sand-50 sm:items-center dark:hover:bg-stone-800/40"
              onClick={() => setOpen(open === run.id ? null : run.id)}
            >
              <ChevronRight
                size={16}
                className={cx("mt-1 shrink-0 text-stone-400 transition sm:mt-0", open === run.id && "rotate-90")}
              />
              <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-1">
                <Badge tone={STATUS_TONE[run.status]}>{run.status}</Badge>
                <span className="font-medium">{dateTime(run.started_at ?? run.created_at)}</span>
                <span className="text-sm text-stone-500">
                  {run.trigger}
                  {run.finished_at && ` · ${duration(run.started_at, run.finished_at)}`}
                </span>
                {/* Its own line on phones; pushed to the right on wider screens. */}
                <span className="w-full text-sm text-stone-600 sm:ml-auto sm:w-auto dark:text-stone-400">
                  {headline(run)}
                </span>
              </span>
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
    if (run.stopping) return "Stopping…";
    const p = s.progress;
    if (!p) return "Starting…";
    return p.phase === "recheck"
      ? `Checking listings ${p.done}/${p.total}`
      : p.phase === "reread"
        ? `Re-reading listings ${p.done}/${p.total}`
        : `Searching ${p.current} (${p.done + 1}/${p.total})`;
  }
  const parts = [
    ...(run.status === "cancelled" ? ["Stopped early"] : []),
    `${s.added?.length ?? 0} added`,
    `${s.removed?.length ?? 0} removed`,
    `${s.rejected?.length ?? 0} rejected`,
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
    <div className="grid grid-cols-1 gap-4 bg-sand-50/60 px-4 py-4 text-sm sm:px-10 md:grid-cols-2 dark:bg-stone-900/40">
      <Section title="Added" items={s.added} />
      <Section title="Removed" items={s.removed?.map((r) => `${r.listing} — ${r.reason}`)} />
      <Section
        title="Price changes"
        items={s.price_changes?.map((p) => `${p.listing}: ${money(p.old)} → ${money(p.new)}`)}
      />
      <Section title="Back on market" items={s.relisted} />
      <Section title="Rejected" items={s.rejected?.map((r) => `${r.listing} — ${r.reason}`)} />
      <Section
        title="Status changes"
        items={s.status_changes?.map((c) => `${c.listing}: ${c.old} → ${c.new}`.replaceAll("contingent", "under contract"))}
      />
      <Section title="Skipped (excluded)" items={s.skipped_excluded} />
      <Section title="Regions not checked" items={s.skipped_regions} tone="amber" />
      <Section title="Errors" items={s.errors} tone="red" />
      {s.sites && Object.keys(s.sites).length > 0 && (
        <div>
          <h4 className="mb-1 font-medium">Listing sites</h4>
          <ul className="space-y-0.5 text-stone-600 dark:text-stone-400">
            {Object.entries(s.sites).map(([key, t]) => (
              <li key={key}>
                <span className="font-medium text-stone-800 dark:text-stone-200">{SITE_NAMES[key] ?? key}</span>:{" "}
                used for {t.used} {t.used === 1 ? "county" : "counties"}
                {t.blocked > 0 && <span className="text-amber-700 dark:text-amber-400"> · blocked in {t.blocked}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {s.email && (
        <div>
          <h4 className="mb-1 font-medium">Email</h4>
          <p className={cx("text-stone-600 dark:text-stone-400", s.email.startsWith("Email not sent") && "text-amber-700 dark:text-amber-400")}>
            {s.email}
          </p>
        </div>
      )}
      {s.checks && (
        <div>
          <h4 className="mb-1 font-medium">Tracked listings</h4>
          <p className="text-stone-600 dark:text-stone-400">
            {s.checks.seen_in_search} confirmed during the county searches · {s.checks.status_checked} quick
            checks · {s.checks.skipped_recent} skipped (checked in the last few days) · {s.checks.reread} re-read
            for condition
          </p>
        </div>
      )}
      {s.usage && <UsageSection usage={s.usage} regions={s.region_stats} />}
      {data.log && (
        <details className="md:col-span-2">
          <summary className="cursor-pointer font-medium">Log</summary>
          <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-stone-900 p-3 text-xs text-stone-100">{data.log}</pre>
        </details>
      )}
    </div>
  );
}

const MODEL_NAMES: Record<string, string> = {
  "claude-opus-5": "Opus 5",
  "claude-opus-5-5": "Opus 5.5",
  "claude-sonnet-5": "Sonnet 5",
  "claude-haiku-4-5": "Haiku 4.5",
  "claude-fable-5-1": "Fable 5.1",
};

function usd(n: number | null | undefined) {
  if (n == null) return "?";
  return n < 0.01 ? "<$0.01" : `$${n.toFixed(2)}`;
}

function tokensK(u: UsageCounts) {
  return `${Math.round((u.input_tokens + u.output_tokens + (u.cache_read_tokens ?? 0)) / 1000)}k tokens`;
}

function UsageSection({ usage, regions }: { usage: Usage; regions?: RunSummary["region_stats"] }) {
  const models = Object.entries(usage.by_model ?? {});
  const counties = Object.entries(regions ?? {});
  return (
    <div className="min-w-0 md:col-span-2">
      <h4 className="mb-1 font-medium">
        Usage{usage.est_cost_usd != null && <span className="font-normal text-stone-500"> · about {usd(usage.est_cost_usd)}</span>}
      </h4>
      <p className="text-stone-600 dark:text-stone-400">
        {usage.calls} model calls · {usage.web_fetches} pages opened · {usage.web_searches} web searches · {tokensK(usage)}
      </p>
      {models.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-stone-600 dark:text-stone-400">
          {models.map(([model, u]) => (
            <li key={model}>
              <span className="font-medium text-stone-800 dark:text-stone-200">{MODEL_NAMES[model] ?? model}</span>:{" "}
              {u.calls} calls · {tokensK(u)} · {usd(u.est_cost_usd)}
            </li>
          ))}
        </ul>
      )}
      {counties.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-stone-600 dark:text-stone-400">By county</summary>
          <div className="mt-1 overflow-x-auto">
            <table className="w-full min-w-[420px] text-left text-xs">
              <thead className="text-stone-500">
                <tr>
                  <th className="py-1 pr-3 font-medium">County</th>
                  <th className="py-1 pr-3 font-medium">New</th>
                  <th className="py-1 pr-3 font-medium">Tracked seen</th>
                  <th className="py-1 pr-3 font-medium">Pages (budget)</th>
                  <th className="py-1 font-medium">Cost</th>
                </tr>
              </thead>
              <tbody className="text-stone-700 dark:text-stone-300">
                {counties.map(([label, r]) => (
                  <tr key={label} className="border-t border-stone-100 dark:border-stone-800">
                    <td className="py-1 pr-3">{label}</td>
                    <td className="py-1 pr-3 tabular-nums">{r.added}</td>
                    <td className="py-1 pr-3 tabular-nums">{r.seen_tracked}</td>
                    <td className="py-1 pr-3 tabular-nums">
                      {r.usage?.web_fetches ?? "?"} ({r.fetch_budget})
                    </td>
                    <td className="py-1 tabular-nums">{usd(r.usage?.est_cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
      <p className="mt-1 text-xs text-stone-400">Estimate from model tokens; web search and page-fetch fees not included.</p>
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
