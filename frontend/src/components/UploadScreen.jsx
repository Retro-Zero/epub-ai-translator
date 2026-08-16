import { useRef, useState } from 'react';
import { api } from '../api';

/**
 * Screen 1 — upload / new job.
 * Drop zone or file picker (.epub only). Preview parses the file on the
 * server WITHOUT creating a job and shows filename / size / chapter count /
 * title before anything is committed. No AI calls on this screen.
 * Continue routes to settings when no provider is configured yet, else
 * commits the upload and goes to the dashboard.
 */
export default function UploadScreen({ notify, providerConfigured, onContinue }) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null);
  const [dragOver, setDragOver] = useState(false);

  const file = inputRef.current?.files?.[0] || null;

  const setFile = (f) => {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith('.epub')) {
      notify('only .epub files are accepted', false);
      return;
    }
    setPreview(null);
    if (inputRef.current) inputRef.current.value = ''; // reset so re-picking same file fires change
    const dt = new DataTransfer();
    dt.items.add(f);
    inputRef.current.files = dt.files;
    runPreview(f);
  };

  const runPreview = async (f) => {
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('file', f);
      const body = await api('/preview', { method: 'POST', body: fd });
      setPreview({ ...body, filename: f.name });
      notify(`preview ready — ${body.chapter_count} chapters, no job created yet`);
    } catch (e) {
      setPreview(null);
      notify(e.message, false);
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer?.files?.[0];
    if (f) setFile(f);
  };

  const loadSample = async () => {
    setBusy(true);
    try {
      const res = await fetch('/sample');
      if (!res.ok) throw new Error('sample book unavailable');
      const blob = await res.blob();
      setFile(new File([blob], 'sample-book.epub', { type: 'application/epub+zip' }));
    } catch (e) {
      notify(e.message, false);
    } finally {
      setBusy(false);
    }
  };

  const fmtSize = (n) => {
    if (n > 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
    return `${Math.max(1, Math.round(n / 1024))} KB`;
  };

  return (
    <div className="card">
      <h2>Upload a book</h2>
      <p className="card-sub">
        English epub in, Persian epub out — processed on this machine only.
      </p>

      <div
        className={`dropzone${dragOver ? ' drag' : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        <input
          type="file"
          accept=".epub"
          className="hidden-input"
          ref={inputRef}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) setFile(f);
          }}
        />
        <p className="dropzone-main">{busy ? 'Reading the epub…' : 'Drop an epub here or click to choose'}</p>
        <p className="muted small">.epub only — nothing is created until you continue</p>
      </div>

      <div className="form-actions">
        <button className="btn btn-ghost" onClick={loadSample} disabled={busy}>
          or try the sample book
        </button>
      </div>

      {preview && (
        <div className="preview-box">
          <table>
            <tbody>
              <tr>
                <td className="muted">File</td>
                <td>{preview.filename}</td>
              </tr>
              <tr>
                <td className="muted">Size</td>
                <td>{fmtSize(preview.size)}</td>
              </tr>
              <tr>
                <td className="muted">Title</td>
                <td>{preview.title || '—'}</td>
              </tr>
              <tr>
                <td className="muted">Chapters</td>
                <td>
                  {preview.chapter_count}
                  <span className="muted small">
                    {' '}
                    (≈ {preview.chapters.reduce((a, c) => a + c.text_nodes, 0)} text nodes)
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
          <div className="form-actions">
            <button
              className="btn btn-primary"
              onClick={() => onContinue(file)}
              disabled={busy || !file}
            >
              Continue
            </button>
            <button className="btn btn-ghost" onClick={() => setPreview(null)}>
              Choose a different file
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
