import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Car, CircleSlash, ExternalLink, Plus, Trees } from "lucide-react";
import { api } from "../lib/api";
import { driveLabel, money, num, shortDate } from "../lib/format";
import type { Listing } from "../lib/types";
import { Badge } from "./Badge";
import { IncludeDialog } from "./IncludeDialog";

export function RejectedView({ profileId }: { profileId: number }) {
  const qc = useQueryClient();
  const { data = [], isLoading } = useQuery({
    queryKey: ["listings", profileId, "rejected"],
    queryFn: () => api.listings(profileId, "rejected"),
  });
  const [including, setIncluding] = useState<Listing | null>(null);
  const include = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) => api.include(id, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["listings", profileId] });
      qc.invalidateQueries({ queryKey: ["stats", profileId] });
      qc.invalidateQueries({ queryKey: ["feedback", profileId] });
    },
  });
  const sorted = [...data].sort((a, b) => (b.last_checked ?? "").localeCompare(a.last_checked ?? ""));

  return (
    <div className="space-y-5">
      <div>
        <h2 className="font-display text-xl font-semibold">Rejected by the agent</h2>
        <p className="text-sm text-stone-500">
          Listings the agent looked at and left out, and why. If it got one wrong, click{" "}
          <span className="font-medium">Include anyway</span> and tell it why. It uses your reasons on
          future searches.
        </p>
      </div>

      {isLoading ? (
        <p className="text-stone-500">Loading…</p>
      ) : sorted.length === 0 ? (
        <div className="card p-10 text-center text-stone-500">
          Nothing rejected yet. Listings the agent rules out will show up here after the next search.
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {sorted.map((l) => (
            <RejectedCard key={l.id} listing={l} onInclude={() => setIncluding(l)} />
          ))}
        </div>
      )}

      {including && (
        <IncludeDialog
          listing={including}
          onCancel={() => setIncluding(null)}
          onConfirm={(reason) => {
            include.mutate({ id: including.id, reason });
            setIncluding(null);
          }}
        />
      )}
    </div>
  );
}

function RejectedCard({ listing: l, onInclude }: { listing: Listing; onInclude: () => void }) {
  return (
    <article className="card flex flex-col overflow-hidden">
      <div className="flex items-start justify-between gap-3 px-4 pt-4">
        <div className="min-w-0">
          <span className="text-xl font-semibold tabular-nums text-stone-600 dark:text-stone-300">
            {money(l.price)}
          </span>
          <h3 className="mt-0.5 truncate font-medium" title={l.address}>
            {l.address}
          </h3>
          <p className="text-sm text-stone-500">
            {l.city}, {l.state}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <Badge tone="red">
            <CircleSlash size={12} /> Rejected
          </Badge>
          {l.market_status === "pending" && <Badge tone="amber">Pending</Badge>}
          {l.market_status === "contingent" && <Badge tone="amber">Under contract</Badge>}
        </div>
      </div>

      <div className="mx-4 mt-3 rounded-lg border border-rose-200 bg-rose-50/70 px-3 py-2 text-sm text-rose-900 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-100">
        <div className="text-xs font-semibold uppercase tracking-wide opacity-80">Why it was left out</div>
        <p className="mt-0.5 leading-relaxed">{l.reject_reason || "Didn't meet your search rules."}</p>
      </div>

      <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 px-4 text-sm text-stone-600 dark:text-stone-400">
        {l.beds != null && (
          <span>
            <span className="font-medium text-stone-800 dark:text-stone-200">{num(l.beds)}</span> beds ·{" "}
            <span className="font-medium text-stone-800 dark:text-stone-200">{num(l.baths)}</span> baths
          </span>
        )}
        <span className="flex items-center gap-1.5">
          <Trees size={15} className="text-stone-400" />
          <span className="font-medium text-stone-800 dark:text-stone-200">{num(l.acres, 2)}</span> acres
        </span>
        {l.drive_hours != null && (
          <span className="flex items-center gap-1.5">
            <Car size={15} className="text-stone-400" />
            <span className="font-medium text-stone-800 dark:text-stone-200">{driveLabel(l.drive_hours, l.drive_km)}</span> to{" "}
            {l.anchor}
          </span>
        )}
      </dl>

      {l.condition_notes && (
        <p className="mt-3 line-clamp-3 px-4 text-sm leading-relaxed text-stone-600 dark:text-stone-400">
          {l.condition_notes}
        </p>
      )}

      <div className="mt-auto px-4 pt-3 text-xs text-stone-400">Last seen {shortDate(l.last_checked)}</div>

      <div className="mt-3 flex flex-wrap items-center gap-0.5 border-t border-stone-100 px-1.5 py-2 dark:border-stone-800">
        {l.url && (
          <a href={l.url} target="_blank" rel="noreferrer" className="btn-ghost px-2 py-1.5">
            <ExternalLink size={15} />
            Listing
          </a>
        )}
        <button onClick={onInclude} className="btn ml-auto px-2 py-1.5 text-pine-700 hover:bg-pine-50 dark:text-pine-300 dark:hover:bg-pine-900/40">
          <Plus size={15} />
          Include anyway
        </button>
      </div>
    </article>
  );
}
