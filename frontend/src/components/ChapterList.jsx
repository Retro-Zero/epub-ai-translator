import { useState } from 'react';
import { post } from '../api';
import StatusBadge from './StatusBadge';

/**
 * Chapter list: title + status badge per chapter, inline retry on failed
 * rows (failures never block the book). `action` hosts the dashboard's
 * action bar above the table.
 */
export default function ChapterList({ jobId, chapters, counts, running, refresh, notify, action }) {
  const [busyId, setBusyId] = useState(null);
  const failedCount = chapters.filter((c) => c.status === 'failed').length;
  const doneCount = chapters.filter((c) => c.status === 'done').length;

  const retry = async (id) => {
    setBusyId(id);
    try {
      const body = await post(`/translate/${jobId}/chapter/${id}`);
      notify(
        `${id}: ${body.report.nodes} گره ترجمه شد (${body.report.usage?.calls || 0} تماس)`
      );
      refresh();
    } catch (e) {
      notify(e.message, false);
      refresh();
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="card">
      <h2>فصل‌ها</h2>
      <p className="card-sub">
        {doneCount} از {chapters.length} ترجمه شد
        {failedCount > 0 && (
          <>
            {' '}
            — <span className="badge badge-failed">{failedCount} ناموفق</span> آن‌ها را جداگانه دوباره
            امتحان کنید؛ بقیه‌ی کتاب بی‌تأثیر می‌ماند
          </>
        )}
      </p>
      {action}
      <table>
        <thead>
          <tr>
            <th>فصل</th>
            <th>گره‌ها</th>
            <th>وضعیت</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {chapters.map((c) => {
            const info = counts[c.id] || {};
            return (
              <tr key={c.id}>
                <td>
                  {info.title ? (
                    <>
                      <span className="chapter-title">{info.title}</span>
                      <span className="muted small"> {c.id}</span>
                    </>
                  ) : (
                    <span className="muted">{c.id}</span>
                  )}
                </td>
                <td className="num">{info.text_nodes ?? '—'}</td>
                <td>
                  <StatusBadge status={c.status} />
                </td>
                <td style={{ textAlign: 'right' }}>
                  {c.status === 'failed' && !running && (
                    <button
                      className="btn btn-secondary"
                      onClick={() => retry(c.id)}
                      disabled={busyId === c.id}
                    >
                      {busyId === c.id ? 'در حال ترجمه…' : 'تلاش دوباره'}
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
