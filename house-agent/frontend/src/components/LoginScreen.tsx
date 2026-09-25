import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Home, Loader2 } from "lucide-react";
import { api } from "../lib/api";

export function LoginScreen() {
  const qc = useQueryClient();
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => api.login(password),
    onSuccess: () => qc.invalidateQueries(),
  });

  return (
    <div className="grid min-h-screen place-items-center bg-sand-50 px-4 dark:bg-stone-950">
      <form
        className="card w-full max-w-sm space-y-5 p-6"
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate();
        }}
      >
        <div className="flex items-center gap-2.5">
          <div className="grid size-10 place-items-center rounded-xl bg-pine-600 text-sand-100">
            <Home size={20} />
          </div>
          <div>
            <h1 className="font-display text-xl font-semibold">House Agent</h1>
            <p className="text-sm text-stone-500">Sign in to see your searches</p>
          </div>
        </div>
        <label className="block space-y-1">
          <span className="text-sm font-medium">Password</span>
          <input
            type="password"
            autoFocus
            autoComplete="current-password"
            className="input py-2.5"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {login.isError && <p className="text-sm text-rose-600">That password didn't work.</p>}
        <button className="btn-primary w-full py-2.5" disabled={!password || login.isPending}>
          {login.isPending && <Loader2 size={16} className="animate-spin" />} Sign in
        </button>
      </form>
    </div>
  );
}
