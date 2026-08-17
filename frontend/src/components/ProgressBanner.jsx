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
              {qa.current ? `در حال اجرای QA — ${qa.current}` : 'در حال اجرای QA…'}
            </strong>
            <span className="muted small">
              {qaDone} از {qaTotal} فصل بررسی شد · {qaPct}%
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
          <span className="badge badge-done">کامل</span>
          <span>
            هر {total} فصل ترجمه شد{failed > 0 ? ` — ${failed} ناموفق` : ''}. یک مرحله‌ی QA
            اجرا کنید، بعد نهایی‌سازی.
          </span>
        </div>
      );
    }
    if (failed > 0) {
      return (
        <div className="progress-banner banner-warn">
          <span className="badge badge-failed">{failed} ناموفق</span>
          <span>
            ترجمه با {failed} فصل ناموفق تمام شد — آن‌ها را
            در فهرست پایین دوباره امتحان کنید.
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
          <strong>{current ? `در حال ترجمه‌ی ${current.id}` : 'در حال ترجمه…'}</strong>
          <span className="muted small">
            {done} انجام شد · {failed} ناموفق · {skipped} رد شد · {pct}%
          </span>
        </div>
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${pct}%` }} />
        </div>
      </div>
    </div>
  );
}
