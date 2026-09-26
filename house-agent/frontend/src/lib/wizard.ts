import { toCron, type Schedule } from "./schedule";
// Turns the setup wizard's answers into a search profile.

import type { Anchor, Country, Criteria, LandPrefs, ProfileIn, Region } from "./types";

export const PROPERTY_TYPES = [
  { key: "house", label: "House", hint: "Single-family home" },
  { key: "townhouse", label: "Townhouse", hint: "Attached, own the land" },
  { key: "condo", label: "Condo", hint: "Unit in a building or complex" },
  { key: "multifamily", label: "Multi-family", hint: "Duplex to 4-plex" },
  { key: "manufactured", label: "Manufactured", hint: "Manufactured or mobile home" },
  { key: "land", label: "Land", hint: "Lots and acreage" },
] as const;

/** Property types that are buildings (everything except vacant land). */
export const HOME_TYPES = ["house", "townhouse", "condo", "multifamily", "manufactured"];

export const hasHomes = (a: Pick<WizardAnswers, "propertyTypes">) =>
  a.propertyTypes.some((t) => HOME_TYPES.includes(t));
export const hasLand = (a: Pick<WizardAnswers, "propertyTypes">) => a.propertyTypes.includes("land");

// Land questions. Stored as these labels; the agent reads them as written.
export const LAND_USES = [
  "Build a home",
  "Cabin or weekend getaway",
  "Hunting",
  "Farming or livestock",
  "Homestead",
  "Camping or RV",
  "Investment / hold",
];

export const LAND_MUST_HAVES = [
  "Year-round road access",
  "Power at or near the road",
  "Buildable (level, perc test passed or septic approved)",
  "Well or public water available",
  "Allows mobile or manufactured homes",
];

export const LAND_NICE_TO_HAVES = [
  "Wooded",
  "Open or tillable fields",
  "Pond, creek, or river frontage",
  "Good hunting (wildlife, cover)",
  "Views",
  "Existing barn, shed, or driveway",
  "Privacy / no close neighbors",
];

export const LAND_ZONING = ["Residential", "Agricultural", "Recreational", "Unrestricted / no zoning"];

export const LAND_AVOID = [
  "Landlocked (no legal access)",
  "Mostly wetlands or flood zone",
  "HOA or deed restrictions that limit building",
  "Next to highways, industry, or landfills",
  "Auctions and tax sales",
];

// Listing sites the agent can search (keys match backend agent/sources.py).
export const SITES = [
  { key: "redfin", name: "Redfin", country: "US" },
  { key: "zillow", name: "Zillow", country: "US" },
  { key: "realtor", name: "Realtor.com", country: "US" },
  { key: "homes", name: "Homes.com", country: "US" },
  { key: "landwatch", name: "LandWatch", country: "US", landOnly: true },
  { key: "realtor_ca", name: "Realtor.ca", country: "CA" },
  { key: "zolo", name: "Zolo", country: "CA" },
  { key: "point2", name: "Point2 Homes", country: "CA" },
  { key: "redfin_ca", name: "Redfin.ca", country: "CA" },
] as const;
export const sitesFor = (country: Country) => SITES.filter((s) => s.country === country);
export const DEFAULT_SITES = sitesFor("US").map((s) => s.key as string);

/** Country-specific words used across setup and settings. */
export const COUNTRY = {
  US: {
    name: "United States",
    flag: "🇺🇸",
    areas: "counties",
    Areas: "Counties",
    area: "county",
    region: "ST",
    postal: "ZIP code",
    currency: "US dollars",
    example: "e.g. 48104, Detroit airport, or 123 Main St, Ann Arbor MI",
  },
  CA: {
    name: "Canada",
    flag: "🇨🇦",
    areas: "regions",
    Areas: "Regions",
    area: "region",
    region: "Prov",
    postal: "postal code",
    currency: "Canadian dollars",
    example: "e.g. K7L 3N6, Toronto Pearson airport, or 123 Main St, Kingston ON",
  },
} as const;

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
    label: "HOA or condo fees",
    text: "Exclude homes with a homeowners association (HOA), condo or strata fee.",
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

export type Frequency = "weekly" | "biweekly" | "monthly" | "daily" | "manual";

export interface WizardAnswers {
  country: Country;
  propertyTypes: string[];
  minPrice: number | null;
  maxPrice: number | null;
  places: { name: string; hours: number }[];
  anchors: Anchor[];
  regions: (Region & { selected: boolean; est_drive_hours?: number; est_drive_km?: number | null; note?: string })[];
  minBeds: number | null;
  minBaths: number | null;
  minAcres: number | null;
  condition: ConditionKey;
  dealBreakers: DealBreaker[];
  land: LandPrefs;
  notes: string;
  includePending: boolean;
  notify: import("./types").NotifySettings;
  frequency: Frequency;
  day: number; // weekday 0-6 (Sunday = 0) for weekly / every two weeks
  monthDay: number; // 1-31 for monthly
  time: string;
  timezone: string;
  name: string;
}

export function initialAnswers(): WizardAnswers {
  return {
    country: "US",
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
    land: {
      uses: [],
      must_have: ["Year-round road access"],
      nice_to_have: [],
      zoning: [],
      avoid: ["Landlocked (no legal access)", "Auctions and tax sales"],
    },
    notes: "",
    includePending: false,
    notify: { email_enabled: false, email_to: [], top_n: 5 },
    frequency: "weekly",
    day: 5,
    monthDay: 1,
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

export function scheduleFor(a: WizardAnswers): Schedule | null {
  switch (a.frequency) {
    case "manual":
      return null;
    case "daily":
      return { every: "week", day: 7, time: a.time };
    case "biweekly":
      return { every: "2weeks", day: a.day, time: a.time };
    case "monthly":
      return { every: "month", day: a.monthDay, time: a.time };
    default:
      return { every: "week", day: a.day, time: a.time };
  }
}

export function cronFor(a: WizardAnswers) {
  const s = scheduleFor(a);
  return s ? toCron(s) : "";
}

export function defaultName(a: WizardAnswers) {
  const only = a.propertyTypes.length === 1 ? a.propertyTypes[0] : null;
  const type =
    only === "land"
      ? "Land"
      : only
        ? (PROPERTY_TYPES.find((p) => p.key === only)?.label ?? "Home") + "s"
        : "Properties";
  const near = a.anchors.map((x) => x.code).join(", ");
  return near ? `${type} near ${near}` : `${type} search`;
}

export function toProfile(a: WizardAnswers): ProfileIn {
  const homes = hasHomes(a);
  const extra = [
    "US only.",
    ...(homes ? DEAL_BREAKERS.filter((d) => a.dealBreakers.includes(d.key)).map((d) => d.text) : []),
    a.notes.trim(),
  ]
    .filter(Boolean)
    .join(" ");
  const criteria: Criteria = {
    country: a.country,
    property_types: a.propertyTypes,
    min_price: a.minPrice,
    max_price: a.maxPrice,
    min_acres: a.minAcres,
    max_acres: null,
    // Bedrooms and bathrooms mean nothing for land-only searches.
    min_beds: homes ? a.minBeds : null,
    min_baths: homes ? a.minBaths : null,
    anchors: a.anchors,
    regions: a.regions
      .filter((r) => r.selected)
      .map(({ name, state, anchor, redfin_county_id }) => ({ name, state, anchor, redfin_county_id })),
    include_nearby: true,
    condition_rules: CONDITIONS[a.condition].rules,
    land: hasLand(a) ? a.land : null,
    sites: sitesFor(a.country).map((s) => s.key),
    include_pending: a.includePending,
    extra_instructions: extra,
  };
  return {
    name: a.name.trim() || defaultName(a),
    criteria,
    schedule_cron: cronFor(a),
    schedule_every: scheduleFor(a)?.every ?? "week",
    timezone: a.timezone,
    enabled: a.frequency !== "manual",
    notify: a.notify,
  };
}
