import { useCallback, useEffect, useState } from 'react';
import { api } from './api';

/**
 * Poll /jobs/{id}/status every `interval` ms while the job is active
 * (running flag or any in_progress chapter). Stops polling when idle.
 * Always returns the latest status; `refresh()` forces an immediate fetch
 * after a mutation.
 */
export function usePolling(jobId, interval = 2000) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!jobId) return;
    try {
      setStatus(await api(`/jobs/${jobId}/status`));
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const active =
    !status || status.running || (status.chapters || []).some((c) => c.status === 'in_progress');

  useEffect(() => {
    if (!active) return undefined;
    const t = setInterval(refresh, interval);
    return () => clearInterval(t);
  }, [active, interval, refresh]);

  return { status, error, loading, refresh };
}

/** Fetch /jobs/{id} once — title + per-chapter node counts. */
export function useJobMeta(jobId) {
  const [meta, setMeta] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let cancelled = false;
    if (!jobId) return undefined;
    api(`/jobs/${jobId}`)
      .then((m) => !cancelled && setMeta(m))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [jobId]);
  return { meta, error };
}
