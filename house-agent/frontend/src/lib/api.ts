import type {
  Excluded,
  Feedback,
  Listing,
  ListingDetail,
  Profile,
  ProfileIn,
  Run,
  RunDetail,
  Stats,
  SuggestIn,
  SuggestOut,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    // Sends cookies once a login module is added; harmless until then.
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init.headers },
    ...init,
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (body: unknown) => JSON.stringify(body);

export interface AuthState {
  required: boolean;
  authenticated: boolean;
  /** Read-only demo session. */
  demo?: boolean;
}

export const api = {
  me: () => request<AuthState>("/api/auth/me"),
  login: (password: string) =>
    request<AuthState>("/api/auth/login", { method: "POST", body: json({ password }) }),
  logout: () => request<AuthState>("/api/auth/logout", { method: "POST" }),

  profiles: () => request<Profile[]>("/api/profiles"),
  createProfile: (body: ProfileIn) =>
    request<Profile>("/api/profiles", { method: "POST", body: json(body) }),
  deleteProfile: (id: number) => request<void>(`/api/profiles/${id}`, { method: "DELETE" }),
  splitProfile: (id: number, anchors: string[], name?: string) =>
    request<Profile>(`/api/profiles/${id}/split`, { method: "POST", body: json({ anchors, name }) }),
  updateProfile: (id: number, body: ProfileIn) =>
    request<Profile>(`/api/profiles/${id}`, { method: "PUT", body: json(body) }),
  startRun: (id: number) => request<Run>(`/api/profiles/${id}/runs`, { method: "POST" }),

  listings: (profileId: number, state: string = "active") =>
    request<Listing[]>(`/api/profiles/${profileId}/listings?state=${state}`),
  listing: (id: number) => request<ListingDetail>(`/api/listings/${id}`),
  setReviewed: (id: number, reviewed: boolean) =>
    request<Listing>(`/api/listings/${id}`, { method: "PATCH", body: json({ reviewed }) }),
  dismiss: (id: number, reason: string) =>
    request<Excluded>(`/api/listings/${id}/dismiss`, { method: "POST", body: json({ reason }) }),

  include: (id: number, reason: string) =>
    request<Listing>(`/api/listings/${id}/include`, { method: "POST", body: json({ reason }) }),
  feedback: (profileId: number) => request<Feedback[]>(`/api/profiles/${profileId}/feedback`),
  deleteFeedback: (id: number) => request<void>(`/api/feedback/${id}`, { method: "DELETE" }),

  excluded: (profileId: number) => request<Excluded[]>(`/api/profiles/${profileId}/excluded`),
  addExcluded: (
    profileId: number,
    body: { address: string; city: string; state: string; reason: string },
  ) =>
    request<Excluded>(`/api/profiles/${profileId}/excluded`, { method: "POST", body: json(body) }),
  restoreExcluded: (id: number) => request<void>(`/api/excluded/${id}`, { method: "DELETE" }),

  runs: (profileId: number) => request<Run[]>(`/api/profiles/${profileId}/runs`),
  run: (id: number) => request<RunDetail>(`/api/runs/${id}`),
  stopRun: (id: number) => request<Run>(`/api/runs/${id}/stop`, { method: "POST" }),
  suggestRegions: (body: SuggestIn) =>
    request<SuggestOut>("/api/wizard/regions", { method: "POST", body: json(body) }),
  emailStatus: () => request<{ configured: boolean; sender: string | null }>("/api/email/status"),
  testEmail: (profileId: number, to: string[]) =>
    request<{ sent_to: string[] }>(`/api/profiles/${profileId}/test-email`, {
      method: "POST",
      body: json({ to }),
    }),
  stats: (profileId: number) => request<Stats>(`/api/profiles/${profileId}/stats`),
};
