// Mirrors backend/src/house_agent/schemas.py

export interface Anchor {
  code: string;
  name: string;
  max_drive_hours: number;
}

export interface Region {
  name: string;
  state: string;
  anchor: string;
  redfin_county_id: number | null;
}

export type Country = "US" | "CA";

export interface Criteria {
  country: Country;
  property_types: string[];
  min_price: number | null;
  max_price: number | null;
  min_acres: number | null;
  max_acres: number | null;
  min_beds: number | null;
  min_baths: number | null;
  anchors: Anchor[];
  regions: Region[];
  include_nearby: boolean;
  condition_rules: string;
  land: LandPrefs | null;
  sites: string[];
  include_pending: boolean;
  extra_instructions: string;
}

export interface LandPrefs {
  uses: string[];
  must_have: string[];
  nice_to_have: string[];
  zoning: string[];
  avoid: string[];
}

export interface NotifySettings {
  email_enabled: boolean;
  email_to: string[];
  top_n: number;
}

export interface ProfileIn {
  name: string;
  criteria: Criteria;
  schedule_cron: string;
  timezone: string;
  enabled: boolean;
  notify: NotifySettings;
}

export interface Profile extends ProfileIn {
  id: number;
  created_at: string;
  updated_at: string;
  next_run_at: string | null;
  /** Demo sessions don't see email addresses. */
  email_hidden?: boolean;
}

export type Condition = "good" | "needs_updating" | "unverified";
export type ListingState = "active" | "removed" | "dismissed" | "rejected";

export interface Listing {
  id: number;
  profile_id: number;
  address: string;
  city: string;
  state: string;
  zip: string | null;
  price: number | null;
  beds: number | null;
  baths: number | null;
  acres: number | null;
  sqft: number | null;
  year_built: number | null;
  anchor: string | null;
  drive_hours: number | null;
  drive_km: number | null;
  condition: Condition;
  condition_notes: string;
  url: string | null;
  mls_number: string | null;
  /** Other working places it's listed, besides the main link. */
  also_on: ListingSource[];
  listing_state: ListingState;
  removed_reason: string | null;
  reject_reason: string | null;
  user_included: boolean;
  market_status: "active" | "pending" | "contingent";
  reviewed: boolean;
  first_seen: string;
  last_checked: string | null;
  is_new: boolean;
  previous_price: number | null;
}

export interface ListingSource {
  site: string;
  name: string;
  url: string;
  last_seen: string;
  dead: boolean;
}

export interface ListingEvent {
  id: number;
  run_id: number | null;
  kind: string;
  old_value: string | null;
  new_value: string | null;
  note: string | null;
  created_at: string;
}

export interface ListingDetail extends Listing {
  events: ListingEvent[];
}

export interface Excluded {
  id: number;
  address: string;
  city: string;
  state: string;
  reason: string;
  excluded_on: string;
}

export interface RunProgress {
  phase: "search" | "recheck" | "reread";
  done: number;
  total: number;
  current: string;
}

export interface RunSummary {
  progress?: RunProgress;
  added?: string[];
  removed?: { listing: string; reason: string }[];
  price_changes?: { listing: string; old: number; new: number }[];
  relisted?: string[];
  rejected?: { listing: string; reason: string }[];
  status_changes?: { listing: string; old: string; new: string }[];
  condition_changes?: { listing: string; old: string; new: string }[];
  skipped_excluded?: string[];
  skipped_regions?: string[];
  errors?: string[];
  usage?: Usage;
  region_stats?: Record<
    string,
    {
      added: number;
      reported: number;
      seen_tracked: number;
      fetch_budget: number;
      tier?: "full" | "sweep";
      why?: string;
      model?: string;
      missed_by_sweeps?: string[];
      usage?: Usage;
    }
  >;
  checks?: {
    seen_in_search: number;
    status_checked: number;
    skipped_recent: number;
    reread: number;
    new_read?: number;
  };
  sweep_misses?: { listing: string; county: string; days_on_market: number }[];
  sites?: Record<string, { used: number; blocked: number }>;
  active_count?: number;
  imported_from?: string;
  email?: string;
  listings_imported?: number;
  split_from?: string;
  listings_moved?: number;
  excluded_imported?: number;
}

export interface UsageCounts {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  web_searches: number;
  web_fetches: number;
}

export interface Usage extends UsageCounts {
  /** Estimated model-token cost in USD (web search/fetch fees not included). */
  est_cost_usd?: number | null;
  by_model?: Record<string, UsageCounts & { est_cost_usd: number | null }>;
}

export type RunStatus = "queued" | "running" | "succeeded" | "partial" | "failed" | "cancelled";

export interface Run {
  id: number;
  profile_id: number;
  trigger: string;
  status: RunStatus;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  summary: RunSummary;
  stopping: boolean;
}

export interface RunDetail extends Run {
  log: string;
}

export interface Stats {
  active: number;
  new_this_run: number;
  needs_updating: number;
  unreviewed: number;
  price_changes_last_run: number;
  removed_last_run: number;
  excluded: number;
  rejected: number;
  by_anchor: Record<string, number>;
  last_run: Run | null;
}

// Setup wizard (backend/src/house_agent/agent/suggest.py)
export interface SuggestIn {
  country: Country;
  anchors: { name: string; max_drive_hours: number }[];
  property_types: string[];
  min_acres: number | null;
  max_price: number | null;
}

export interface ResolvedAnchor {
  input: string;
  name: string;
  code: string;
  state: string;
}

export interface SuggestedRegion {
  name: string;
  state: string;
  anchor: string;
  est_drive_hours: number;
  est_drive_km?: number | null;
  note: string;
}

export interface SuggestOut {
  anchors: ResolvedAnchor[];
  regions: SuggestedRegion[];
}

export interface Feedback {
  id: number;
  listing_id: number | null;
  listing_label: string;
  agent_reason: string;
  user_reason: string;
  created_at: string;
}
