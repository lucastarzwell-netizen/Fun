import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Split } from "lucide-react";
import { api } from "../lib/api";
import type { Profile } from "../lib/types";

/** Move some of a search's locations (with their counties and listings) into new searches. */
export function SplitPanel({ profile }: { profile: Profile }) {
  const qc = useQueryClient();
  const anchors = profile.criteria.anchors;
  const [picked, setPicked] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<string[]>([]);

  const done = (names: string[]) => {
    setCreated(names);
    setPicked([]);
    setName("");
    qc.invalidateQueries();
  };
  const moveSome = useMutation({
    mutationFn: () => api.splitProfile(profile.id, picked, name.trim() || undefined),
    onSuccess: (p) => done([p.name]),
  });
  const onePerLocation = useMutation({
    mutationFn: async () => {
      const names: string[] = [];
      for (const a of anchors.slice(1)) names.push((await api.splitProfile(profile.id, [a.code])).name);
      return names;
    },
    onSuccess: done,
  });
  const busy = moveSome.isPending || onePerLocation.isPending;
  const error = (moveSome.error ?? onePerLocation.error) as Error | null;

  if (anchors.length < 2) return null;
  const allPicked = picked.length === anchors.length;
  return (
    <section className="card space-y-4 p-5">
      <div>
        <h3 className="font-semibold">Split this search</h3>
        <p className="text-sm text-stone-500">
          Move locations into a search of their own. Their counties and listings go with them, with their history
          (including rejected and removed ones). Excluded addresses and your feedback to the agent are copied to both.
          Past runs stay here.
        </p>
      </div>
      <div className="space-y-2">
        {anchors.map((a) => (
          <label key={a.code} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={picked.includes(a.code)}
              onChange={(e) =>
                setPicked(e.target.checked ? [...picked, a.code] : picked.filter((c) => c !== a.code))
              }
            />
            <span className="font-medium">{a.code}</span>
            <span className="truncate text-stone-500">{a.name}</span>
          </label>
        ))}
      </div>
      {picked.length > 0 && (
        <label className="block space-y-1">
          <span className="text-sm font-medium">Name for the new search</span>
          <input
            className="input"
            placeholder="Leave blank to name it after its locations"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
      )}
      {allPicked && <p className="text-sm text-amber-700">Leave at least one location in this search.</p>}
      {error && <p className="text-sm text-rose-600">{error.message}</p>}
      {created.length > 0 && (
        <p className="text-sm text-pine-700 dark:text-pine-300">
          Created {created.map((n) => `"${n}"`).join(", ")}. Pick it from the search menu at the top.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-outline"
          disabled={busy || picked.length === 0 || allPicked}
          onClick={() => moveSome.mutate()}
        >
          <Split size={16} /> {moveSome.isPending ? "Moving…" : "Move to a new search"}
        </button>
        <button
          type="button"
          className="btn-ghost"
          disabled={busy}
          onClick={() => {
            if (confirm(`Split "${profile.name}" into ${anchors.length} searches, one per location?`))
              onePerLocation.mutate();
          }}
        >
          {onePerLocation.isPending ? "Splitting…" : "One search per location"}
        </button>
      </div>
    </section>
  );
}
