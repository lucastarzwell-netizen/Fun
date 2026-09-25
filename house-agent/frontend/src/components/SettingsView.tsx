import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Save, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { dateTime } from "../lib/format";
import type { Criteria, Profile, ProfileIn, Region } from "../lib/types";

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** "M H * * D" <-> {day, time}. Anything more complex is edited as raw cron. */
// day 7 = every day ("*")
function parseCron(cron: string): { day: number; time: string } | null {
  const m = cron.trim().match(/^(\d{1,2}) (\d{1,2}) \* \* ([0-6]|\*)$/);
  if (!m) return null;
  return {
    day: m[3] === "*" ? 7 : Number(m[3]),
    time: `${m[2].padStart(2, "0")}:${m[1].padStart(2, "0")}`,
  };
}

function toCron(day: number, time: string) {
  const [h, m] = time.split(":").map(Number);
  return `${m} ${h} * * ${day === 7 ? "*" : day}`;
}

const numOrNull = (v: string) => (v === "" ? null : Number(v));

export function SettingsView({ profile }: { profile: Profile }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<ProfileIn>(() => strip(profile));
  useEffect(() => setDraft(strip(profile)), [profile]);

  const save = useMutation({
    mutationFn: () => api.updateProfile(profile.id, draft),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profiles"] }),
  });

  const c = draft.criteria;
  const setC = (patch: Partial<Criteria>) => setDraft({ ...draft, criteria: { ...c, ...patch } });
  const setRegion = (i: number, patch: Partial<Region>) =>
    setC({ regions: c.regions.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  const simple = parseCron(draft.schedule_cron);
  // Profiles created with "Only when I ask" have no cron; give the toggle something to enable.
  useEffect(() => {
    if (draft.enabled && !draft.schedule_cron.trim()) setDraft((d) => ({ ...d, schedule_cron: "0 7 * * 5" }));
  }, [draft.enabled, draft.schedule_cron]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(strip(profile));

  return (
    <form
      className="space-y-6"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold">Search settings</h2>
          <p className="text-sm text-stone-500">What the agent looks for, where, and when.</p>
        </div>
        <div className="flex items-center gap-3">
          {save.isError && <span className="text-sm text-rose-600">{(save.error as Error).message}</span>}
          {save.isSuccess && !dirty && <span className="text-sm text-pine-600">Saved</span>}
          <button className="btn-primary" disabled={!dirty || save.isPending}>
            <Save size={16} /> Save changes
          </button>
        </div>
      </div>

      <Panel title="Basics">
        <Field label="Search name">
          <input className="input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Min price">
            <input type="number" step={5000} className="input" value={c.min_price ?? ""}
              onChange={(e) => setC({ min_price: numOrNull(e.target.value) })} />
          </Field>
          <Field label="Max price">
            <input type="number" step={5000} className="input" value={c.max_price ?? ""}
              onChange={(e) => setC({ max_price: numOrNull(e.target.value) })} />
          </Field>
          <Field label="Property types" hint="Comma-separated, e.g. house">
            <input className="input" value={c.property_types.join(", ")}
              onChange={(e) => setC({ property_types: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
          </Field>
          <Field label="Min acres">
            <input type="number" step={0.25} className="input" value={c.min_acres ?? ""}
              onChange={(e) => setC({ min_acres: numOrNull(e.target.value) })} />
          </Field>
          <Field label="Min beds">
            <input type="number" className="input" value={c.min_beds ?? ""}
              onChange={(e) => setC({ min_beds: numOrNull(e.target.value) })} />
          </Field>
          <Field label="Min baths">
            <input type="number" step={0.5} className="input" value={c.min_baths ?? ""}
              onChange={(e) => setC({ min_baths: numOrNull(e.target.value) })} />
          </Field>
        </div>
      </Panel>

      <Panel title="Schedule">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="size-4 accent-pine-600" checked={draft.enabled}
            onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />
          Run automatically
        </label>
        <div className="grid gap-4 sm:grid-cols-3">
          {!draft.schedule_cron.trim() ? null : simple ? (
            <>
              <Field label="Day">
                <select className="input" value={simple.day}
                  onChange={(e) => setDraft({ ...draft, schedule_cron: toCron(Number(e.target.value), simple.time) })}>
                  {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
                  <option value={7}>Every day</option>
                </select>
              </Field>
              <Field label="Time">
                <input type="time" className="input" value={simple.time}
                  onChange={(e) => setDraft({ ...draft, schedule_cron: toCron(simple.day, e.target.value) })} />
              </Field>
            </>
          ) : (
            <Field label="Cron expression" hint="minute hour day month weekday">
              <input className="input font-mono" value={draft.schedule_cron}
                onChange={(e) => setDraft({ ...draft, schedule_cron: e.target.value })} />
            </Field>
          )}
          <Field label="Time zone">
            <input className="input" value={draft.timezone}
              onChange={(e) => setDraft({ ...draft, timezone: e.target.value })} />
          </Field>
        </div>
        <p className="text-sm text-stone-500">
          Next run: {profile.enabled && profile.next_run_at ? dateTime(profile.next_run_at) : "not scheduled"}
        </p>
      </Panel>

      <Panel title="Anchors" hint="Places the search is centered on. Each listing gets a drive-time estimate to the nearest one.">
        {c.anchors.map((a, i) => (
          <div key={i} className="grid grid-cols-[5rem_1fr_7rem_auto] items-end gap-2">
            <Field label={i === 0 ? "Code" : undefined}>
              <input className="input uppercase" value={a.code}
                onChange={(e) => setC({ anchors: c.anchors.map((x, j) => (j === i ? { ...x, code: e.target.value.toUpperCase() } : x)) })} />
            </Field>
            <Field label={i === 0 ? "Name" : undefined}>
              <input className="input" value={a.name}
                onChange={(e) => setC({ anchors: c.anchors.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} />
            </Field>
            <Field label={i === 0 ? "Max drive (hr)" : undefined}>
              <input type="number" step={0.1} className="input" value={a.max_drive_hours}
                onChange={(e) => setC({ anchors: c.anchors.map((x, j) => (j === i ? { ...x, max_drive_hours: Number(e.target.value) } : x)) })} />
            </Field>
            <button type="button" className="btn-ghost p-2" title="Remove"
              onClick={() => setC({ anchors: c.anchors.filter((_, j) => j !== i) })}>
              <Trash2 size={16} />
            </button>
          </div>
        ))}
        <button type="button" className="btn-outline"
          onClick={() => setC({ anchors: [...c.anchors, { code: "", name: "", max_drive_hours: 2 }] })}>
          <Plus size={16} /> Add anchor
        </button>
      </Panel>

      <Panel title={`Regions (${c.regions.length})`} hint="Counties to search. With a Redfin county ID the agent opens that county's filtered results page directly; without one it searches the web.">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-stone-500">
              <tr>
                <th className="pb-2 pr-2">County</th>
                <th className="pb-2 pr-2 w-20">State</th>
                <th className="pb-2 pr-2 w-28">Anchor</th>
                <th className="pb-2 pr-2 w-32">Redfin ID</th>
                <th className="w-10" />
              </tr>
            </thead>
            <tbody>
              {c.regions.map((r, i) => (
                <tr key={i}>
                  <td className="py-1 pr-2"><input className="input py-1.5" value={r.name} onChange={(e) => setRegion(i, { name: e.target.value })} /></td>
                  <td className="py-1 pr-2"><input className="input py-1.5 uppercase" maxLength={2} value={r.state} onChange={(e) => setRegion(i, { state: e.target.value.toUpperCase() })} /></td>
                  <td className="py-1 pr-2">
                    <select className="input py-1.5" value={r.anchor} onChange={(e) => setRegion(i, { anchor: e.target.value })}>
                      {c.anchors.map((a) => <option key={a.code} value={a.code}>{a.code}</option>)}
                    </select>
                  </td>
                  <td className="py-1 pr-2"><input type="number" className="input py-1.5" value={r.redfin_county_id ?? ""} onChange={(e) => setRegion(i, { redfin_county_id: numOrNull(e.target.value) })} /></td>
                  <td className="py-1">
                    <button type="button" className="btn-ghost p-2" title="Remove" onClick={() => setC({ regions: c.regions.filter((_, j) => j !== i) })}>
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button type="button" className="btn-outline"
          onClick={() => setC({ regions: [...c.regions, { name: "", state: "", anchor: c.anchors[0]?.code ?? "", redfin_county_id: null }] })}>
          <Plus size={16} /> Add region
        </button>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="size-4 accent-pine-600" checked={c.include_nearby}
            onChange={(e) => setC({ include_nearby: e.target.checked })} />
          Include "nearby" results from other areas when they're within an anchor's drive limit
        </label>
      </Panel>

      <Panel title="Condition rules" hint="How the agent decides between good, needs updating, and reject.">
        <textarea rows={6} className="input font-mono text-xs leading-relaxed" value={c.condition_rules}
          onChange={(e) => setC({ condition_rules: e.target.value })} />
        <Field label="Other instructions">
          <textarea rows={3} className="input text-sm" value={c.extra_instructions}
            onChange={(e) => setC({ extra_instructions: e.target.value })} />
        </Field>
      </Panel>
    </form>
  );
}

function strip(p: Profile): ProfileIn {
  return { name: p.name, criteria: p.criteria, schedule_cron: p.schedule_cron, timezone: p.timezone, enabled: p.enabled };
}

function Panel({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="card space-y-4 p-5">
      <div>
        <h3 className="font-semibold">{title}</h3>
        {hint && <p className="text-sm text-stone-500">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

function Field({ label, hint, children }: { label?: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      {label && <span className="text-sm font-medium text-stone-700 dark:text-stone-300">{label}</span>}
      {children}
      {hint && <span className="block text-xs text-stone-500">{hint}</span>}
    </label>
  );
}
