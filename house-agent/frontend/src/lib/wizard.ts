// Turns the setup wizard's answers into a search profile.

import type { Anchor, Criteria, ProfileIn, Region } from "./types";

export const PROPERTY_TYPES = [
  { key: "house", label: "House", hint: "Single-family home" },
  { key: "townhouse", label: "Townhouse", hint: "Attached, own the land" },
  { key: "condo", label: "Condo", hint: "Unit in a building or complex" },
  { key: "multifamily", label: "Multi-family", hint: "Duplex to 4-plex" },
  { key: "manufactured", label: "Manufactured", hint: "Manufactured or mobile home" },
  { key: "land", label: "Land", hint: "Lots and acreage" },
] as const;

export const DRIVE_TIMES = [0.5, 0.75, 1, 1.5, 2, 2.5, 3, 4];

export const CONDITIONS = {
  move_in: {
    label: "Move-in ready",
    hint: "No projects. It should be livable and up to date on day one.",
    rules:
      "Only move-in ready homes. Reject anything that needs repairs or significant updating: " +
      'fixer-uppers, "TLC", "needs work", "as-is" with repair language, damage, unfinished areas. ' +
      "Label acceptable homes good; don't use needs_updating (treat those as reject).",
  },
  cosmetic: {
    label: "Cosmetic updates are fine",
    hint: "Paint, flooring, dated kitchens: yes. Major repairs: no.",
    rules:
      "Exclude anything that needs major repairs to be habitable, e.g. \"cash only\", foreclosure " +
      'sold as-is with no access, "extensive TLC", "needs work throughout", fixer-upper/restore/' +
      "rehab, mold/leaks/damage, stripped to studs, unfinished shell.\n" +
      'Houses that only need cosmetic updating or "some TLC" stay, labeled needs_updating.\n' +
      'Plain "as-is" or estate as-is with no repair language is fine.',
  },
  fixer: {
    label: "Fixer-uppers welcome",
    hint: "Real projects are OK, as long as it isn't a teardown.",
    rules:
      "Fixer-uppers are fine. Only reject homes that can't be lived in or repaired sensibly: " +
      "fire damage, condemned, stripped to studs, unfinished shell, structural failure. Label " +
      "anything needing repairs or updating needs_updating and summarize the work mentioned.",
  },
} as const;

export type ConditionKey = keyof typeof CONDITIONS;

export const DEAL_BREAKERS = [
  { key: "auctions", label: "Auctions and short sales", text: "Exclude auctions and short sales." },
  {
    key: "hoa",
    label: "HOA fees",
    text: "Exclude homes with a homeowners association (HOA) fee.",
  },
  {
    key: "commercial",
    label: "Commercial or mixed-use",
    text: "Exclude churches, commercial and mixed-use property.",
  },
  {
    key: "flood",
    label: "Flood zones",
    text: "Exclude homes the listing says are in a flood zone.",
  },
] as const;

export type DealBreaker = (typeof DEAL_BREAKERS)[number]["key"];

export type Frequency = "weekly" | "daily" | "manual";

export interface WizardAnswers {
  propertyTypes: string[];
  minPrice: number | null;
  maxPrice: number | null;
  places: { name: string; hours: number }[];
  anchors: Anchor[];
  regions: (Region & { selected: boolean; est_drive_hours?: number; note?: string })[];
  minBeds: number | null;
  minBaths: number | null;
  minAcres: number | null;
  condition: ConditionKey;
  dealBreakers: DealBreaker[];
  notes: string;
  frequency: Frequency;
  day: number;
  time: string;
  timezone: string;
  name: string;
}

export function initialAnswers(): WizardAnswers {
  return {
    propertyTypes: ["house"],
    minPrice: null,
    maxPrice: null,
    places: [{ name: "", hours: 1 }],
    anchors: [],
    regions: [],
    minBeds: null,
    minBaths: null,
    minAcres: null,
    condition: "cosmetic",
    dealBreakers: ["auctions"],
    notes: "",
    frequency: "weekly",
    day: 5,
    time: "07:00",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "America/New_York",
    name: "",
  };
}

/** Fallback label for a place when Claude couldn't resolve it: initials, max 4 letters. */
export function placeCode(name: string) {
  const words = name.replace(/[^A-Za-z ]/g, " ").split(/\s+/).filter(Boolean);
  const code = words.length > 1 ? words.map((w) => w[0]).join("") : (words[0] ?? "").slice(0, 3);
  return code.toUpperCase().slice(0, 4) || "HOME";
}

export function cronFor(a: WizardAnswers) {
  if (a.frequency === "manual") return "";
  const [h, m] = a.time.split(":").map(Number);
  return `${m} ${h} * * ${a.frequency === "daily" ? "*" : a.day}`;
}

export function defaultName(a: WizardAnswers) {
  const type = a.propertyTypes.length === 1
    ? (PROPERTY_TYPES.find((p) => p.key === a.propertyTypes[0])?.label ?? "Home") + "s"
    : "Homes";
  const near = a.anchors.map((x) => x.code).join(", ");
  return near ? `${type} near ${near}` : `${type} search`;
}

export function toProfile(a: WizardAnswers): ProfileIn {
  const extra = [
    "US only.",
    ...DEAL_BREAKERS.filter((d) => a.dealBreakers.includes(d.key)).map((d) => d.text),
    a.notes.trim(),
  ]
    .filter(Boolean)
    .join(" ");
  const criteria: Criteria = {
    property_types: a.propertyTypes,
    min_price: a.minPrice,
    max_price: a.maxPrice,
    min_acres: a.minAcres,
    max_acres: null,
    min_beds: a.minBeds,
    min_baths: a.minBaths,
    anchors: a.anchors,
    regions: a.regions
      .filter((r) => r.selected)
      .map(({ name, state, anchor, redfin_county_id }) => ({ name, state, anchor, redfin_county_id })),
    include_nearby: true,
    condition_rules: CONDITIONS[a.condition].rules,
    extra_instructions: extra,
  };
  return {
    name: a.name.trim() || defaultName(a),
    criteria,
    schedule_cron: cronFor(a),
    timezone: a.timezone,
    enabled: a.frequency !== "manual",
  };
}
