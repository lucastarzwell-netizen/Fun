import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RotateCcw } from "lucide-react";
import { api } from "../lib/api";
import { shortDate } from "../lib/format";

export function ExcludedView({ profileId }: { profileId: number }) {
  const qc = useQueryClient();
  const { data = [] } = useQuery({
    queryKey: ["excluded", profileId],
    queryFn: () => api.excluded(profileId),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["excluded", profileId] });
    qc.invalidateQueries({ queryKey: ["listings", profileId] });
    qc.invalidateQueries({ queryKey: ["stats", profileId] });
  };
  const restore = useMutation({ mutationFn: api.restoreExcluded, onSuccess: refresh });
  const add = useMutation({
    mutationFn: (body: { address: string; city: string; state: string; reason: string }) =>
      api.addExcluded(profileId, body),
    onSuccess: () => {
      refresh();
      setForm({ address: "", city: "", state: "", reason: "" });
    },
  });
  const [form, setForm] = useState({ address: "", city: "", state: "", reason: "" });

  return (
    <div className="space-y-5">
      <div>
        <h2 className="font-display text-xl font-semibold">Excluded addresses</h2>
        <p className="text-sm text-stone-500">
          Houses you've ruled out. The agent never adds these back, even if they still match.
        </p>
      </div>

      <form
        className="card grid gap-2 p-3 sm:grid-cols-[2fr_1.2fr_4rem_1.5fr_auto]"
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate({ ...form, reason: form.reason || "Ruled out" });
        }}
      >
        <input className="input" placeholder="Street address" required value={form.address}
          onChange={(e) => setForm({ ...form, address: e.target.value })} />
        <input className="input" placeholder="City" required value={form.city}
          onChange={(e) => setForm({ ...form, city: e.target.value })} />
        <input className="input uppercase" placeholder="ST" required maxLength={2} minLength={2} value={form.state}
          onChange={(e) => setForm({ ...form, state: e.target.value.toUpperCase() })} />
        <input className="input" placeholder="Reason" value={form.reason}
          onChange={(e) => setForm({ ...form, reason: e.target.value })} />
        <button className="btn-primary" disabled={add.isPending}>
          <Plus size={16} /> Exclude
        </button>
      </form>

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead className="border-b border-stone-200 bg-stone-50 text-left text-xs uppercase tracking-wide text-stone-500 dark:border-stone-800 dark:bg-stone-900/60">
            <tr>
              <th className="px-4 py-2.5">Address</th>
              <th className="px-4 py-2.5">Reason</th>
              <th className="px-4 py-2.5">Excluded</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100 dark:divide-stone-800">
            {data.map((e) => (
              <tr key={e.id}>
                <td className="px-4 py-2">
                  <span className="font-medium">{e.address}</span>
                  <span className="text-stone-500">, {e.city}, {e.state}</span>
                </td>
                <td className="px-4 py-2 text-stone-600 dark:text-stone-400">{e.reason}</td>
                <td className="px-4 py-2 text-stone-500">{shortDate(e.excluded_on)}</td>
                <td className="px-4 py-2 text-right">
                  <button className="btn-ghost px-2 py-1" onClick={() => restore.mutate(e.id)}>
                    <RotateCcw size={14} /> Restore
                  </button>
                </td>
              </tr>
            ))}
            {!data.length && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-stone-500">Nothing excluded.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
