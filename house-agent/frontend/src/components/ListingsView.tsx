import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LayoutGrid, Rows3, Search } from "lucide-react";
import { api } from "../lib/api";
import { cx, money, shortDate } from "../lib/format";
import { statusLabel } from "../lib/listing";
import { useLocal } from "../lib/useLocal";
import type { Listing, Profile, Stats } from "../lib/types";
import { DismissDialog } from "./DismissDialog";
import { ListingCard } from "./ListingCard";
import { ListingTable } from "./ListingTable";
import { StatTiles } from "./StatTiles";

type StatusFilter = "all" | "new" | "good" | "needs_updating" | "unverified";
type SortKey = "default" | "price" | "acres" | "drive" | "newest";

const STATUS_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "new", label: "New" },
  { key: "good", label: "Active" },
  { key: "needs_updating", label: "Needs updating" },
  { key: "unverified", label: "Unverified" },
];

const SORTS: { key: SortKey; label: string }[] = [
  { key: "default", label: "Airport, status, price" },
  { key: "price", label: "Price: low to high" },
  { key: "acres", label: "Acres: most first" },
  { key: "drive", label: "Drive: shortest first" },
  { key: "newest", label: "Newest first" },
];

function sortListings(list: Listing[], key: SortKey) {
  const byPrice = (a: Listing, b: Listing) => (a.price ?? 0) - (b.price ?? 0);
  const copy = [...list];
  switch (key) {
    case "price":
      return copy.sort(byPrice);
    case "acres":
      return copy.sort((a, b) => (b.acres ?? 0) - (a.acres ?? 0));
    case "drive":
      return copy.sort((a, b) => (a.drive_hours ?? 99) - (b.drive_hours ?? 99));
    case "newest":
      return copy.sort((a, b) => b.first_seen.localeCompare(a.first_seen) || byPrice(a, b));
    default:
      return copy.sort(
        (a, b) =>
          (a.anchor ?? "").localeCompare(b.anchor ?? "") ||
          statusLabel(a).rank - statusLabel(b).rank ||
          byPrice(a, b),
      );
  }
}

export function ListingsView({ profile, stats }: { profile: Profile; stats: Stats | undefined }) {
  const qc = useQueryClient();
  const { data: listings = [], isLoading } = useQuery({
    queryKey: ["listings", profile.id],
    queryFn: () => api.listings(profile.id),
  });

  const [view, setView] = useLocal<"cards" | "table">("listings.view", "cards");
  const [sort, setSort] = useLocal<SortKey>("listings.sort", "default");
  const [hideReviewed, setHideReviewed] = useLocal("listings.hideReviewed", false);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [anchors, setAnchors] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [maxPrice, setMaxPrice] = useState<number | "">("");
  const [minAcres, setMinAcres] = useState<number | "">("");
  const [dismissing, setDismissing] = useState<Listing | null>(null);
  const [showRemoved, setShowRemoved] = useState(false);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["listings", profile.id] });
    qc.invalidateQueries({ queryKey: ["stats", profile.id] });
    qc.invalidateQueries({ queryKey: ["excluded", profile.id] });
  };

  const reviewed = useMutation({
    mutationFn: ({ id, value }: { id: number; value: boolean }) => api.setReviewed(id, value),
    onMutate: async ({ id, value }) => {
      await qc.cancelQueries({ queryKey: ["listings", profile.id] });
      qc.setQueryData<Listing[]>(["listings", profile.id], (old) =>
        old?.map((l) => (l.id === id ? { ...l, reviewed: value } : l)),
      );
    },
    onSettled: invalidate,
  });

  const dismiss = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) => api.dismiss(id, reason),
    onSuccess: invalidate,
  });

  const anchorCodes = useMemo(
    () => [...new Set(listings.map((l) => l.anchor ?? "?"))].sort(),
    [listings],
  );

  const filtered = useMemo(() => {
    const q = text.trim().toLowerCase();
    return sortListings(
      listings.filter((l) => {
        if (hideReviewed && l.reviewed) return false;
        if (anchors.length && !anchors.includes(l.anchor ?? "?")) return false;
        if (status === "new" && !l.is_new) return false;
        if (status !== "all" && status !== "new" && l.condition !== status) return false;
        if (maxPrice !== "" && (l.price ?? 0) > maxPrice) return false;
        if (minAcres !== "" && (l.acres ?? 0) < minAcres) return false;
        if (q && !`${l.address} ${l.city} ${l.state} ${l.condition_notes}`.toLowerCase().includes(q))
          return false;
        return true;
      }),
      sort,
    );
  }, [listings, hideReviewed, anchors, status, maxPrice, minAcres, text, sort]);

  const toggleAnchor = (code: string) =>
    setAnchors((cur) => (cur.includes(code) ? cur.filter((c) => c !== code) : [...cur, code]));

  return (
    <div className="space-y-5">
      <StatTiles stats={stats} />

      <div className="card space-y-3 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-48 flex-1">
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400" />
            <input
              className="input pl-9"
              placeholder="Search address, town, notes…"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>
          <select className="input w-auto" value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
          <div className="flex rounded-lg border border-stone-300 p-0.5 dark:border-stone-700">
            {(["cards", "table"] as const).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={cx(
                  "rounded-md p-1.5",
                  view === v ? "bg-pine-600 text-white" : "text-stone-500 hover:text-stone-800 dark:hover:text-stone-200",
                )}
                title={v === "cards" ? "Card view" : "Table view"}
              >
                {v === "cards" ? <LayoutGrid size={16} /> : <Rows3 size={16} />}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <div className="flex flex-wrap gap-1">
            {STATUS_FILTERS.map((f) => (
              <Chip key={f.key} active={status === f.key} onClick={() => setStatus(f.key)}>
                {f.label}
              </Chip>
            ))}
          </div>
          <div className="flex flex-wrap gap-1">
            {anchorCodes.map((code) => (
              <Chip key={code} active={anchors.includes(code)} onClick={() => toggleAnchor(code)}>
                {code}
                <span className="text-xs opacity-70">{stats?.by_anchor[code] ?? ""}</span>
              </Chip>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-stone-600 dark:text-stone-400">
            Max $
            <input
              type="number"
              step={5000}
              className="input w-28 py-1"
              placeholder="any"
              value={maxPrice}
              onChange={(e) => setMaxPrice(e.target.value === "" ? "" : Number(e.target.value))}
            />
          </label>
          <label className="flex items-center gap-1.5 text-stone-600 dark:text-stone-400">
            Min acres
            <input
              type="number"
              step={0.5}
              className="input w-20 py-1"
              placeholder="any"
              value={minAcres}
              onChange={(e) => setMinAcres(e.target.value === "" ? "" : Number(e.target.value))}
            />
          </label>
          <label className="flex items-center gap-2 text-stone-600 dark:text-stone-400">
            <input
              type="checkbox"
              className="size-4 accent-pine-600"
              checked={hideReviewed}
              onChange={(e) => setHideReviewed(e.target.checked)}
            />
            Hide reviewed
          </label>
          <span className="ml-auto text-stone-500">
            {filtered.length} of {listings.length}
          </span>
        </div>
      </div>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="card h-56 animate-pulse bg-stone-100 dark:bg-stone-800" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="card p-10 text-center text-stone-500">
          {listings.length === 0
            ? "No listings yet. Run a search to get started."
            : "Nothing matches these filters."}
        </div>
      ) : view === "cards" ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((l) => (
            <ListingCard
              key={l.id}
              listing={l}
              onReviewed={(value) => reviewed.mutate({ id: l.id, value })}
              onDismiss={() => setDismissing(l)}
            />
          ))}
        </div>
      ) : (
        <ListingTable
          listings={filtered}
          onReviewed={(l, value) => reviewed.mutate({ id: l.id, value })}
          onDismiss={setDismissing}
        />
      )}

      <div>
        <button className="btn-ghost -ml-3" onClick={() => setShowRemoved(!showRemoved)}>
          {showRemoved ? "Hide" : "Show"} removed listings
        </button>
        {showRemoved && <RemovedList profileId={profile.id} />}
      </div>

      {dismissing && (
        <DismissDialog
          listing={dismissing}
          onCancel={() => setDismissing(null)}
          onConfirm={(reason) => {
            dismiss.mutate({ id: dismissing.id, reason });
            setDismissing(null);
          }}
        />
      )}
    </div>
  );
}

function RemovedList({ profileId }: { profileId: number }) {
  const { data = [] } = useQuery({
    queryKey: ["listings", profileId, "removed"],
    queryFn: () => api.listings(profileId, "removed"),
  });
  if (!data.length) return <p className="mt-2 text-sm text-stone-500">Nothing removed yet.</p>;
  return (
    <ul className="card mt-2 divide-y divide-stone-100 text-sm dark:divide-stone-800">
      {data.map((l) => (
        <li key={l.id} className="flex flex-wrap items-center gap-x-3 px-4 py-2">
          <span className="font-medium">{l.address}</span>
          <span className="text-stone-500">
            {l.city}, {l.state}
          </span>
          <span className="tabular-nums text-stone-500">{money(l.price)}</span>
          <span className="ml-auto text-stone-500">
            {l.removed_reason} · {shortDate(l.last_checked)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cx(
        "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-sm transition",
        active
          ? "border-pine-600 bg-pine-600 text-white"
          : "border-stone-300 text-stone-600 hover:border-pine-500 dark:border-stone-700 dark:text-stone-300",
      )}
    >
      {children}
    </button>
  );
}
