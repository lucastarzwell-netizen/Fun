import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

/** True in a read-only demo session. The server enforces it; this only hides the controls. */
export function useDemo() {
  const { data } = useQuery({ queryKey: ["auth"], queryFn: api.me, staleTime: Infinity });
  return !!data?.demo;
}
