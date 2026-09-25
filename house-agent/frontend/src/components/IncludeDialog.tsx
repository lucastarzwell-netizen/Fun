import { useEffect, useRef, useState } from "react";
import type { Listing } from "../lib/types";

export function IncludeDialog({
  listing,
  onCancel,
  onConfirm,
}: {
  listing: Listing;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => ref.current?.showModal(), []);
  const ok = reason.trim().length >= 3;

  return (
    <dialog
      ref={ref}
      onClose={onCancel}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-2xl bg-white p-0 text-stone-800 shadow-xl backdrop:bg-stone-900/40 dark:bg-stone-900 dark:text-stone-100"
    >
      <form
        method="dialog"
        className="space-y-4 p-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (ok) onConfirm(reason.trim());
        }}
      >
        <div>
          <h2 className="font-display text-lg font-semibold">Include this listing anyway?</h2>
          <p className="mt-1 text-sm text-stone-500">
            {listing.address}, {listing.city} moves to your Listings. Tell the agent why, and it will use your
            reason to judge similar listings in future searches.
          </p>
        </div>
        {listing.reject_reason && (
          <div className="rounded-lg bg-stone-100 px-3 py-2 text-sm dark:bg-stone-800">
            <span className="font-medium">Agent's reason: </span>
            {listing.reject_reason}
          </div>
        )}
        <label className="block space-y-1">
          <span className="text-sm font-medium">Why should it have been included?</span>
          <textarea
            autoFocus
            required
            rows={3}
            className="input"
            placeholder="e.g. A new roof is fine; I only want to skip foundation problems."
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={!ok}>
            Include it
          </button>
        </div>
      </form>
    </dialog>
  );
}
