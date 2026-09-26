import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { dateTime, money } from "../lib/format";
import type { ListingEvent } from "../lib/types";

function describe(e: ListingEvent) {
  switch (e.kind) {
    case "added":
      return `Found at ${money(Number(e.new_value))}`;
    case "imported":
      return "Imported from Google Sheet";
    case "price_change":
      return `Price ${money(Number(e.old_value))} → ${money(Number(e.new_value))}`;
    case "removed":
      return `Removed: ${e.note ?? ""}`;
    case "relisted":
      return "Back on the market";
    case "condition_change":
      return `Condition ${e.old_value?.replace("_", " ")} → ${e.new_value?.replace("_", " ")}`;
    case "dismissed":
      return `Ruled out${e.note ? `: ${e.note}` : ""}`;
    case "restored":
      return "Restored from Excluded";
    case "rejected":
      return `Rejected: ${e.note ?? ""}`;
    case "now_matches":
      return "Now matches your search";
    case "included":
      return `Included by you${e.note ? `: "${e.note}"` : ""}`;
    case "status_change":
      return `Status ${e.old_value} → ${e.new_value}`.replace("contingent", "under contract");
    case "link_changed":
      return `Main link moved from ${e.old_value} to ${e.new_value}`;
    case "mls_changed":
      return `New MLS# ${e.new_value} (was ${e.old_value}): usually a relisting`;
    case "check_failed":
      return `Couldn't check listing${e.note ? ` (${e.note})` : ""}`;
    default:
      return e.kind;
  }
}

export function ListingHistory({ id }: { id: number }) {
  const { data, isLoading } = useQuery({ queryKey: ["listing", id], queryFn: () => api.listing(id) });
  if (isLoading) return <p className="text-xs text-stone-500">Loading…</p>;
  if (!data?.events.length) return <p className="text-xs text-stone-500">No history yet.</p>;
  return (
    <ol className="space-y-1.5 border-l border-stone-200 pl-3 dark:border-stone-700">
      {[...data.events].reverse().map((e) => (
        <li key={e.id} className="text-xs">
          <span className="text-stone-700 dark:text-stone-300">{describe(e)}</span>
          <span className="ml-2 text-stone-400">{dateTime(e.created_at)}</span>
        </li>
      ))}
    </ol>
  );
}
