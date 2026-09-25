import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Home, Loader2, MapPin, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { api } from "../../lib/api";
import { cx, money } from "../../lib/format";
import type { Profile, SuggestOut } from "../../lib/types";
import {
  CONDITIONS,
  DEAL_BREAKERS,
  DRIVE_TIMES,
  LAND_AVOID,
  LAND_MUST_HAVES,
  LAND_NICE_TO_HAVES,
  LAND_USES,
  LAND_ZONING,
  PROPERTY_TYPES,
  type ConditionKey,
  type Frequency,
  type WizardAnswers,
  defaultName,
  hasHomes,
  hasLand,
  initialAnswers,
  placeCode,
  toProfile,
} from "../../lib/wizard";
import { CheckList, ChipGroup, MultiChips, OptionCard, Question, hoursLabel } from "./ui";

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

type Step =
  | "type"
  | "budget"
  | "size"
  | "location"
  | "areas"
  | "condition"
  | "land"
  | "schedule"
  | "review";

/** The questions depend on the property types: homes get "condition", land gets "land". */
function stepsFor(a: WizardAnswers): Step[] {
  return [
    "type",
    "budget",
    "size",
    "location",
    "areas",
    ...(hasHomes(a) ? (["condition"] as Step[]) : []),
    ...(hasLand(a) ? (["land"] as Step[]) : []),
    "schedule",
    "review",
  ];
}

export function SetupWizard({
  onDone,
  onCancel,
}: {
  onDone: (profile: Profile) => void;
  onCancel?: () => void;
}) {
  const qc = useQueryClient();
  const [a, setA] = useState<WizardAnswers>(initialAnswers);
  const [step, setStep] = useState<Step>("type");
  const [runNow, setRunNow] = useState(true);
  const set = (patch: Partial<WizardAnswers>) => setA((cur) => ({ ...cur, ...patch }));
  const setLand = (patch: Partial<WizardAnswers["land"]>) => set({ land: { ...a.land, ...patch } });
  const STEPS = stepsFor(a);
  const i = STEPS.indexOf(step);
  const homes = hasHomes(a);
  const land = hasLand(a);

  // --- county suggestions -------------------------------------------------------------
  const placesKey = JSON.stringify(a.places);
  const [suggestedFor, setSuggestedFor] = useState<string | null>(null);
  const suggest = useMutation({
    mutationFn: () =>
      api.suggestRegions({
        anchors: a.places.map((p) => ({ name: p.name.trim(), max_drive_hours: p.hours })),
        property_types: a.propertyTypes,
        min_acres: a.minAcres,
        max_price: a.maxPrice,
      }),
    onSuccess: (out: SuggestOut) => {
      setSuggestedFor(placesKey);
      set({
        anchors: out.anchors.map((x) => ({
          code: x.code,
          name: x.name,
          max_drive_hours: a.places.find((p) => p.name.trim() === x.input)?.hours ?? a.places[0].hours,
        })),
        regions: out.regions.map((r) => ({
          name: r.name,
          state: r.state,
          anchor: r.anchor,
          redfin_county_id: null,
          selected: true,
          est_drive_hours: r.est_drive_hours,
          note: r.note,
        })),
      });
    },
    onError: () => {
      setSuggestedFor(placesKey);
      // Keep going without Claude: label each location ourselves; counties are added by hand.
      set({
        anchors: a.places.map((p) => ({ code: placeCode(p.name), name: p.name.trim(), max_drive_hours: p.hours })),
        regions: [],
      });
    },
  });
  useEffect(() => {
    if (step === "areas" && suggestedFor !== placesKey && !suggest.isPending) suggest.mutate();
  }, [step, suggestedFor, placesKey, suggest]);

  // --- create -------------------------------------------------------------------------
  const create = useMutation({
    mutationFn: async () => {
      const profile = await api.createProfile(toProfile(a));
      if (runNow) await api.startRun(profile.id).catch(() => undefined);
      return profile;
    },
    onSuccess: (profile) => {
      qc.invalidateQueries();
      onDone(profile);
    },
  });

  const canContinue: Record<Step, boolean> = {
    type: a.propertyTypes.length > 0,
    budget: a.maxPrice != null && a.maxPrice > 0 && (a.minPrice == null || a.minPrice <= a.maxPrice),
    location: a.places.every((p) => p.name.trim().length > 1),
    areas: !suggest.isPending && a.regions.some((r) => r.selected),
    size: true,
    condition: true,
    land: true,
    schedule: true,
    review: !create.isPending,
  };

  const next = () => (i < STEPS.length - 1 ? setStep(STEPS[i + 1]) : create.mutate());
  const back = () => i > 0 && setStep(STEPS[i - 1]);

  return (
    <div className="min-h-screen bg-sand-50 dark:bg-stone-950">
      <div className="mx-auto flex min-h-screen max-w-2xl flex-col px-4 py-6 sm:px-6">
        <header className="flex items-center gap-3">
          <div className="grid size-9 place-items-center rounded-xl bg-pine-600 text-sand-100">
            <Home size={18} />
          </div>
          <div className="flex-1">
            <div className="font-display text-lg font-semibold">Set up your property search</div>
            <div className="text-xs text-stone-500">
              Step {i + 1} of {STEPS.length}
            </div>
          </div>
          {onCancel && (
            <button className="btn-ghost p-2" onClick={onCancel} title="Cancel">
              <X size={18} />
            </button>
          )}
        </header>
        <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800">
          <div
            className="h-full rounded-full bg-pine-600 transition-all duration-300"
            style={{ width: `${((i + 1) / STEPS.length) * 100}%` }}
          />
        </div>

        <main className="flex-1 py-10">
          {step === "type" && (
            <Question title="What kind of home are you looking for?" hint="Pick all that you'd consider.">
              <div className="grid gap-3 sm:grid-cols-2">
                {PROPERTY_TYPES.map((t) => {
                  const on = a.propertyTypes.includes(t.key);
                  return (
                    <OptionCard
                      key={t.key}
                      multi
                      selected={on}
                      title={t.label}
                      hint={t.hint}
                      onClick={() =>
                        set({
                          propertyTypes: on
                            ? a.propertyTypes.filter((x) => x !== t.key)
                            : [...a.propertyTypes, t.key],
                        })
                      }
                    />
                  );
                })}
              </div>
            </Question>
          )}

          {step === "budget" && (
            <Question title="What's your price range?" hint="The asking price. Leave the minimum empty for no floor.">
              <div className="grid gap-4 sm:grid-cols-2">
                <MoneyInput label="Minimum" value={a.minPrice} onChange={(v) => set({ minPrice: v })} />
                <MoneyInput label="Maximum" value={a.maxPrice} onChange={(v) => set({ maxPrice: v })} autoFocus />
              </div>
              {a.minPrice != null && a.maxPrice != null && a.minPrice > a.maxPrice && (
                <p className="text-sm text-rose-600">The minimum is higher than the maximum.</p>
              )}
            </Question>
          )}

          {step === "location" && (
            <Question
              title="Where should the search be centered?"
              hint="Enter an address, ZIP code, or landmark (like an airport, a town, or a workplace), then how far you're willing to drive from it."
            >
              <div className="space-y-4">
                {a.places.map((p, idx) => (
                  <div key={idx} className="card space-y-4 p-4">
                    <div className="flex items-center gap-2">
                      <div className="relative flex-1">
                        <MapPin size={18} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400" />
                        <input
                          autoFocus={idx === a.places.length - 1}
                          className="input py-3 pl-10 text-base"
                          placeholder="e.g. 48104, Detroit airport, or 123 Main St, Ann Arbor MI"
                          value={p.name}
                          onChange={(e) =>
                            set({ places: a.places.map((x, j) => (j === idx ? { ...x, name: e.target.value } : x)) })
                          }
                        />
                      </div>
                      {a.places.length > 1 && (
                        <button
                          type="button"
                          className="btn-ghost p-2"
                          title="Remove"
                          onClick={() => set({ places: a.places.filter((_, j) => j !== idx) })}
                        >
                          <Trash2 size={16} />
                        </button>
                      )}
                    </div>
                    <ChipGroup
                      label="Maximum drive time from here"
                      value={p.hours}
                      onChange={(v) =>
                        set({ places: a.places.map((x, j) => (j === idx ? { ...x, hours: v } : x)) })
                      }
                      options={DRIVE_TIMES.map((h) => ({ value: h, label: hoursLabel(h) }))}
                    />
                  </div>
                ))}
                {a.places.length < 6 && (
                  <button
                    type="button"
                    className="btn-outline"
                    onClick={() => set({ places: [...a.places, { name: "", hours: a.places[0].hours }] })}
                  >
                    <Plus size={16} /> Add another location
                  </button>
                )}
                <p className="text-sm text-stone-500">
                  Several locations are searched separately, e.g. if you'd live near any one of three airports.
                </p>
              </div>
            </Question>
          )}

          {step === "areas" && (
            <AreasStep
              answers={a}
              set={set}
              loading={suggest.isPending}
              error={suggest.isError ? (suggest.error as Error).message : null}
              onRetry={() => suggest.mutate()}
            />
          )}

          {step === "size" && (
            <Question
              title={homes ? "How much space do you need?" : "How much land do you need?"}
              hint="Minimums. Choose Any to skip one."
            >
              <div className="space-y-6">
                {homes && (
                <>
                <ChipGroup
                  label="Bedrooms"
                  value={a.minBeds}
                  onChange={(v) => set({ minBeds: v })}
                  options={[null, 1, 2, 3, 4, 5].map((n) => ({ value: n, label: n == null ? "Any" : `${n}+` }))}
                />
                <ChipGroup
                  label="Bathrooms"
                  value={a.minBaths}
                  onChange={(v) => set({ minBaths: v })}
                  options={[null, 1, 1.5, 2, 3].map((n) => ({ value: n, label: n == null ? "Any" : `${n}+` }))}
                />
                </>
                )}
                <ChipGroup
                  label={homes ? "Lot size" : "Acreage"}
                  value={a.minAcres}
                  onChange={(v) => set({ minAcres: v })}
                  options={(homes ? [null, 0.25, 0.5, 1, 2, 5, 10] : [null, 1, 5, 10, 20, 40, 80]).map((n) => ({
                    value: n,
                    label: n == null ? "Any" : `${n}+ acre${n > 1 ? "s" : ""}`,
                  }))}
                />
              </div>
            </Question>
          )}

          {step === "condition" && (
            <Question
              title="How much work are you willing to take on?"
              hint={
                land
                  ? "For the homes in your search. Land questions come next."
                  : "The agent reads each listing's description and sorts homes by condition."
              }
            >
              <div className="space-y-3">
                {(Object.keys(CONDITIONS) as ConditionKey[]).map((k) => (
                  <OptionCard
                    key={k}
                    selected={a.condition === k}
                    title={CONDITIONS[k].label}
                    hint={CONDITIONS[k].hint}
                    onClick={() => set({ condition: k })}
                  />
                ))}
              </div>
              <div>
                <div className="mb-2 text-sm font-medium text-stone-700 dark:text-stone-300">Skip these</div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {DEAL_BREAKERS.map((d) => {
                    const on = a.dealBreakers.includes(d.key);
                    return (
                      <label key={d.key} className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="size-4 accent-pine-600"
                          checked={on}
                          onChange={() =>
                            set({
                              dealBreakers: on
                                ? a.dealBreakers.filter((x) => x !== d.key)
                                : [...a.dealBreakers, d.key],
                            })
                          }
                        />
                        {d.label}
                      </label>
                    );
                  })}
                </div>
              </div>
              {!land && (
                <Notes
                  value={a.notes}
                  onChange={(notes) => set({ notes })}
                  placeholder="e.g. Must have a garage or pole barn. No homes right on a highway."
                />
              )}
            </Question>
          )}

          {step === "land" && (
            <Question
              title="What are you looking for in the land?"
              hint="The agent checks each listing against these. Must-haves decide what gets through."
            >
              <div className="space-y-7">
                <MultiChips
                  label="What will you use it for?"
                  options={LAND_USES}
                  value={a.land.uses}
                  onChange={(uses) => setLand({ uses })}
                />
                <CheckList
                  label="Must have"
                  hint="Listings without these are skipped. If a listing doesn't say, it's marked Unverified."
                  options={LAND_MUST_HAVES}
                  value={a.land.must_have}
                  onChange={(must_have) => setLand({ must_have })}
                />
                <MultiChips
                  label="Nice to have"
                  options={LAND_NICE_TO_HAVES}
                  value={a.land.nice_to_have}
                  onChange={(nice_to_have) => setLand({ nice_to_have })}
                />
                <MultiChips
                  label="Preferred zoning"
                  hint="Leave all unselected if any zoning is fine."
                  options={LAND_ZONING}
                  value={a.land.zoning}
                  onChange={(zoning) => setLand({ zoning })}
                />
                <CheckList
                  label="Skip these"
                  options={LAND_AVOID}
                  value={a.land.avoid}
                  onChange={(avoid) => setLand({ avoid })}
                />
                <Notes
                  value={a.notes}
                  onChange={(notes) => set({ notes })}
                  placeholder="e.g. At least half wooded. South-facing building site. No shared driveways."
                />
              </div>
            </Question>
          )}

          {step === "schedule" && (
            <Question title="How often should the agent search?" hint="Each search re-checks the homes you're tracking and looks for new ones.">
              <div className="space-y-3">
                {(
                  [
                    ["weekly", "Once a week", "Recommended. Most listings stay up for weeks."],
                    ["daily", "Every day", "For fast-moving markets. Costs about 7x more."],
                    ["manual", "Only when I ask", "Run searches yourself from the dashboard."],
                  ] as [Frequency, string, string][]
                ).map(([k, title, hint]) => (
                  <OptionCard key={k} selected={a.frequency === k} title={title} hint={hint} onClick={() => set({ frequency: k })} />
                ))}
              </div>
              {a.frequency !== "manual" && (
                <div className="grid gap-4 sm:grid-cols-3">
                  {a.frequency === "weekly" && (
                    <label className="block space-y-1">
                      <span className="text-sm font-medium">Day</span>
                      <select className="input" value={a.day} onChange={(e) => set({ day: Number(e.target.value) })}>
                        {DAYS.map((d, n) => (
                          <option key={d} value={n}>
                            {d}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <label className="block space-y-1">
                    <span className="text-sm font-medium">Time</span>
                    <input type="time" className="input" value={a.time} onChange={(e) => set({ time: e.target.value })} />
                  </label>
                  <label className="block space-y-1">
                    <span className="text-sm font-medium">Time zone</span>
                    <input className="input" value={a.timezone} onChange={(e) => set({ timezone: e.target.value })} />
                  </label>
                </div>
              )}
            </Question>
          )}

          {step === "review" && (
            <Question title="Ready to start?" hint="Check your answers. You can change any of this later in Search settings.">
              <label className="block space-y-1">
                <span className="text-sm font-medium">Name this search</span>
                <input
                  className="input"
                  placeholder={defaultName(a)}
                  value={a.name}
                  onChange={(e) => set({ name: e.target.value })}
                />
              </label>
              <dl className="card divide-y divide-stone-100 text-sm dark:divide-stone-800">
                <Row label="Home types" onEdit={() => setStep("type")}>
                  {a.propertyTypes.map((t) => PROPERTY_TYPES.find((p) => p.key === t)?.label).join(", ")}
                </Row>
                <Row label="Price" onEdit={() => setStep("budget")}>
                  {a.minPrice ? `${money(a.minPrice)} – ${money(a.maxPrice)}` : `Up to ${money(a.maxPrice)}`}
                </Row>
                <Row label="Centered on" onEdit={() => setStep("location")}>
                  {a.anchors.map((x) => `${x.name} (within ${hoursLabel(x.max_drive_hours)})`).join("; ")}
                </Row>
                <Row label="Counties" onEdit={() => setStep("areas")}>
                  {a.regions.filter((r) => r.selected).length} counties
                </Row>
                <Row label="Size" onEdit={() => setStep("size")}>
                  {[
                    homes && a.minBeds && `${a.minBeds}+ beds`,
                    homes && a.minBaths && `${a.minBaths}+ baths`,
                    a.minAcres && `${a.minAcres}+ acres`,
                  ]
                    .filter(Boolean)
                    .join(", ") || "Any"}
                </Row>
                {homes && (
                  <Row label="Condition" onEdit={() => setStep("condition")}>
                    {CONDITIONS[a.condition].label}
                  </Row>
                )}
                {land && (
                  <Row label="Land" onEdit={() => setStep("land")}>
                    {[
                      a.land.uses.length ? `For ${a.land.uses.join(", ").toLowerCase()}` : "",
                      a.land.must_have.length ? `Must have: ${a.land.must_have.join(", ").toLowerCase()}` : "",
                      a.land.zoning.length ? `Zoning: ${a.land.zoning.join(", ").toLowerCase()}` : "",
                    ]
                      .filter(Boolean)
                      .join(". ") || "No land preferences"}
                  </Row>
                )}
                <Row label="Schedule" onEdit={() => setStep("schedule")}>
                  {a.frequency === "manual"
                    ? "Only when you run it"
                    : `${a.frequency === "daily" ? "Every day" : `Every ${DAYS[a.day]}`} at ${a.time}`}
                </Row>
              </dl>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="size-4 accent-pine-600" checked={runNow} onChange={(e) => setRunNow(e.target.checked)} />
                Run the first search now
              </label>
              {create.isError && <p className="text-sm text-rose-600">{(create.error as Error).message}</p>}
            </Question>
          )}
        </main>

        <footer className="sticky bottom-0 flex items-center justify-between border-t border-stone-200 bg-sand-50/90 py-4 backdrop-blur dark:border-stone-800 dark:bg-stone-950/90">
          <button className="btn-ghost" onClick={back} disabled={i === 0}>
            <ArrowLeft size={16} /> Back
          </button>
          <button className="btn-primary px-5 py-2.5" onClick={next} disabled={!canContinue[step]}>
            {step === "review" ? (
              create.isPending ? (
                <>
                  <Loader2 size={16} className="animate-spin" /> Creating…
                </>
              ) : (
                "Create my search"
              )
            ) : (
              <>
                Continue <ArrowRight size={16} />
              </>
            )}
          </button>
        </footer>
      </div>
    </div>
  );
}

function AreasStep({
  answers: a,
  set,
  loading,
  error,
  onRetry,
}: {
  answers: WizardAnswers;
  set: (p: Partial<WizardAnswers>) => void;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  const [county, setCounty] = useState({ name: "", state: "", anchor: "" });
  if (loading) {
    return (
      <Question title="Finding counties within your drive time…" hint="Claude is working out which counties fall inside your drive-time limit. This takes a few seconds.">
        <div className="card flex items-center gap-3 p-6 text-stone-600 dark:text-stone-300">
          <Loader2 className="animate-spin text-pine-600" /> Mapping your search area
        </div>
      </Question>
    );
  }
  const toggle = (idx: number) =>
    set({ regions: a.regions.map((r, j) => (j === idx ? { ...r, selected: !r.selected } : r)) });
  const selected = a.regions.filter((r) => r.selected).length;

  return (
    <Question
      title={error ? "Which counties should we search?" : "These are the counties within your drive time"}
      hint={
        error
          ? "Add each county you'd like the agent to search."
          : "Uncheck any you don't want, or add ones we missed. The agent searches each county you keep."
      }
    >
      {error && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          Couldn't suggest counties automatically ({error}). Add them below, or{" "}
          <button className="font-medium underline" onClick={onRetry}>
            try again
          </button>
          .
        </div>
      )}
      {a.anchors.map((anchor) => {
        const rows = a.regions.map((r, idx) => ({ r, idx })).filter(({ r }) => r.anchor === anchor.code);
        return (
          <section key={anchor.code} className="space-y-2">
            <h3 className="flex items-center gap-2 font-medium">
              <MapPin size={16} className="text-pine-600" />
              {anchor.name}
              <span className="text-sm font-normal text-stone-500">within {hoursLabel(anchor.max_drive_hours)}</span>
            </h3>
            <div className="card divide-y divide-stone-100 dark:divide-stone-800">
              {rows.map(({ r, idx }) => (
                <label key={idx} className="flex cursor-pointer items-center gap-3 px-4 py-2.5 hover:bg-sand-50 dark:hover:bg-stone-800/40">
                  <input type="checkbox" className="size-4 accent-pine-600" checked={r.selected} onChange={() => toggle(idx)} />
                  <span className={cx("font-medium", !r.selected && "text-stone-400 line-through")}>
                    {r.name}, {r.state}
                  </span>
                  <span className="hidden text-sm text-stone-500 sm:inline">{r.note}</span>
                  {r.est_drive_hours != null && (
                    <span className="ml-auto text-sm tabular-nums text-stone-500">~{hoursLabel(r.est_drive_hours)}</span>
                  )}
                </label>
              ))}
              {!rows.length && <p className="px-4 py-3 text-sm text-stone-500">No counties yet.</p>}
            </div>
          </section>
        );
      })}
      <form
        className="grid grid-cols-[1fr_4rem] gap-2 sm:grid-cols-[1fr_4rem_8rem_auto]"
        onSubmit={(e) => {
          e.preventDefault();
          const name = /county$/i.test(county.name.trim()) ? county.name.trim() : `${county.name.trim()} County`;
          set({
            regions: [
              ...a.regions,
              { name, state: county.state, anchor: county.anchor || a.anchors[0]?.code, redfin_county_id: null, selected: true },
            ],
          });
          setCounty({ ...county, name: "", state: "" });
        }}
      >
        <input className="input" placeholder="Add a county" required value={county.name} onChange={(e) => setCounty({ ...county, name: e.target.value })} />
        <input className="input uppercase" placeholder="ST" required minLength={2} maxLength={2} value={county.state} onChange={(e) => setCounty({ ...county, state: e.target.value.toUpperCase() })} />
        {a.anchors.length > 1 && (
          <select className="input" value={county.anchor || a.anchors[0]?.code} onChange={(e) => setCounty({ ...county, anchor: e.target.value })}>
            {a.anchors.map((x) => (
              <option key={x.code} value={x.code}>
                near {x.code}
              </option>
            ))}
          </select>
        )}
        <button className="btn-outline col-span-2 sm:col-span-1">
          <Plus size={16} /> Add
        </button>
      </form>
      <div className="flex items-center justify-between text-sm text-stone-500">
        <span>{selected} counties selected</span>
        {!error && (
          <button className="btn-ghost px-2 py-1" onClick={onRetry}>
            <RefreshCw size={14} /> Suggest again
          </button>
        )}
      </div>
    </Question>
  );
}

function Notes({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium text-stone-700 dark:text-stone-300">
        Anything else the agent should know? <span className="font-normal text-stone-500">(optional)</span>
      </span>
      <textarea
        rows={3}
        className="input"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function MoneyInput({
  label,
  value,
  onChange,
  autoFocus,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  autoFocus?: boolean;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium">{label}</span>
      <div className="relative">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400">$</span>
        <input
          autoFocus={autoFocus}
          inputMode="numeric"
          className="input py-3 pl-7 text-base tabular-nums"
          placeholder={label === "Minimum" ? "No minimum" : "e.g. 350,000"}
          value={value == null ? "" : value.toLocaleString("en-US")}
          onChange={(e) => {
            const digits = e.target.value.replace(/[^\d]/g, "");
            onChange(digits ? Number(digits) : null);
          }}
        />
      </div>
    </label>
  );
}

function Row({ label, onEdit, children }: { label: string; onEdit: () => void; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-4 px-4 py-3">
      <dt className="w-28 shrink-0 text-stone-500">{label}</dt>
      <dd className="flex-1">{children}</dd>
      <button type="button" className="text-sm font-medium text-pine-700 hover:underline dark:text-pine-300" onClick={onEdit}>
        Edit
      </button>
    </div>
  );
}
