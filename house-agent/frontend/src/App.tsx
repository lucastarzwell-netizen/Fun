import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, History, Home, Loader2, LogOut, Monitor, Moon, Play, Plus, Settings2, Sun } from "lucide-react";
import { api } from "./lib/api";
import { cx, dateTime } from "./lib/format";
import { useTheme } from "./lib/theme";
import { useLocal } from "./lib/useLocal";
import { ListingsView } from "./components/ListingsView";
import { ExcludedView } from "./components/ExcludedView";
import { RunsView } from "./components/RunsView";
import { SettingsView } from "./components/SettingsView";
import { SetupWizard } from "./components/wizard/SetupWizard";
import { LoginScreen } from "./components/LoginScreen";

type Tab = "listings" | "excluded" | "runs" | "settings";

const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: "listings", label: "Listings", icon: <Home size={16} /> },
  { key: "excluded", label: "Excluded", icon: <Ban size={16} /> },
  { key: "runs", label: "Runs", icon: <History size={16} /> },
  { key: "settings", label: "Search settings", icon: <Settings2 size={16} /> },
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
      <header className="sticky top-0 z-10 border-b border-stone-200/80 bg-sand-50/85 backdrop-blur dark:border-stone-800 dark:bg-stone-950/85">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <div className="grid size-9 place-items-center rounded-xl bg-pine-600 text-sand-100 shadow-sm">
              <Home size={18} />
            </div>
            <div className="leading-tight">
              <div className="font-display text-lg font-semibold">House Agent</div>
              {profile && (
                <div className="text-xs text-stone-500">
                  {lastRun ? `Last run ${dateTime(lastRun.finished_at ?? lastRun.created_at)}` : "Not run yet"}
                  {profile.enabled && profile.next_run_at && ` · next ${dateTime(profile.next_run_at)}`}
                </div>
              )}
            </div>
          </div>

          <div className="ml-auto flex items-center gap-2">
            {profiles.data && profiles.data.length > 1 && (
              <select
                className="input w-auto"
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
            <button className="btn-ghost" onClick={() => setWizardOpen(true)} title="Set up another search">
              <Plus size={16} />
              <span className="hidden sm:inline">New search</span>
            </button>
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
            <button
              className="btn-primary"
              disabled={!profile || !!activeRun || start.isPending}
              onClick={() => start.mutate()}
            >
              {activeRun ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
              {activeRun ? "Searching…" : "Run search now"}
            </button>
          </div>
        </div>

        <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 sm:px-6">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={cx(
                "flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm font-medium whitespace-nowrap transition",
                tab === t.key
                  ? "border-pine-600 text-pine-700 dark:text-pine-300"
                  : "border-transparent text-stone-500 hover:text-stone-800 dark:hover:text-stone-200",
              )}
            >
              {t.icon}
              {t.label}
              {t.key === "excluded" && stats.data ? (
                <span className="rounded-full bg-stone-200 px-1.5 text-xs dark:bg-stone-800">{stats.data.excluded}</span>
              ) : null}
            </button>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {start.isError && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
            Couldn't start the search: {(start.error as Error).message}
          </div>
        )}
        {activeRun && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-4 py-2 text-sm text-sky-900 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-200">
            <Loader2 size={16} className="animate-spin" />
            The agent is checking listings and searching your regions. This can take a while; results
            appear when it's done.
          </div>
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
