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
