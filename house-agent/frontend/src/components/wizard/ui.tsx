import type { ReactNode } from "react";
import { Check } from "lucide-react";
import { cx } from "../../lib/format";

export function Question({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-display text-2xl font-semibold sm:text-3xl">{title}</h2>
        {hint && <p className="mt-2 text-stone-500 dark:text-stone-400">{hint}</p>}
      </div>
      {children}
    </div>
  );
}

export function OptionCard({
  selected,
  onClick,
  title,
  hint,
  multi,
}: {
  selected: boolean;
  onClick: () => void;
  title: string;
  hint?: string;
  multi?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        "flex w-full items-start gap-3 rounded-xl border p-4 text-left transition",
        selected
          ? "border-pine-600 bg-pine-50 ring-1 ring-pine-600 dark:bg-pine-900/30"
          : "border-stone-300 bg-white hover:border-pine-400 dark:border-stone-700 dark:bg-stone-900",
      )}
    >
      <span
        className={cx(
          "mt-0.5 grid size-5 shrink-0 place-items-center border",
          multi ? "rounded" : "rounded-full",
          selected ? "border-pine-600 bg-pine-600 text-white" : "border-stone-400",
        )}
      >
        {selected && <Check size={13} strokeWidth={3} />}
      </span>
      <span>
        <span className="block font-medium">{title}</span>
        {hint && <span className="mt-0.5 block text-sm text-stone-500 dark:text-stone-400">{hint}</span>}
      </span>
    </button>
  );
}

export function ChipGroup<T extends string | number | null>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div>
      <div className="mb-2 text-sm font-medium text-stone-700 dark:text-stone-300">{label}</div>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => (
          <button
            key={String(o.value)}
            type="button"
            onClick={() => onChange(o.value)}
            className={cx(
              "rounded-full border px-4 py-1.5 text-sm transition",
              value === o.value
                ? "border-pine-600 bg-pine-600 text-white"
                : "border-stone-300 bg-white hover:border-pine-400 dark:border-stone-700 dark:bg-stone-900",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function hoursLabel(h: number) {
  if (h < 1) return `${Math.round(h * 60)} min`;
  return `${h % 1 === 0 ? h : h.toFixed(1).replace(/\.0$/, "")} hr`;
}

export function MultiChips({
  label,
  hint,
  options,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  options: readonly string[];
  value: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <div>
      <div className="text-sm font-medium text-stone-700 dark:text-stone-300">{label}</div>
      {hint && <div className="text-sm text-stone-500">{hint}</div>}
      <div className="mt-2 flex flex-wrap gap-2">
        {options.map((o) => {
          const on = value.includes(o);
          return (
            <button
              key={o}
              type="button"
              onClick={() => onChange(on ? value.filter((x) => x !== o) : [...value, o])}
              className={cx(
                "inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm transition",
                on
                  ? "border-pine-600 bg-pine-600 text-white"
                  : "border-stone-300 bg-white hover:border-pine-400 dark:border-stone-700 dark:bg-stone-900",
              )}
            >
              {on && <Check size={13} strokeWidth={3} />}
              {o}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function CheckList({
  label,
  hint,
  options,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  options: readonly string[];
  value: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <div>
      <div className="text-sm font-medium text-stone-700 dark:text-stone-300">{label}</div>
      {hint && <div className="text-sm text-stone-500">{hint}</div>}
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {options.map((o) => {
          const on = value.includes(o);
          return (
            <label key={o} className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-pine-600"
                checked={on}
                onChange={() => onChange(on ? value.filter((x) => x !== o) : [...value, o])}
              />
              {o}
            </label>
          );
        })}
      </div>
    </div>
  );
}
