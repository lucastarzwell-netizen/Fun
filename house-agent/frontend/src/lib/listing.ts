import type { Listing } from "./types";
import type { Tone } from "../components/Badge";

/** The sheet's Status column, derived from condition + is_new. */
export function statusLabel(l: Listing): { label: string; tone: Tone; rank: number } {
  if (l.is_new) return { label: "New this week", tone: "blue", rank: 0 };
  if (l.condition === "good") return { label: "Active", tone: "green", rank: 1 };
  if (l.condition === "needs_updating") return { label: "Needs updating", tone: "amber", rank: 2 };
  return { label: "Unverified", tone: "gray", rank: 3 };
}

export function conditionLabel(l: Listing): { label: string; tone: Tone } | null {
  if (!l.is_new) return null;
  if (l.condition === "needs_updating") return { label: "Needs updating", tone: "amber" };
  if (l.condition === "unverified") return { label: "Unverified", tone: "gray" };
  return null;
}
