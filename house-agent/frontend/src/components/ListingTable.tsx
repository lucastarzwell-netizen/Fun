import { ExternalLink, X } from "lucide-react";
import { Badge } from "./Badge";
import { cx, money, num, shortDate } from "../lib/format";
import { statusLabel } from "../lib/listing";
import type { Listing } from "../lib/types";

export function ListingTable({
  listings,
  onReviewed,
  onDismiss,
}: {
  listings: Listing[];
  onReviewed: (l: Listing, value: boolean) => void;
  onDismiss: (l: Listing) => void;
}) {
  return (
    <div className="card overflow-x-auto">
      <table className="w-full min-w-[960px] text-sm">
        <thead className="border-b border-stone-200 bg-stone-50 text-left text-xs uppercase tracking-wide text-stone-500 dark:border-stone-800 dark:bg-stone-900/60">
          <tr>
            <th className="px-3 py-2.5">Status</th>
            <th className="px-3 py-2.5">Airport</th>
            <th className="px-3 py-2.5 text-right">Drive</th>
            <th className="px-3 py-2.5">Address</th>
            <th className="px-3 py-2.5 text-right">Price</th>
            <th className="px-3 py-2.5 text-right">Beds</th>
            <th className="px-3 py-2.5 text-right">Baths</th>
            <th className="px-3 py-2.5 text-right">Acres</th>
            <th className="px-3 py-2.5">Condition notes</th>
            <th className="px-3 py-2.5">First seen</th>
            <th className="px-3 py-2.5 text-center">Reviewed</th>
            <th className="px-3 py-2.5" />
          </tr>
        </thead>
        <tbody className="divide-y divide-stone-100 dark:divide-stone-800">
          {listings.map((l) => {
            const s = statusLabel(l);
            return (
              <tr key={l.id} className={cx("align-top hover:bg-sand-50 dark:hover:bg-stone-800/40", l.is_new && "bg-sky-50/50 dark:bg-sky-950/20")}>
                <td className="px-3 py-2">
                  <Badge tone={s.tone}>{s.label}</Badge>
                </td>
                <td className="px-3 py-2 font-medium">{l.anchor}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {num(l.drive_hours)}
                  {l.drive_km != null && <div className="text-xs text-stone-500">{Math.round(l.drive_km)} km</div>}
                </td>
                <td className="px-3 py-2">
                  <div className="font-medium">{l.address}</div>
                  <div className="text-xs text-stone-500">
                    {l.city}, {l.state}
                  </div>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {money(l.price)}
                  {l.previous_price != null && (
                    <div className="text-xs text-stone-400 line-through">{money(l.previous_price)}</div>
                  )}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{num(l.beds)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{num(l.baths)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{num(l.acres, 2)}</td>
                <td className="max-w-sm px-3 py-2 text-stone-600 dark:text-stone-400">{l.condition_notes}</td>
                <td className="px-3 py-2 whitespace-nowrap text-stone-500">{shortDate(l.first_seen)}</td>
                <td className="px-3 py-2 text-center">
                  <input
                    type="checkbox"
                    className="size-4 accent-pine-600"
                    checked={l.reviewed}
                    onChange={(e) => onReviewed(l, e.target.checked)}
                  />
                </td>
                <td className="px-3 py-2">
                  <div className="flex gap-1">
                    {l.url && (
                      <a href={l.url} target="_blank" rel="noreferrer" className="btn-ghost p-1.5" title="Open listing">
                        <ExternalLink size={15} />
                      </a>
                    )}
                    <button onClick={() => onDismiss(l)} className="btn-ghost p-1.5 hover:text-rose-700" title="Dismiss">
                      <X size={15} />
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
