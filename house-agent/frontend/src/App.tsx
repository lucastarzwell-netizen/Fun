import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CircleSlash, History, Home, Loader2, LogOut, Monitor, Moon, Play, Plus, Settings2, Square, Sun } from "lucide-react";
import { api } from "./lib/api";
import { cx, dateTime } from "./lib/format";
import { useTheme } from "./lib/theme";
import type { RunProgress } from "./lib/types";
import { useLocal } from "./lib/useLocal";
import { ListingsView } from "./components/ListingsView";
import { ExcludedView } from "./components/ExcludedView";
import { RejectedView } from "./components/RejectedView";
import { RunsView } from "./components/RunsView";
import { SettingsView } from "./components/SettingsView";
import { SetupWizard } from "./components/wizard/SetupWizard";
import { LoginScreen } from "./components/LoginScreen";
import { useDemo } from "./lib/demo";

type Tab = "listings" | "rejected" | "excluded" | "runs" | "settings";

const TABS: { key: Tab; label: string; short: string; icon: React.ReactNode }[] = [
  { key: "listings", label: "Listings", short: "Listings", icon: <Home size={16} /> },
  { key: "rejected", label: "Rejected", short: "Rejected", icon: <CircleSlash size={16} /> },
  { key: "excluded", label: "Excluded", short: "Excluded", icon: <Ban size={16} /> },
  { key: "runs", label: "Runs", short: "Runs", icon: <History size={16} /> },
  { key: "settings", label: "Search settings", short: "Settings", icon: <Settings2 size={16} /> },
];

export default function App() {
  const auth = useQuery({ queryKey: ["auth"], queryFn: api.me, staleTime: Infinity });
  if (auth.isLoading) return null;
  if (auth.data?.required && !auth.data.authenticated) return <LoginScreen />;
  return <Dashboard signOut={auth.data?.required ? api.logout : undefined} />;
}

function Dashboard({ signOut }: { signOut?: () => Promise<unknown> }) {
  const qc = useQueryClient();
  const [tab, setTab] = useLocal<Tab>("tab", "listings");
  const [profileId, setProfileId] = useLocal<number | null>("profileId", null);
  const [theme, setTheme] = useTheme();
  const [wizardOpen, setWizardOpen] = useState(false);
  const demo = useDemo();

  const profiles = useQuery({ queryKey: ["profiles"], queryFn: api.profiles });
  const profile = profiles.data?.find((p) => p.id === profileId) ?? profiles.data?.[0];
  useEffect(() => {
    if (profile && profile.id !== profileId) setProfileId(profile.id);
  }, [profile, profileId, setProfileId]);

  const runs = useQuery({
    queryKey: ["runs", profile?.id],
    queryFn: () => api.runs(profile!.id),
    enabled: !!profile,
    refetchInterval: (q) =>
      q.state.data?.some((r) => r.status === "running" || r.status === "queued") ? 4000 : false,
  });
  const activeRun = runs.data?.find((r) => r.status === "running" || r.status === "queued");

  const stats = useQuery({
    queryKey: ["stats", profile?.id],
    queryFn: () => api.stats(profile!.id),
    enabled: !!profile,
  });

  // Listings land county by county, so refresh them while a run is going.
  const progressKey = JSON.stringify(activeRun?.summary.progress ?? null);
  useEffect(() => {
    if (!activeRun || !profile) return;
    qc.invalidateQueries({ queryKey: ["listings", profile.id] });
    qc.invalidateQueries({ queryKey: ["stats", profile.id] });
  }, [progressKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // When a run finishes, refresh everything it may have changed.
  const [wasRunning, setWasRunning] = useState(false);
  useEffect(() => {
    if (activeRun) setWasRunning(true);
    else if (wasRunning) {
      setWasRunning(false);
      qc.invalidateQueries();
    }
  }, [activeRun, wasRunning, qc]);

  const start = useMutation({
    mutationFn: () => api.startRun(profile!.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs", profile?.id] }),
  });

  const stop = useMutation({
    mutationFn: (id: number) => api.stopRun(id),
    onSettled: () => qc.invalidateQueries({ queryKey: ["runs", profile?.id] }),
  });

  const lastRun = stats.data?.last_run;

  // Wait for the first load so a new account goes straight to setup without a flash.
  if (profiles.isLoading) return null;

  // First visit (no searches yet) or "New search": the guided setup.
  if (wizardOpen || (profiles.isSuccess && profiles.data.length === 0)) {
    return (
      <SetupWizard
        onCancel={profiles.data?.length ? () => setWizardOpen(false) : undefined}
        onDone={(p) => {
          setProfileId(p.id);
          setTab("listings");
          setWizardOpen(false);
        }}
      />
    );
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-stone-200/80 bg-sand-50/85 backdrop-blur sm:sticky sm:top-0 sm:z-10 dark:border-stone-800 dark:bg-stone-950/85">
        {/* Phones: brand + icon buttons on one row, search picker + Run on the next.
            Wider screens: everything on one row. */}
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 sm:px-6">
          <div className="flex min-w-0 flex-1 items-center gap-2.5">
            <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-pine-600 text-sand-100 shadow-sm">
              <Home size={18} />
            </div>
            <div className="min-w-0 leading-tight">
              <div className="flex items-center gap-2">
                <span className="font-display text-lg font-semibold">House Agent</span>
                {demo && (
                  <span
                    className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-200"
                    title="A read-only demo: look around; searches and changes are off."
                  >
                    Demo · read-only
                  </span>
                )}
              </div>
              {profile && (
                <div className="text-xs text-stone-500">
                  {lastRun ? `Last run ${dateTime(lastRun.finished_at ?? lastRun.created_at)}` : "Not run yet"}
                  {profile.enabled && profile.next_run_at && ` · next ${dateTime(profile.next_run_at)}`}
                </div>
              )}
            </div>
          </div>

          <div className="order-3 flex w-full items-center justify-end gap-2 sm:order-2 sm:w-auto">
            {profiles.data && profiles.data.length > 1 && (
              <select
                className="input min-w-0 flex-1 sm:w-auto sm:max-w-xs sm:flex-none"
                value={profile?.id}
                onChange={(e) => setProfileId(Number(e.target.value))}
              >
                {profiles.data.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            )}
            {!demo && <button
              className="btn-primary shrink-0"
              disabled={!profile || !!activeRun || start.isPending}
              onClick={() => start.mutate()}
            >
              {activeRun ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
              {activeRun ? "Searching…" : (
                <>
                  <span className="sm:hidden">Run now</span>
                  <span className="hidden sm:inline">Run search now</span>
                </>
              )}
            </button>}
          </div>

          <div className="order-2 flex shrink-0 items-center gap-1 sm:order-3">
            {!demo && (
              <button className="btn-ghost p-2 sm:px-3.5" onClick={() => setWizardOpen(true)} title="Set up another search">
                <Plus size={18} />
                <span className="hidden sm:inline">New search</span>
              </button>
            )}
            {signOut && (
              <button
                className="btn-ghost p-2"
                title="Sign out"
                onClick={() => signOut().then(() => qc.invalidateQueries())}
              >
                <LogOut size={18} />
              </button>
            )}
            <button
              className="btn-ghost p-2"
              title={`Theme: ${theme}`}
              onClick={() => setTheme(theme === "system" ? "light" : theme === "light" ? "dark" : "system")}
            >
              {theme === "system" ? <Monitor size={18} /> : theme === "light" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
          </div>
        </div>

        <nav className="mx-auto flex max-w-7xl overflow-x-auto px-2 sm:gap-1 sm:px-6">
          {TABS.map((t) => {
            const count =
              stats.data && t.key === "excluded"
                ? stats.data.excluded
                : stats.data && t.key === "rejected"
                  ? stats.data.rejected
                  : null;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cx(
                  // Phones: five equal columns, icon over a short label. Wider: icon, label, count in a row.
                  "flex min-w-0 flex-1 flex-col items-center gap-0.5 border-b-2 px-1 py-2 text-[11px] font-medium whitespace-nowrap transition",
                  "sm:flex-none sm:flex-row sm:gap-1.5 sm:px-3 sm:py-2.5 sm:text-sm",
                  tab === t.key
                    ? "border-pine-600 text-pine-700 dark:text-pine-300"
                    : "border-transparent text-stone-500 hover:text-stone-800 dark:hover:text-stone-200",
                )}
              >
                <span className="relative">
                  {t.icon}
                  {count ? (
                    <span className="absolute -top-1.5 left-3 rounded-full bg-stone-200 px-1 text-[10px] leading-4 text-stone-700 sm:hidden dark:bg-stone-700 dark:text-stone-200">
                      {count}
                    </span>
                  ) : null}
                </span>
                <span className="sm:hidden">{t.short}</span>
                <span className="hidden sm:inline">{t.label}</span>
                {count != null && (
                  <span className="hidden rounded-full bg-stone-200 px-1.5 text-xs sm:inline dark:bg-stone-800">
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {start.isError && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
            Couldn't start the search: {(start.error as Error).message}
          </div>
        )}
        {activeRun && (
          <RunBanner
            progress={activeRun.summary.progress}
            stopping={activeRun.stopping || stop.isPending}
            onStop={demo ? undefined : () => stop.mutate(activeRun.id)}
          />
        )}

        {profiles.isLoading ? (
          <p className="text-stone-500">Loading…</p>
        ) : profiles.isError ? (
          <div className="card p-8 text-center">
            <p className="font-medium">Can't reach the House Agent API.</p>
            <p className="mt-1 text-sm text-stone-500">Start the backend with <code>house-agent serve</code>.</p>
          </div>
        ) : !profile ? null : tab === "listings" ? (
          <ListingsView profile={profile} stats={stats.data} />
        ) : tab === "rejected" ? (
          <RejectedView profileId={profile.id} />
        ) : tab === "excluded" ? (
          <ExcludedView profileId={profile.id} />
        ) : tab === "runs" ? (
          <RunsView profileId={profile.id} />
        ) : (
          <SettingsView profile={profile} />
        )}
      </main>
    </div>
  );
}

function RunBanner({
  progress,
  stopping,
  onStop,
}: {
  progress?: RunProgress;
  stopping: boolean;
  onStop?: () => void;
}) {
  const pct = progress && progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
  const label = !progress
    ? "Starting the search…"
    : progress.phase === "recheck"
      ? `Checking tracked listings the search didn't show (${progress.done} of ${progress.total})`
      : progress.phase === "reread"
        ? `Reading new and changed listings (${progress.done} of ${progress.total})`
        : `Searching ${progress.current} (${progress.done + 1} of ${progress.total} counties)`;
  return (
    <div className="mb-4 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-200">
      <div className="flex items-center gap-2">
        <Loader2 size={16} className="shrink-0 animate-spin" />
        <span className="font-medium">{label}</span>
        <span className="ml-auto hidden text-xs opacity-80 md:inline">
          {stopping ? "Stopping after the current step…" : "New listings show up as each county finishes."}
        </span>
        {onStop && <button
          className="btn ml-auto shrink-0 border border-sky-300 bg-white px-2.5 py-1 text-xs text-sky-900 hover:bg-sky-100 md:ml-2 dark:border-sky-800 dark:bg-sky-950 dark:text-sky-100"
          disabled={stopping}
          onClick={() => {
            if (confirm("Stop this search? Listings it has already found are kept.")) onStop();
          }}
        >
          <Square size={12} /> {stopping ? "Stopping…" : "Stop search"}
        </button>}
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-sky-200/70 dark:bg-sky-900">
        <div className="h-full rounded-full bg-sky-600 transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
