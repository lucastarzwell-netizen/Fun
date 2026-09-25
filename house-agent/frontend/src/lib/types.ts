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

export interface Criteria {
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
  extra_instructions: string;
}

export interface ProfileIn {
  name: string;
  criteria: Criteria;
  schedule_cron: string;
  timezone: string;
  enabled: boolean;
}

export interface Profile extends ProfileIn {
  id: number;
  created_at: string;
  updated_at: string;
  next_run_at: string | null;
}

export type Condition = "good" | "needs_updating" | "unverified";
export type ListingState = "active" | "removed" | "dismissed";

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
  condition: Condition;
  condition_notes: string;
  url: string | null;
  listing_state: ListingState;
  removed_reason: string | null;
  reviewed: boolean;
  first_seen: string;
  last_checked: string | null;
  is_new: boolean;
  previous_price: number | null;
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

export interface RunSummary {
  added?: string[];
  removed?: { listing: string; reason: string }[];
  price_changes?: { listing: string; old: number; new: number }[];
  relisted?: string[];
  condition_changes?: { listing: string; old: string; new: string }[];
  skipped_excluded?: string[];
  skipped_regions?: string[];
  errors?: string[];
  usage?: Record<string, number>;
  active_count?: number;
  imported_from?: string;
  listings_imported?: number;
  excluded_imported?: number;
}

export type RunStatus = "queued" | "running" | "succeeded" | "partial" | "failed";

export interface Run {
  id: number;
  profile_id: number;
  trigger: string;
  status: RunStatus;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  summary: RunSummary;
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
  by_anchor: Record<string, number>;
  last_run: Run | null;
}

// Setup wizard (backend/src/house_agent/agent/suggest.py)
export interface SuggestIn {
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
  note: string;
}

export interface SuggestOut {
  anchors: ResolvedAnchor[];
  regions: SuggestedRegion[];
}
