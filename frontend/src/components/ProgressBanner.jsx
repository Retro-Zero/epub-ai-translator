/**
 * Unmissable progress banners at the top of the dashboard: translation runs
 * AND QA passes. Both render big animated banners with live % and current
 * item — readable within a second of looking at the screen.
 */
export default function ProgressBanner({ chapters, running, qa }) {
  const total = chapters.length;
  const done = chapters.filter((c) => c.status === 'done').length;
  const failed = chapters.filter((c) => c.status === 'failed').length;
  const skipped = chapters.filter((c) => c.status === 'skipped').length;
  const current = chapters.find((c) => c.status === 'in_progress');
  const finished = done + failed + skipped;
  const pct = total ? Math.round((finished / total) * 100) : 0;

  const active = Boolean(running || current);

  // QA pass in flight — top banner must show it, even if translation is idle
  if (qa?.running) {
    const qaDone = qa.done || 0;
    const qaTotal = qa.total || 0;
    const qaPct = qaTotal ? Math.round((qaDone / qaTotal) * 100) : 0;
    return (
      <div className="progress-banner banner-running">
        <span className="spin" />
        <div className="progress-main">
          <div className="progress-line">
            <strong>
              {qa.current ? `Running QA — ${qa.current}` : 'Running QA…'}
            </strong>
            <span className="muted small">
              {qaDone} of {qaTotal} chapters checked · {qaPct}%
            </span>
          </div>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${qaPct}%` }} />
          </div>
        </div>
      </div>
    );
  }

  if (!active) {
    if (total > 0 && done + skipped === total) {
      return (
        <div className="progress-banner banner-done">
          <span className="badge badge-done">complete</span>
          <span>
            All {total} chapters translated{failed > 0 ? ` — ${failed} failed` : ''}. Run a QA
            pass, then finalize.
          </span>
        </div>
      );
    }
    if (failed > 0) {
      return (
        <div className="progress-banner banner-warn">
          <span className="badge badge-failed">{failed} failed</span>
          <span>
            Translation finished with {failed} failed chapter{failed === 1 ? '' : 's'} — retry
            them inline in the list below.
          </span>
        </div>
      );
    }
    return null;
  }

  return (
    <div className="progress-banner banner-running">
      <span className="spin" />
      <div className="progress-main">
        <div className="progress-line">
          <strong>{current ? `Translating ${current.id}` : 'Translating…'}</strong>
          <span className="muted small">
            {done} done · {failed} failed · {skipped} skipped · {pct}%
          </span>
        </div>
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${pct}%` }} />
        </div>
      </div>
    </div>
  );
}
