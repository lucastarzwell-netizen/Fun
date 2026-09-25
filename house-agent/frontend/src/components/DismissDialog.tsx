import { useEffect, useRef, useState } from "react";
import type { Listing } from "../lib/types";

const QUICK = ["Too far", "Location", "Layout / size", "Condition", "Price", "Not interested"];

export function DismissDialog({
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

  return (
    <dialog
      ref={ref}
      onClose={onCancel}
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-2xl bg-white p-0 text-stone-800 shadow-xl backdrop:bg-stone-900/40 dark:bg-stone-900 dark:text-stone-100"
    >
      <form
        method="dialog"
        className="space-y-4 p-5"
        onSubmit={(e) => {
          e.preventDefault();
          onConfirm(reason.trim() || "Dismissed");
        }}
      >
        <div>
          <h2 className="font-display text-lg font-semibold">Rule out this listing?</h2>
          <p className="mt-1 text-sm text-stone-500">
            {listing.address}, {listing.city} will move to the Excluded list and the agent won't add it
            back. You can restore it later.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {QUICK.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => setReason(q)}
              className="rounded-full border border-stone-300 px-2.5 py-1 text-xs hover:border-pine-500 hover:text-pine-700 dark:border-stone-700"
            >
              {q}
            </button>
          ))}
        </div>
        <input
          autoFocus
          className="input"
          placeholder="Reason (optional)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" className="btn bg-rose-600 text-white hover:bg-rose-700">
            Rule out
          </button>
        </div>
      </form>
    </dialog>
  );
}
