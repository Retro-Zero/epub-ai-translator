import { useEffect, useState } from 'react';
import { get, post, put } from '../api';

const ISSUE_LABELS = {
  glossary_violation: 'glossary',
  meaning_drift: 'meaning',
  fluency: 'fluency',
  tone: 'tone',
};

/**
 * Screen 5 — QA review. Issues grouped by chapter, each with the original
 * snippet, current translation, flagged reason and suggested fix. Per issue:
 * accept the suggested fix (checkbox), keep the original (unchecked), or
 * edit by hand. "Apply fixes and finalize" saves the fixes and triggers the
 * final epub rebuild.
 */
export default function QaCard({ jobId, notify, runSignal, onRefreshStatus }) {
  const [report, setReport] = useState(null);
  const [fixes, setFixes] = useState({}); // node_id -> {text, apply}
  const [busy, setBusy] = useState(false);
  const [savedCount, setSavedCount] = useState(0);
  const [finalized, setFinalized] = useState(false);
  const [opts, setOpts] = useState({ title: true, author: false, publisher: false });

  useEffect(() => {
    get(`/qa/${jobId}`)
      .then((body) => {
        if (body.report && Object.keys(body.report).length) setReport(body.report);
      })
      .catch(() => {});
  }, [jobId]);

  // action-bar "Run QA pass" signal
  useEffect(() => {
    if (runSignal > 0) run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runSignal]);

  const run = async () => {
    setBusy(true);
    try {
      const body = await post(`/qa/${jobId}`);
      setReport(body);
      setSavedCount(0);
      setFinalized(false);
      const map = {};
      for (const [ch, info] of Object.entries(body.chapters || {})) {
        for (const it of info.issues || []) {
          map[it.id] = { text: it.suggested_fix || '', apply: true, chapter: ch };
        }
      }
      setFixes(map);
      notify(`QA done — ${body.total_issues} issue(s) flagged`);
    } catch (e) {
      notify(e.message, false);
    } finally {
      setBusy(false);
    }
  };

  const applyAndFinalize = async () => {
    const out = {};
    for (const [id, f] of Object.entries(fixes)) {
      if (f.apply && f.text.trim()) out[id] = f.text.trim();
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
        `finalized — ${fin.language}, title: ${fin.title || '(kept)'}, font: ${fin.font}. Ready to download.`
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

  return (
    <div className="card">
      <h2>Quality review</h2>
      <p className="card-sub">
        A consistency check on a sample of translated nodes per chapter — glossary use, meaning,
        fluency. Run it from the action bar above.
      </p>

      {report && report.errors?.length > 0 && (
        <p className="small muted">QA errors on {report.errors.length} chapter(s) — report is partial.</p>
      )}

      {report && totalIssues === 0 && (
        <p className="qa-summary">
          <span className="badge badge-done">clean</span> no issues flagged in the sample.
        </p>
      )}

      {report && totalIssues > 0 && (
        <>
          <p className="qa-summary">
            <strong>
              {totalIssues} issue{totalIssues === 1 ? '' : 's'} found across {chapterIds.length}{' '}
              chapter{chapterIds.length === 1 ? '' : 's'}
            </strong>
            {savedCount > 0 && <span className="muted"> — {savedCount} fix(es) saved</span>}
          </p>

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
                      <span className="qa-snippet-label">original</span>
                      <span className="muted small">{it.original}</span>
                    </div>
                    <div className="qa-snippet">
                      <span className="qa-snippet-label">current</span>
                      <span dir="rtl" className="small">
                        {it.translation}
                      </span>
                    </div>
                  </div>
                  <div className="qa-fix-row">
                    <input
                      type="text"
                      dir="rtl"
                      value={fixes[it.id]?.text ?? it.suggested_fix ?? ''}
                      onChange={(e) => setFix(it.id, { text: e.target.value })}
                      placeholder="suggested fix"
                    />
                    <label className="checkbox-row" style={{ margin: 0 }}>
                      <input
                        type="checkbox"
                        checked={fixes[it.id]?.apply ?? true}
                        onChange={(e) => setFix(it.id, { apply: e.target.checked })}
                      />
                      {fixes[it.id]?.apply ?? true ? 'apply fix' : 'keep original'}
                    </label>
                  </div>
                </div>
              ))}
            </div>
          ))}

          <div className="form-actions">
            <button className="btn btn-primary" onClick={applyAndFinalize} disabled={busy}>
              {busy ? 'Working…' : 'Apply fixes and finalize'}
            </button>
            <details className="finalize-opts">
              <summary className="small muted">finalize options</summary>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={opts.title}
                  onChange={(e) => setOpts((o) => ({ ...o, title: e.target.checked }))}
                />
                Translate the title
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={opts.author}
                  onChange={(e) => setOpts((o) => ({ ...o, author: e.target.checked }))}
                />
                Translate the author name
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={opts.publisher}
                  onChange={(e) => setOpts((o) => ({ ...o, publisher: e.target.checked }))}
                />
                Translate the publisher name
              </label>
            </details>
          </div>
          {finalized && (
            <div className="download-box">
              <a className="btn btn-primary" href={`/download/${jobId}`} download>
                Download epub
              </a>
              <span className="small muted">final Persian epub — RTL, font, translated TOC</span>
            </div>
          )}
        </>
      )}

      {!report && (
        <p className="muted small">
          No QA report yet. Once at least one chapter is translated, run a QA pass from the action
          bar.
        </p>
      )}
    </div>
  );
}
