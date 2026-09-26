import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Loader2, MapPin, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { cx } from "../lib/format";
import type { Anchor, Criteria, Region } from "../lib/types";
import { COUNTRY, DRIVE_TIMES, placeCode } from "../lib/wizard";
import { ChipGroup, hoursLabel } from "./wizard/ui";

/** "St. Clair County" and "St Clair" compare equal. */
const countyKey = (r: { name: string; state: string }) =>
  `${r.name.toLowerCase().replace(/county/g, "").replace(/[^a-z0-9]/g, "")}|${r.state.toUpperCase()}`;

interface Proposal {
  add: (Region & { est_drive_hours: number; est_drive_km?: number | null; note: string; keep: boolean })[];
  drop: (Region & { keep: boolean })[];
}

/** Search locations and their maximum drive times, with a way to refresh the counties. */
export function LocationsPanel({
  criteria: c,
  savedAnchors,
  setC,
}: {
  criteria: Criteria;
  savedAnchors: Anchor[];
  setC: (patch: Partial<Criteria>) => void;
}) {
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const changed = JSON.stringify(c.anchors) !== JSON.stringify(savedAnchors);
  const setAnchor = (i: number, patch: Partial<Anchor>) =>
    setC({ anchors: c.anchors.map((a, j) => (j === i ? { ...a, ...patch } : a)) });

  const suggest = useMutation({
    mutationFn: () =>
      api.suggestRegions({
        country: c.country,
        anchors: c.anchors.map((a) => ({ name: a.name.trim(), max_drive_hours: a.max_drive_hours })),
        property_types: c.property_types,
        min_acres: c.min_acres,
        max_price: c.max_price,
      }),
    onSuccess: (out) => {
      // Map Claude's codes back to this search's codes (by the name we sent, else by order).
      const codeFor = new Map<string, string>();
      out.anchors.forEach((ra, i) => {
        const mine = c.anchors.find((a) => a.name.trim() === ra.input) ?? c.anchors[i];
        if (mine) codeFor.set(ra.code, mine.code);
      });
      const suggested = out.regions
        .filter((r) => codeFor.has(r.anchor))
        .map((r) => ({ ...r, anchor: codeFor.get(r.anchor)! }));
      const have = new Set(c.regions.map(countyKey));
      const want = new Set(suggested.map(countyKey));
      setProposal({
        add: suggested
          .filter((r) => !have.has(countyKey(r)))
          .map((r) => ({ ...r, redfin_county_id: null, keep: true })),
        drop: c.regions.filter((r) => !want.has(countyKey(r))).map((r) => ({ ...r, keep: true })),
      });
    },
  });

  // Recalculate automatically when a location or drive time changes (after typing pauses).
  const anchorsKey = JSON.stringify(c.anchors.map((a) => [a.name.trim(), a.max_drive_hours]));
  const savedKey = JSON.stringify(savedAnchors.map((a) => [a.name.trim(), a.max_drive_hours]));
  const lastAsked = useRef(savedKey);
  useEffect(() => {
    if (anchorsKey === lastAsked.current || c.anchors.some((a) => !a.name.trim())) return;
    const t = setTimeout(() => {
      lastAsked.current = anchorsKey;
      suggest.mutate();
    }, 900);
    return () => clearTimeout(t);
  }, [anchorsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const apply = () => {
    if (!proposal) return;
    const dropKeys = new Set(proposal.drop.filter((r) => r.keep).map(countyKey));
    const added = proposal.add
      .filter((r) => r.keep)
      .map(({ name, state, anchor, redfin_county_id }) => ({ name, state, anchor, redfin_county_id }));
    setC({ regions: [...c.regions.filter((r) => !dropKeys.has(countyKey(r))), ...added] });
    setProposal(null);
  };

  return (
    <section className="card space-y-4 p-5">
      <div>
        <h3 className="font-semibold">Where you're searching from</h3>
        <p className="text-sm text-stone-500">
          Each location and the longest drive you'd accept from it. Listings farther than that are left out.
        </p>
      </div>

      {c.anchors.map((a, i) => {
        const options = DRIVE_TIMES.includes(a.max_drive_hours)
          ? DRIVE_TIMES
          : [...DRIVE_TIMES, a.max_drive_hours].sort((x, y) => x - y);
        return (
          <div key={i} className="space-y-3 rounded-xl border border-stone-200 p-3 sm:p-4 dark:border-stone-800">
            <div className="flex items-end gap-2">
              <label className="block min-w-0 flex-1 space-y-1">
                <span className="text-sm font-medium">Location</span>
                <div className="relative">
                  <MapPin size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400" />
                  <input
                    className="input pl-9"
                    placeholder={`Address, ${COUNTRY[c.country].postal}, or landmark`}
                    value={a.name}
                    onChange={(e) => setAnchor(i, { name: e.target.value })}
                  />
                </div>
              </label>
              <label className="block w-16 shrink-0 space-y-1 sm:w-24">
                <span className="text-sm font-medium">Label</span>
                <input
                  className="input uppercase"
                  value={a.code}
                  onChange={(e) => setAnchor(i, { code: e.target.value.toUpperCase() })}
                />
              </label>
              {c.anchors.length > 1 && (
                <button type="button" className="btn-ghost p-2" title="Remove location"
                  onClick={() => setC({ anchors: c.anchors.filter((_, j) => j !== i) })}>
                  <Trash2 size={16} />
                </button>
              )}
            </div>
            <ChipGroup
              label="Maximum drive time"
              value={a.max_drive_hours}
              onChange={(v) => setAnchor(i, { max_drive_hours: v })}
              options={options.map((h) => ({ value: h, label: hoursLabel(h) }))}
            />
          </div>
        );
      })}

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="btn-outline"
          onClick={() => setC({ anchors: [...c.anchors, { code: placeCode(`Location ${c.anchors.length + 1}`), name: "", max_drive_hours: 1 }] })}>
          <Plus size={16} /> Add location
        </button>
        <button type="button" className="btn-ghost" disabled={suggest.isPending || c.anchors.some((a) => !a.name.trim())}
          onClick={() => suggest.mutate()}>
          {suggest.isPending ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          Update {COUNTRY[c.country].areas} for these drive times
        </button>
      </div>

      {suggest.isPending && (
        <p className="flex items-center gap-2 text-sm text-stone-600 dark:text-stone-300">
          <Loader2 size={16} className="animate-spin text-pine-600" /> Working out which {COUNTRY[c.country].areas} are within
          your drive times…
        </p>
      )}
      {changed && !proposal && !suggest.isPending && suggest.isError && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          Your {COUNTRY[c.country].areas} were picked for the previous locations or drive times. Try{" "}
          <span className="font-medium">Update {COUNTRY[c.country].areas}</span> again, or edit the list below.
        </div>
      )}
      {suggest.isError && (
        <p className="text-sm text-rose-600">
          Couldn't suggest {COUNTRY[c.country].areas} ({(suggest.error as Error).message}). You can still edit the list below.
        </p>
      )}

      {proposal && (
        <div className="space-y-3 rounded-xl border border-sky-200 bg-sky-50/60 p-4 text-sm dark:border-sky-900 dark:bg-sky-950/30">
          {proposal.add.length === 0 && proposal.drop.length === 0 ? (
            <p>Your {COUNTRY[c.country].areas} already match these drive times.</p>
          ) : (
            <>
              {proposal.add.length > 0 && (
                <ProposalList
                  title={`Add ${proposal.add.length} ${proposal.add.length === 1 ? COUNTRY[c.country].area : COUNTRY[c.country].areas} now within reach`}
                  rows={proposal.add.map((r) => ({ label: `${r.name}, ${r.state}`, detail: `~${hoursLabel(r.est_drive_hours)}${r.est_drive_km != null ? ` · ${Math.round(r.est_drive_km)} km` : ""} · ${r.note}`, keep: r.keep }))}
                  onToggle={(i) => setProposal({ ...proposal, add: proposal.add.map((r, j) => (j === i ? { ...r, keep: !r.keep } : r)) })}
                />
              )}
              {proposal.drop.length > 0 && (
                <ProposalList
                  title={`Drop ${proposal.drop.length} ${proposal.drop.length === 1 ? COUNTRY[c.country].area : COUNTRY[c.country].areas} outside these drive times`}
                  rows={proposal.drop.map((r) => ({ label: `${r.name}, ${r.state}`, detail: `near ${r.anchor}`, keep: r.keep }))}
                  onToggle={(i) => setProposal({ ...proposal, drop: proposal.drop.map((r, j) => (j === i ? { ...r, keep: !r.keep } : r)) })}
                />
              )}
            </>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={() => setProposal(null)}>Cancel</button>
            {(proposal.add.length > 0 || proposal.drop.length > 0) && (
              <button type="button" className="btn-primary" onClick={apply}>Apply to {COUNTRY[c.country].area} list</button>
            )}
          </div>
          <p className="text-xs text-stone-500">Nothing is saved until you click Save changes.</p>
        </div>
      )}
    </section>
  );
}

function ProposalList({
  title,
  rows,
  onToggle,
}: {
  title: string;
  rows: { label: string; detail: string; keep: boolean }[];
  onToggle: (i: number) => void;
}) {
  return (
    <div>
      <div className="mb-1 font-medium">{title}</div>
      <ul className="space-y-1">
        {rows.map((r, i) => (
          <li key={i}>
            <label className="flex items-center gap-2">
              <input type="checkbox" className="size-4 accent-pine-600" checked={r.keep} onChange={() => onToggle(i)} />
              <span className={cx(!r.keep && "text-stone-400 line-through")}>{r.label}</span>
              <span className="text-stone-500">{r.detail}</span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
