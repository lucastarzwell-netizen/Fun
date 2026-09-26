import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Save, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { dateTime } from "../lib/format";
import type { Criteria, LandPrefs, Profile, ProfileIn, Region } from "../lib/types";
import {
  LAND_AVOID,
  LAND_MUST_HAVES,
  LAND_NICE_TO_HAVES,
  LAND_USES,
  LAND_ZONING,
  COUNTRY,
  sitesFor,
  hasHomes,
  hasLand,
} from "../lib/wizard";
import { CheckList, MultiChips } from "./wizard/ui";
import { EmailSettings } from "./EmailSettings";
import { LocationsPanel } from "./LocationsPanel";
import { SplitPanel } from "./SplitPanel";
import { useDemo } from "../lib/demo";
import {
  MONTH_DAYS,
  WEEKDAYS,
  ordinal,
  parseSchedule,
  toCron,
  withEvery,
  type Every,
  type Schedule,
} from "../lib/schedule";

const EMPTY_LAND: LandPrefs = { uses: [], must_have: [], nice_to_have: [], zoning: [], avoid: [] };

const numOrNull = (v: string) => (v === "" ? null : Number(v));

export function SettingsView({ profile }: { profile: Profile }) {
  const qc = useQueryClient();
  const demo = useDemo();
  const [draft, setDraft] = useState<ProfileIn>(() => strip(profile));
  useEffect(() => setDraft(strip(profile)), [profile]);

  const save = useMutation({
    mutationFn: () => api.updateProfile(profile.id, draft),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profiles"] }),
  });

  const c = draft.criteria;
  const setC = (patch: Partial<Criteria>) => setDraft({ ...draft, criteria: { ...c, ...patch } });
  const land = c.land ?? EMPTY_LAND;
  const setLand = (patch: Partial<LandPrefs>) => setC({ land: { ...land, ...patch } });
  const setRegion = (i: number, patch: Partial<Region>) =>
    setC({ regions: c.regions.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  const sched = parseSchedule(draft.schedule_cron, draft.schedule_every ?? "week");
  const setSched = (next: Schedule) =>
    setDraft({ ...draft, schedule_cron: toCron(next), schedule_every: next.every });
  // Profiles created with "Only when I ask" have no cron; give the toggle something to enable.
  useEffect(() => {
    if (draft.enabled && !draft.schedule_cron.trim())
      setDraft((d) => ({ ...d, schedule_cron: "0 7 * * 5", schedule_every: "week" }));
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
          {!demo && (
            <button className="btn-primary" disabled={!dirty || save.isPending}>
              <Save size={16} /> Save changes
            </button>
          )}
        </div>
      </div>

      {demo && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          Demo: you can see how this search is set up, but not change it.
          {profile.email_hidden && " Email addresses are hidden."}
        </p>
      )}
      {/* In a demo every control below is disabled (the server refuses changes anyway). */}
      <fieldset disabled={demo} className="min-w-0 space-y-6">
      <Panel title="Basics">
        <Field label="Country" hint="Changing the country switches listing sites; review your locations and regions after.">
          <select className="input" value={c.country}
            onChange={(e) => {
              const country = e.target.value as Criteria["country"];
              setC({ country, sites: sitesFor(country).map((x) => x.key as string) });
            }}>
            <option value="US">🇺🇸 United States</option>
            <option value="CA">🇨🇦 Canada</option>
          </select>
        </Field>
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

      <Panel
        title="Listing sites"
        hint="The agent spreads each search across these sites. Each county starts on a site it didn't use last time, so over a few searches every county is checked on every site. Sites that block the agent are tried last next time."
      >
        <div className="grid gap-2 sm:grid-cols-3">
          {sitesFor(c.country).map((site) => {
            const on = (c.sites ?? []).includes(site.key) || !sitesFor(c.country).some((x) => c.sites.includes(x.key));
            return (
              <label key={site.key} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-4 accent-pine-600"
                  checked={on}
                  onChange={() =>
                    setC({
                      sites: on
                        ? c.sites.filter((k) => k !== site.key)
                        : sitesFor(c.country).map((x) => x.key as string).filter((k) => k === site.key || c.sites.includes(k)),
                    })
                  }
                />
                {site.name}
                {"landOnly" in site && <span className="text-xs text-stone-500">(land searches)</span>}
              </label>
            );
          })}
        </div>
        {(c.sites ?? []).length === 0 && (
          <p className="text-sm text-rose-600">Pick at least one site, or the agent will only use web search.</p>
        )}
      </Panel>

      <Panel title="Pending and under-contract listings">
        <label className="flex items-start gap-2 text-sm">
          <input type="radio" className="mt-0.5 size-4 accent-pine-600" checked={!c.include_pending}
            onChange={() => setC({ include_pending: false })} />
          <span>
            <span className="font-medium">Leave them out.</span>{" "}
            <span className="text-stone-500">They go to the Rejected tab, where you can include any of them.</span>
          </span>
        </label>
        <label className="flex items-start gap-2 text-sm">
          <input type="radio" className="mt-0.5 size-4 accent-pine-600" checked={c.include_pending}
            onChange={() => setC({ include_pending: true })} />
          <span>
            <span className="font-medium">Include them</span>{" "}
            <span className="text-stone-500">with your listings, marked Pending or Under contract.</span>
          </span>
        </label>
      </Panel>

      <Panel title="Schedule">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="size-4 accent-pine-600" checked={draft.enabled}
            onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />
          Run automatically
        </label>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {!draft.schedule_cron.trim() ? null : sched ? (
            <>
              <Field label="How often">
                <select className="input" value={sched.every}
                  onChange={(e) => setSched(withEvery(sched, e.target.value as Every))}>
                  <option value="week">Every week</option>
                  <option value="2weeks">Every 2 weeks</option>
                  <option value="month">Every month</option>
                </select>
              </Field>
              {sched.every === "month" ? (
                <Field label="Day of the month" hint={sched.day > 28 ? "In shorter months it runs on the last day." : undefined}>
                  <select className="input" value={sched.day}
                    onChange={(e) => setSched({ ...sched, day: Number(e.target.value) })}>
                    {MONTH_DAYS.map((d) => <option key={d} value={d}>{ordinal(d)}</option>)}
                  </select>
                </Field>
              ) : (
                <Field label="Day">
                  <select className="input" value={sched.day}
                    onChange={(e) => setSched({ ...sched, day: Number(e.target.value) })}>
                    {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
                    {sched.every === "week" && <option value={7}>Every day</option>}
                  </select>
                </Field>
              )}
              <Field label="Time">
                <input type="time" className="input" value={sched.time}
                  onChange={(e) => setSched({ ...sched, time: e.target.value })} />
              </Field>
            </>
          ) : (
            <Field label="Cron expression" hint="minute hour day month weekday">
              <input className="input font-mono" value={draft.schedule_cron}
                onChange={(e) => setDraft({ ...draft, schedule_cron: e.target.value, schedule_every: "week" })} />
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

      <LocationsPanel criteria={c} savedAnchors={profile.criteria.anchors} setC={setC} />

      <Panel title={`${COUNTRY[c.country].Areas} (${c.regions.length})`} hint={`The ${COUNTRY[c.country].areas} the agent searches. Use Update ${COUNTRY[c.country].areas} above after changing a drive time, or edit this list directly.`}>
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

      {hasLand({ propertyTypes: c.property_types }) && (
        <Panel title="Land preferences" hint="How the agent judges vacant land listings.">
          <MultiChips label="Intended use" options={LAND_USES} value={land.uses} onChange={(uses) => setLand({ uses })} />
          <CheckList label="Must have" options={LAND_MUST_HAVES} value={land.must_have} onChange={(must_have) => setLand({ must_have })} />
          <MultiChips label="Nice to have" options={LAND_NICE_TO_HAVES} value={land.nice_to_have} onChange={(nice_to_have) => setLand({ nice_to_have })} />
          <MultiChips label="Preferred zoning" hint="None selected means any zoning." options={LAND_ZONING} value={land.zoning} onChange={(zoning) => setLand({ zoning })} />
          <CheckList label="Skip these" options={LAND_AVOID} value={land.avoid} onChange={(avoid) => setLand({ avoid })} />
        </Panel>
      )}

      <Panel
        title={hasHomes({ propertyTypes: c.property_types }) ? "Condition rules" : "Agent instructions"}
        hint={hasHomes({ propertyTypes: c.property_types }) ? "How the agent decides between good, needs updating, and reject for homes." : undefined}
      >
        {hasHomes({ propertyTypes: c.property_types }) && (
          <textarea rows={6} className="input font-mono text-xs leading-relaxed" value={c.condition_rules}
            onChange={(e) => setC({ condition_rules: e.target.value })} />
        )}
        <Field label="Other instructions">
          <textarea rows={3} className="input text-sm" value={c.extra_instructions}
            onChange={(e) => setC({ extra_instructions: e.target.value })} />
        </Field>
      </Panel>
      <EmailPanel
        profileId={profile.id}
        value={draft.notify}
        onChange={(notify) => setDraft({ ...draft, notify })}
      />

      <FeedbackPanel profileId={profile.id} />
      {!demo && (
        <Panel
          title="Demo access"
          hint="Someone signed in with the demo password sees only the searches you show here, read-only, without email addresses."
        >
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={draft.demo_visible ?? false}
              onChange={(e) => setDraft({ ...draft, demo_visible: e.target.checked })}
            />
            Show this search in the demo
          </label>
        </Panel>
      )}
      </fieldset>
      {!demo && <SplitPanel profile={profile} />}
      {!demo && <DeletePanel profile={profile} />}
    </form>
  );
}

function EmailPanel({
  profileId,
  value,
  onChange,
}: {
  profileId: number;
  value: ProfileIn["notify"];
  onChange: (v: ProfileIn["notify"]) => void;
}) {
  const test = useMutation({ mutationFn: () => api.testEmail(profileId, value.email_to) });
  return (
    <Panel title="Email summaries" hint="A summary of each finished search, with the top listings, sent to everyone listed.">
      <EmailSettings value={value} onChange={onChange} />
      {value.email_enabled && value.email_to.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn-outline" disabled={test.isPending} onClick={() => test.mutate()}>
            {test.isPending ? "Sending…" : "Send a test email"}
          </button>
          {test.isSuccess && <span className="text-sm text-pine-700">Sent to {test.data.sent_to.join(", ")}</span>}
          {test.isError && <span className="text-sm text-rose-600">{(test.error as Error).message}</span>}
        </div>
      )}
    </Panel>
  );
}

function DeletePanel({ profile }: { profile: Profile }) {
  const qc = useQueryClient();
  const remove = useMutation({
    mutationFn: () => api.deleteProfile(profile.id),
    onSuccess: () => {
      qc.removeQueries({ predicate: (q) => q.queryKey.includes(profile.id) });
      qc.invalidateQueries({ queryKey: ["profiles"] });
    },
  });
  return (
    <section className="card space-y-3 border-rose-200 p-5 dark:border-rose-900/60">
      <div>
        <h3 className="font-semibold text-rose-700 dark:text-rose-300">Delete this search</h3>
        <p className="text-sm text-stone-500">
          Stops its scheduled searches and permanently deletes its listings, rejected and excluded
          addresses, run history and feedback. To just pause it, untick Run automatically under Schedule
          instead.
        </p>
      </div>
      {remove.isError && <p className="text-sm text-rose-600">{(remove.error as Error).message}</p>}
      <button
        type="button"
        className="btn border border-rose-300 bg-white text-rose-700 hover:bg-rose-50 dark:border-rose-800 dark:bg-stone-900 dark:text-rose-300 dark:hover:bg-rose-950/40"
        disabled={remove.isPending}
        onClick={() => {
          if (confirm(`Delete "${profile.name}" and everything it found? This can't be undone.`)) remove.mutate();
        }}
      >
        <Trash2 size={16} /> {remove.isPending ? "Deleting…" : "Delete this search"}
      </button>
    </section>
  );
}

function FeedbackPanel({ profileId }: { profileId: number }) {
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["feedback", profileId], queryFn: () => api.feedback(profileId) });
  const remove = useMutation({
    mutationFn: api.deleteFeedback,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["feedback", profileId] }),
  });
  return (
    <Panel
      title="What you've taught the agent"
      hint="Each time you include a rejected listing, your reason is sent with every future search. Remove any that no longer apply."
    >
      {data.length === 0 ? (
        <p className="text-sm text-stone-500">Nothing yet. Use Include anyway on the Rejected tab to add some.</p>
      ) : (
        <ul className="divide-y divide-stone-100 text-sm dark:divide-stone-800">
          {data.map((f) => (
            <li key={f.id} className="flex items-start gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="font-medium">"{f.user_reason}"</div>
                <div className="text-stone-500">
                  {f.listing_label}
                  {f.agent_reason && <> · agent had said: {f.agent_reason}</>}
                </div>
              </div>
              <button type="button" className="btn-ghost p-2" title="Remove" onClick={() => remove.mutate(f.id)}>
                <Trash2 size={16} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function strip(p: Profile): ProfileIn {
  return {
    name: p.name,
    criteria: p.criteria,
    schedule_cron: p.schedule_cron,
    schedule_every: p.schedule_every ?? "week",
    timezone: p.timezone,
    enabled: p.enabled,
    demo_visible: p.demo_visible ?? false,
    notify: p.notify ?? { email_enabled: false, email_to: [], top_n: 5 },
  };
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
