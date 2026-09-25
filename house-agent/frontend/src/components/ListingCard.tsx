import { useState } from "react";
import { Bath, BedDouble, Car, Check, ChevronDown, ExternalLink, Trees, X } from "lucide-react";
import { Badge } from "./Badge";
import { ListingHistory } from "./ListingHistory";
import { cx, money, num, shortDate } from "../lib/format";
import { statusLabel } from "../lib/listing";
import type { Listing } from "../lib/types";

export function ListingCard({
  listing: l,
  onReviewed,
  onDismiss,
}: {
  listing: Listing;
  onReviewed: (value: boolean) => void;
  onDismiss: () => void;
}) {
  const [open, setOpen] = useState(false);
  const status = statusLabel(l);
  const cut = l.previous_price != null && l.price != null && l.price < l.previous_price;
  const raised = l.previous_price != null && l.price != null && l.price > l.previous_price;

  return (
    <article
      className={cx(
        "card flex flex-col overflow-hidden transition hover:shadow-md",
        l.is_new && "ring-2 ring-sky-400/60",
      )}
    >
      <div className="flex items-start justify-between gap-3 px-4 pt-4">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="text-xl font-semibold tabular-nums">{money(l.price)}</span>
            {(cut || raised) && (
              <span className="text-sm text-stone-400 line-through tabular-nums">
                {money(l.previous_price)}
              </span>
            )}
          </div>
          <h3 className="mt-0.5 truncate font-medium" title={l.address}>
            {l.address}
          </h3>
          <p className="text-sm text-stone-500">
            {l.city}, {l.state}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <Badge tone={status.tone}>{status.label}</Badge>
          {l.is_new && l.condition === "needs_updating" && <Badge tone="amber">Needs updating</Badge>}
          {cut && <Badge tone="violet">Price cut</Badge>}
        </div>
      </div>

      <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 px-4 text-sm text-stone-600 dark:text-stone-400">
        {/* Land has no bedrooms or bathrooms; don't show empty placeholders. */}
        {(l.beds != null || l.baths != null) && (
          <>
            <Fact icon={<BedDouble size={15} />} label={l.beds === 1 ? "bed" : "beds"} value={num(l.beds)} />
            <Fact icon={<Bath size={15} />} label={l.baths === 1 ? "bath" : "baths"} value={num(l.baths)} />
          </>
        )}
        <Fact icon={<Trees size={15} />} label={l.acres === 1 ? "acre" : "acres"} value={num(l.acres, 2)} />
        <Fact
          icon={<Car size={15} />}
          label={l.anchor ?? ""}
          value={l.drive_hours != null ? `${num(l.drive_hours)} hr to` : "—"}
        />
      </dl>

      {l.condition_notes && (
        <p className="mt-3 line-clamp-3 px-4 text-sm leading-relaxed text-stone-700 dark:text-stone-300">
          {l.condition_notes}
        </p>
      )}

      <div className="mt-auto px-4 pt-3 text-xs text-stone-400">
        First seen {shortDate(l.first_seen)} · checked {shortDate(l.last_checked)}
      </div>

      {open && (
        <div className="px-4 pt-3">
          <ListingHistory id={l.id} />
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-1 border-t border-stone-100 px-2 py-2 dark:border-stone-800">
        <button
          onClick={() => onReviewed(!l.reviewed)}
          className={cx(
            "btn px-2.5 py-1.5",
            l.reviewed
              ? "text-pine-700 hover:bg-pine-50 dark:text-pine-300 dark:hover:bg-pine-900/40"
              : "text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800",
          )}
          title="Mark reviewed"
        >
          <span
            className={cx(
              "grid size-4 place-items-center rounded border",
              l.reviewed ? "border-pine-600 bg-pine-600 text-white" : "border-stone-400",
            )}
          >
            {l.reviewed && <Check size={12} strokeWidth={3} />}
          </span>
          Reviewed
        </button>
        <button onClick={() => setOpen(!open)} className="btn-ghost px-2.5 py-1.5" title="History">
          <ChevronDown size={15} className={cx("transition", open && "rotate-180")} />
          History
        </button>
        <div className="ml-auto flex items-center gap-1">
          {l.url && (
            <a href={l.url} target="_blank" rel="noreferrer" className="btn-ghost px-2.5 py-1.5">
              <ExternalLink size={15} />
              Listing
            </a>
          )}
          <button
            onClick={onDismiss}
            className="btn px-2.5 py-1.5 text-stone-500 hover:bg-rose-50 hover:text-rose-700 dark:hover:bg-rose-900/30"
            title="Rule out this listing"
          >
            <X size={15} />
            Rule out
          </button>
        </div>
      </div>
    </article>
  );
}

function Fact({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-stone-400">{icon}</span>
      <dd className="tabular-nums">
        <span className="font-medium text-stone-800 dark:text-stone-200">{value}</span> {label}
      </dd>
    </div>
  );
}
