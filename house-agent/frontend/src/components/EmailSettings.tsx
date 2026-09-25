import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Mail, X } from "lucide-react";
import { api } from "../lib/api";
import type { NotifySettings } from "../lib/types";
import { ChipGroup } from "./wizard/ui";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** On/off, a list of recipient addresses, and how many listings to include. */
export function EmailSettings({
  value,
  onChange,
}: {
  value: NotifySettings;
  onChange: (v: NotifySettings) => void;
}) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const status = useQuery({ queryKey: ["email-status"], queryFn: api.emailStatus, staleTime: 60_000 });

  const add = () => {
    const parts = draft.split(/[,;\s]+/).map((p) => p.trim()).filter(Boolean);
    if (!parts.length) return;
    const bad = parts.find((p) => !EMAIL.test(p));
    if (bad) {
      setError(`"${bad}" doesn't look like an email address.`);
      return;
    }
    const merged = [...value.email_to];
    for (const p of parts) if (!merged.some((m) => m.toLowerCase() === p.toLowerCase())) merged.push(p);
    if (merged.length > 10) {
      setError("Up to 10 addresses.");
      return;
    }
    onChange({ ...value, email_to: merged });
    setDraft("");
    setError(null);
  };

  return (
    <div className="space-y-4">
      <label className="flex items-center gap-2 text-sm font-medium">
        <input
          type="checkbox"
          className="size-4 accent-pine-600"
          checked={value.email_enabled}
          onChange={(e) => onChange({ ...value, email_enabled: e.target.checked })}
        />
        Email a summary with the top listings after each search
      </label>

      {value.email_enabled && (
        <>
          <div className="space-y-2">
            <div className="text-sm font-medium text-stone-700 dark:text-stone-300">Send to</div>
            <div className="flex flex-wrap gap-2">
              {value.email_to.map((addr) => (
                <span
                  key={addr}
                  className="inline-flex items-center gap-1 rounded-full bg-pine-50 py-1 pl-3 pr-1 text-sm text-pine-800 ring-1 ring-pine-600/20 dark:bg-pine-900/40 dark:text-pine-200"
                >
                  {addr}
                  <button
                    type="button"
                    title={`Remove ${addr}`}
                    className="rounded-full p-0.5 hover:bg-pine-100 dark:hover:bg-pine-800"
                    onClick={() => onChange({ ...value, email_to: value.email_to.filter((a) => a !== addr) })}
                  >
                    <X size={14} />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Mail size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400" />
                <input
                  type="email"
                  className="input pl-9"
                  placeholder={value.email_to.length ? "Add another address" : "name@example.com"}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === ",") {
                      e.preventDefault();
                      add();
                    }
                  }}
                  onBlur={add}
                />
              </div>
              <button type="button" className="btn-outline" onClick={add}>
                Add
              </button>
            </div>
            {error && <p className="text-sm text-rose-600">{error}</p>}
            {!value.email_to.length && !error && (
              <p className="text-sm text-stone-500">Add one or more addresses. Press Enter after each.</p>
            )}
          </div>
          <ChipGroup
            label="Listings to include"
            value={value.top_n}
            onChange={(n) => onChange({ ...value, top_n: n })}
            options={[3, 5, 10].map((n) => ({ value: n, label: `Top ${n}` }))}
          />
          {status.data && !status.data.configured && (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
              Email isn't set up on the server yet, so summaries won't send until it is. Your choices are saved
              either way.
            </p>
          )}
        </>
      )}
    </div>
  );
}
