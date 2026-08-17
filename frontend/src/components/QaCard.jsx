import { useCallback, useEffect, useRef, useState } from 'react';
import { get, post, put } from '../api';

const ISSUE_LABELS = {
  glossary_violation: 'glossary',
  meaning_drift: 'meaning',
  fluency: 'fluency',
  tone: 'tone',
};

/**
 * Screen 5 — QA review. Running a pass is a background task now: the top
 * banner shows "Running QA — chapter X of N" (via /status.qa), and this card
 * polls the report until the pass lands. Issues grouped by chapter, each with
 * original/current snippets, reason and suggested fix; accept (checkbox),
 * keep original (unchecked) or edit by hand. "Apply fixes and finalize"
 * saves the fixes, rebuilds the final epub, then collapses into a green
 * "N fixes applied · in final.epub" summary behind an expander — the
 * glossary-approved pattern, so applied suggestions stop lingering.
 */
export default function QaCard({ jobId, notify, runSignal, onRefreshStatus, qaRunning, finalExists }) {
  const [report, setReport] = useState(null);
  const [fixes, setFixes] = useState({}); // node_id -> {text, apply}
  const [busy, setBusy] = useState(false);
  const [savedCount, setSavedCount] = useState(0);
  const [finalized, setFinalized] = useState(false);
  const [appliedExpanded, setAppliedExpanded] = useState(false);
  const [opts, setOpts] = useState({ title: true, author: false, publisher: false });
  const pendingRun = useRef(false);

  const loadReport = useCallback(async () => {
    try {
      const body = await get(`/qa/${jobId}`);
      if (body.report && Object.keys(body.report).length) {
        setReport(body.report);
        const saved = Object.keys(body.fixes || {}).length;
        setSavedCount(saved);
        setFinalized(saved > 0 && body.report.errors?.length === 0 ? true : finalized);
      }
    } catch {
      /* server may be mid-run; poller retries */
    }
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  // initial load (also restores applied state after a reload)
  useEffect(() => {
    loadReport();
  }, [loadReport]);

  // while a run is pending, poll until the report lands
  useEffect(() => {
    if (!pendingRun.current) return undefined;
    const t = setInterval(async () => {
      const body = await get(`/qa/${jobId}`).catch(() => null);
      if (body?.report && Object.keys(body.report).length) {
        pendingRun.current = false;
        setBusy(false);
        setReport(body.report);
        const saved = Object.keys(body.fixes || {}).length;
        setSavedCount(saved);
        setFinalized(saved > 0);
        const map = {};
        for (const [ch, info] of Object.entries(body.report.chapters || {})) {
          for (const it of info.issues || []) {
            map[it.id] = { text: it.suggested_fix || '', apply: true, chapter: ch };
          }
        }
        setFixes(map);
        notify(`QA تمام شد — ${body.report.total_issues} مشکل پیدا شد`);
      }
    }, 2000);
    return () => clearInterval(t);
  }, [jobId, notify, pendingRun]);

  // action-bar "Run QA pass" signal
  useEffect(() => {
    if (runSignal > 0) run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runSignal]);

  const run = async () => {
    setBusy(true);
    setAppliedExpanded(false);
    try {
      await post(`/qa/${jobId}`); // 202 — runs in background
      pendingRun.current = true;
      notify('QA شروع شد — پیشرفت در نوار بالا');
    } catch (e) {
      setBusy(false);
      notify(e.message, false);
    }
  };

  const applyAndFinalize = async () => {
    // Build the payload from the REPORT's issues (source of truth), so it
    // works even after a reload when the local `fixes` draft map is empty:
    // the per-issue text falls back to the suggested fix, apply defaults on.
    const out = {};
    for (const [ch, info] of Object.entries(report?.chapters || {})) {
      for (const it of info.issues || []) {
        const draft = fixes[it.id];
        const apply = draft?.apply ?? true;
        const text = (draft?.text ?? it.suggested_fix ?? '').trim();
        if (apply && text) out[it.id] = text;
      }
    }
    setBusy(true);
    try {
      if (Object.keys(out).length) {
        const body = await put(`/qa/${jobId}/fixes`, { fixes: out });
        setSavedCount(body.count);
      }
      const fin = await post(`/finalize/${jobId}`, {
        translate_title: opts.title,
        translate_author: opts.author,
        translate_publisher: opts.publisher,
      });
      setFinalized(true);
      notify(
        `نهایی شد — ${fin.language}، عنوان: ${fin.title || '(بدون تغییر)'}، فونت: ${fin.font}. آماده‌ی دانلود.`
      );
      onRefreshStatus();
    } catch (e) {
      notify(e.message, false);
    } finally {
      setBusy(false);
    }
  };

  const chapters = report?.chapters || {};
  const totalIssues = report?.total_issues || 0;
  const chapterIds = Object.keys(chapters);

  const setFix = (id, patch) => setFixes((m) => ({ ...m, [id]: { ...(m[id] || {}), ...patch } }));

  // --- applied state: green collapsed summary (glossary-approved pattern) ---
  const applied = savedCount > 0;
  const showIssues = report && (totalIssues > 0 || chapterIds.length > 0);

  return (
    <div className="card">
      <h2>بازبینی کیفیت</h2>
      <p className="card-sub">
        بررسی سازگاری روی نمونه‌ای از گره‌های ترجمه‌شده‌ی هر فصل — استفاده از Glossary، انتقال معنا،
        روان بودن. از نوار بالا اجرایش کنید.
      </p>

      {qaRunning && (
        <div className="progress-banner banner-running" style={{ marginBottom: 14 }}>
          <span className="spin" />
          <span>مرحله‌ی QA در پس‌زمینه در حال اجراست — این صفحه به کار خودش ادامه می‌دهد.</span>
        </div>
      )}

      {applied && (
        <div className="card-head" style={{ marginBottom: 10 }}>
          <div>
            <p className="qa-summary" style={{ margin: 0 }}>
              <span className="badge badge-done">{savedCount} اصلاح اعمال شد</span>{' '}
              <span className="muted">· در فایل نهایی EPUB اعمال شده</span>
            </p>
          </div>
          <button className="btn btn-ghost" onClick={() => setAppliedExpanded((v) => !v)}>
            {appliedExpanded ? 'بستن' : 'مشاهده‌ی اصلاحات اعمال‌شده'}
          </button>
        </div>
      )}

      {report && report.errors?.length > 0 && !applied && (
        <p className="small muted">خطای QA در {report.errors.length} فصل — گزارش ناقص است.</p>
      )}

      {showIssues && (!applied || appliedExpanded) && (
        <div className="qa-issues-list">
          {totalIssues === 0 && (
            <p className="qa-summary">
              <span className="badge badge-done">تمیز</span> هیچ مشکلی در نمونه پیدا نشد.
            </p>
          )}

          {totalIssues > 0 && !applied && (
            <p className="qa-summary">
              <strong>
                {totalIssues} مشکل در {chapterIds.length}{' '}
                فصل پیدا شد
              </strong>
            </p>
          )}

          {chapterIds.map((ch) => (
            <div className="qa-group" key={ch}>
              <h3 className="qa-chapter">{ch}</h3>
              {(chapters[ch].issues || []).map((it) => (
                <div className="qa-issue" key={it.id}>
                  <div className="qa-head">
                    <span className="issue-type">{ISSUE_LABELS[it.issue_type] || it.issue_type}</span>
                    <span className="muted small">{it.id}</span>
                    <span className="muted small">— {it.description}</span>
                  </div>
                  <div className="qa-snippets">
                    <div className="qa-snippet">
                      <span className="qa-snippet-label">متن اصلی</span>
                      <span className="muted small">{it.original}</span>
                    </div>
                    <div className="qa-snippet">
                      <span className="qa-snippet-label">ترجمه‌ی فعلی</span>
                      <span dir="rtl" className="small">
                        {it.translation}
                      </span>
                    </div>
                  </div>
                  {applied ? (
                    <p className="small" style={{ color: 'var(--green)', margin: '6px 0 0' }}>
                      ✓ اعمال شد — {fixes[it.id]?.text || 'متن اصلی حفظ شد'}
                    </p>
                  ) : (
                    <div className="qa-fix-row">
                      <input
                        type="text"
                        dir="rtl"
                        value={fixes[it.id]?.text ?? it.suggested_fix ?? ''}
                        onChange={(e) => setFix(it.id, { text: e.target.value })}
                        placeholder="پیشنهاد اصلاح"
                      />
                      <label className="checkbox-row" style={{ margin: 0 }}>
                        <input
                          type="checkbox"
                          checked={fixes[it.id]?.apply ?? true}
                          onChange={(e) => setFix(it.id, { apply: e.target.checked })}
                        />
                        {fixes[it.id]?.apply ?? true ? 'اعمال اصلاح' : 'حفظ متن اصلی'}
                      </label>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {!applied && totalIssues > 0 && (
        <div className="form-actions">
          <button className="btn btn-primary" onClick={applyAndFinalize} disabled={busy}>
            {busy ? 'در حال انجام…' : 'اعمال اصلاحات و نهایی‌سازی'}
          </button>
          <details className="finalize-opts">
            <summary className="small muted">گزینه‌های نهایی‌سازی</summary>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={opts.title}
                onChange={(e) => setOpts((o) => ({ ...o, title: e.target.checked }))}
              />
              ترجمه‌ی عنوان
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={opts.author}
                onChange={(e) => setOpts((o) => ({ ...o, author: e.target.checked }))}
              />
              ترجمه‌ی نام نویسنده
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={opts.publisher}
                onChange={(e) => setOpts((o) => ({ ...o, publisher: e.target.checked }))}
              />
              ترجمه‌ی نام ناشر
            </label>
          </details>
        </div>
      )}

      {(finalized || finalExists) && (
        <div className="download-box">
          <a className="btn btn-primary" href={`/download/${jobId}`} download>
            دانلود EPUB
          </a>
          <span className="small muted">EPUB فارسی نهایی — راست‌به‌چپ، فونت، فهرست ترجمه‌شده</span>
        </div>
      )}

      {!report && !qaRunning && (
        <p className="muted small">
          هنوز گزارش QA وجود ندارد. بعد از ترجمه‌ی حداقل یک فصل، از نوار بالا یک مرحله‌ی QA اجرا کنید.
        </p>
      )}
    </div>
  );
}
