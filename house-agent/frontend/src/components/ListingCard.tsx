import { useState } from "react";
import { Bath, BedDouble, Car, Check, ChevronDown, ExternalLink, Trees, X } from "lucide-react";
import { Badge } from "./Badge";
import { ListingHistory } from "./ListingHistory";
import { cx, driveLabel, money, num, shortDate } from "../lib/format";
import { statusLabel } from "../lib/listing";
import type { Listing } from "../lib/types";
import { useDemo } from "../lib/demo";

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
  const demo = useDemo();
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
            {l.mls_number && <span className="whitespace-nowrap text-xs text-stone-400"> · MLS# {l.mls_number}</span>}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <Badge tone={status.tone}>{status.label}</Badge>
          {l.is_new && l.condition === "needs_updating" && <Badge tone="amber">Needs updating</Badge>}
          {cut && <Badge tone="violet">Price cut</Badge>}
          {l.market_status === "pending" && <Badge tone="amber">Pending</Badge>}
          {l.market_status === "contingent" && <Badge tone="amber">Under contract</Badge>}
          {l.user_included && <Badge tone="gray">Included by you</Badge>}
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
          value={l.drive_hours != null ? `${driveLabel(l.drive_hours, l.drive_km)} to` : "—"}
        />
      </dl>

      {l.condition_notes && (
        <p className="mt-3 line-clamp-3 px-4 text-sm leading-relaxed text-stone-700 dark:text-stone-300">
          {l.condition_notes}
        </p>
      )}

      {l.also_on.length > 0 && (
        <p className="mt-2 px-4 text-xs text-stone-500">
          Also on:{" "}
          {l.also_on.map((s, i) => (
            <span key={s.site}>
              {i > 0 && " · "}
              <a href={s.url} target="_blank" rel="noreferrer" className="underline decoration-stone-300 hover:text-pine-700">
                {s.name}
              </a>
            </span>
          ))}
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

      <div className="mt-3 flex flex-wrap items-center gap-0.5 border-t border-stone-100 px-1 py-2 sm:px-1.5 dark:border-stone-800">
        {!demo && <button
          onClick={() => onReviewed(!l.reviewed)}
          className={cx(
            "btn gap-1 px-1.5 py-1.5 text-[13px] sm:gap-2 sm:px-2 sm:text-sm",
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
        </button>}
        <button onClick={() => setOpen(!open)} className="btn-ghost gap-1 px-1.5 py-1.5 text-[13px] sm:gap-2 sm:px-2 sm:text-sm" title="History">
          <ChevronDown size={15} className={cx("transition", open && "rotate-180")} />
          History
        </button>
        {l.url && (
          <a href={l.url} target="_blank" rel="noreferrer" className="btn-ghost gap-1 px-1.5 py-1.5 text-[13px] sm:gap-2 sm:px-2 sm:text-sm">
            <ExternalLink size={15} />
            Listing
          </a>
        )}
        {!demo && <button
          onClick={onDismiss}
          className="btn ml-auto gap-1 px-1.5 py-1.5 text-[13px] text-stone-500 sm:gap-2 sm:px-2 sm:text-sm hover:bg-rose-50 hover:text-rose-700 dark:hover:bg-rose-900/30"
          title="Dismiss this listing"
        >
          <X size={15} />
          Dismiss
        </button>}
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
