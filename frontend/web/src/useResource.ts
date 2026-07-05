import { useCallback, useEffect, useState } from "react";

import { fetchResource, postAction } from "./api";
import type { ResourceArea } from "./types";

export function useResource<T extends object>(area: ResourceArea) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);

  const refresh = useCallback(() => setGeneration((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchResource<T>(area, controller.signal)
      .then((snapshot) => setData(snapshot.data))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : `Could not load ${area}`);
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [area, generation]);

  const action = useCallback(async (name: string, payload: Record<string, unknown>) => {
    setNotice(null);
    setError(null);
    setPendingAction(name);
    try {
      const result = await postAction(name, payload);
      setNotice(result.message);
      refresh();
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The action could not be completed");
      return false;
    } finally {
      setPendingAction(null);
    }
  }, [refresh]);

  return { data, loading, error, notice, pendingAction, refresh, action };
}
