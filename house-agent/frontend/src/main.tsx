import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "./lib/api";
import App from "./App";
import "./index.css";

// A 401 anywhere means the session expired: re-check auth so the sign-in screen shows.
const onError = (error: Error) => {
  if (error instanceof ApiError && error.status === 401) {
    queryClient.invalidateQueries({ queryKey: ["auth"] });
  }
};

const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({ onError }),
  mutationCache: new MutationCache({ onError }),
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 15_000,
      retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
