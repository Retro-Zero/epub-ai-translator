import { useEffect, useState } from 'react';
import { patch, post } from '../api';

/**
 * Screen 4 — glossary. Not approved: extract -> review/edit -> bulk approve
 * (blocks Translate remaining until approved). Approved: collapsed summary
 * with a few term previews; expand to see the full approved list (re-approval
 * of later edits is a v2 concern).
 */
export default function GlossaryCard({ jobId, glossary, refresh, notify }) {
  const proposed = glossary?.proposed || [];
  const approved = glossary?.approved || null;
  const [edits, setEdits] = useState({});
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setEdits({});
  }, [JSON.stringify(proposed)]);

  const extract = async () => {
    setBusy(true);
    try {
      const body = await post(`/glossary/${jobId}/extract`);
      notify(`proposed ${body.glossary.length} terms from ${body.chapter_used}`);
      refresh();
    } catch (e) {
      notify(e.message, false);
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    const terms = proposed.map((t, i) => ({
      original: t.original,
      persian: (edits[i] ?? t.persian).trim(),
      category: t.category || 'other',
      note: t.note || 'edited in review',
    }));
    setBusy(true);
    try {
      await patch(`/glossary/${jobId}`, { glossary: terms });
      notify('glossary approved — translate remaining is enabled');
      refresh();
    } catch (e) {
      notify(e.message, false);
    } finally {
      setBusy(false);
    }
  };

  if (approved) {
    const preview = approved.slice(0, 6);
    return (
      <div className="card">
        <div className="card-head">
          <div>
            <h2>Glossary</h2>
            <p className="card-sub">
              <span className="badge badge-done">approved</span> {approved.length} fixed terms
              applied to every translation call
            </p>
          </div>
          <button className="btn btn-ghost" onClick={() => setExpanded((v) => !v)}>
            {expanded ? 'Collapse' : 'View all'}
          </button>
        </div>
        <div className="term-chips">
          {preview.map((t) => (
            <span className="term-chip" key={t.original}>
              <span className="term-en">{t.original}</span>
              <span className="term-fa" dir="rtl">
                {t.persian}
              </span>
            </span>
          ))}
          {approved.length > preview.length && (
            <span className="muted small">+{approved.length - preview.length} more</span>
          )}
        </div>
        {expanded && (
          <div className="glossary-list">
            <table>
              <thead>
                <tr>
                  <th>English</th>
                  <th>Persian</th>
                  <th>Category</th>
                </tr>
              </thead>
              <tbody>
                {approved.map((t) => (
                  <tr key={t.original}>
                    <td>{t.original}</td>
                    <td dir="rtl">{t.persian}</td>
                    <td className="muted small">{t.category}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Glossary</h2>
      <p className="card-sub">
        {proposed.length
          ? `${proposed.length} terms proposed — edit any, then approve to unlock translation.`
          : 'Extract recurring names and terms from the first content chapter, then approve them as fixed translations.'}
      </p>
      {!proposed.length && (
        <button className="btn btn-secondary" onClick={extract} disabled={busy}>
          {busy ? 'Extracting…' : 'Extract glossary'}
        </button>
      )}
      {proposed.length > 0 && (
        <>
          <div className="glossary-list">
            <table>
              <thead>
                <tr>
                  <th>English</th>
                  <th>Persian (editable)</th>
                  <th>Category</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {proposed.map((t, i) => (
                  <tr key={`${t.original}-${i}`}>
                    <td>{t.original}</td>
                    <td>
                      <input
                        type="text"
                        dir="rtl"
                        value={edits[i] ?? t.persian}
                        onChange={(e) => setEdits((m) => ({ ...m, [i]: e.target.value }))}
                      />
                    </td>
                    <td className="muted small">{t.category}</td>
                    <td className="muted small">{t.note || ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="form-actions">
            <button className="btn btn-secondary" onClick={approve} disabled={busy}>
              {busy ? 'Approving…' : 'Approve glossary'}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
