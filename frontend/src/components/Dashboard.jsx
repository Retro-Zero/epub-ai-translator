import { useEffect, useMemo, useState } from 'react';
import { post } from '../api';
import { useJobMeta, usePolling } from '../hooks';
import { estCost, fmtTokens, fmtUsd, priceFor } from '../pricing';
import ChapterList from './ChapterList';
import GlossaryCard from './GlossaryCard';
import ProgressBanner from './ProgressBanner';
import QaCard from './QaCard';

const DONE = 'done';
const FAILED = 'failed';

/**
 * Screen 3 — dashboard (per-job). Header (filename, provider/model badge),
 * stats row (chapters, translated, tokens, client-side cost estimate),
 * glossary summary, chapter list with the three-button action bar, QA review.
 * State renders instantly on load and polls every 3s while any chapter is
 * in progress; polling stops when everything is done or failed.
 */
export default function Dashboard({ jobId, notify, settings, goSettings, onNewBook }) {
  const { status, error, refresh } = usePolling(jobId, 3000);
  const { meta } = useJobMeta(jobId);
  const [runQaSignal, setRunQaSignal] = useState(0);
  const [starting, setStarting] = useState(false);

  const chapters = status?.chapters || [];
  const running = Boolean(status?.running);
  const qaRunning = Boolean(status?.qa?.running);
  const qa = status?.qa || { running: false, done: 0, total: 0 };
  const title = status?.title || meta?.title || 'Book';
  const model = settings?.model || '';
  const provider = settings?.provider || '';

  const counts = useMemo(() => {
    const byId = {};
    for (const c of meta?.chapters || []) byId[c.id] = c;
    return byId;
  }, [meta]);

  const doneCount = chapters.filter((c) => c.status === DONE).length;
  const failedCount = chapters.filter((c) => c.status === FAILED).length;
  const pendingCount = chapters.filter((c) => ['pending', 'in_progress'].includes(c.status)).length;
  const translated = doneCount > 0;
  const complete = chapters.length > 0 && doneCount === chapters.length;
  const approved = Boolean(status?.glossary?.approved);

  // tokens + cost
  const usage = status?.usage || {};
  const tokensUsed = (usage.prompt_tokens || 0) + (usage.completion_tokens || 0);
  const cost = estCost(usage, model, settings);
  const rate = priceFor(model, settings);

  // remaining-token estimate: avg tokens per translated node x remaining nodes
  const remainingEstimate = useMemo(() => {
    const nodesById = {};
    for (const c of meta?.chapters || []) nodesById[c.id] = c.text_nodes || 0;
    let translatedNodes = 0;
    let remainingNodes = 0;
    for (const c of chapters) {
      if (c.status === DONE) translatedNodes += nodesById[c.id] || 0;
      else if (c.status === 'pending' || c.status === FAILED) remainingNodes += nodesById[c.id] || 0;
    }
    if (!translatedNodes || !remainingNodes) return null;
    const perNode = tokensUsed / translatedNodes;
    return Math.round(perNode * remainingNodes);
  }, [chapters, meta, tokensUsed]);

  const translateRemaining = async () => {
    setStarting(true);
    try {
      await post(`/translate/${jobId}/all`);
      notify('ترجمه شروع شد — وضعیت به‌صورت زنده به‌روز می‌شود');
      refresh();
    } catch (e) {
      notify(e.message, false);
    } finally {
      setStarting(false);
    }
  };

  // live tab title while translating OR running QA — visible even backgrounded
  useEffect(() => {
    if (qaRunning) {
      document.title = `QA — ${qa.current || '…'} (${qa.done}/${qa.total}) · مترجم هوشمند EPUB`;
      return;
    }
    const current = chapters.find((c) => c.status === 'in_progress');
    if (running || current) {
      const d = chapters.filter((c) => c.status === 'done').length;
      document.title = `در حال ترجمه ${current?.id || '…'} — ${d}/${chapters.length} · مترجم هوشمند EPUB`;
    } else {
      document.title = 'مترجم هوشمند EPUB';
    }
  }, [running, qaRunning, qa, chapters]);

  const runQa = () => setRunQaSignal((n) => n + 1);

  const actionBar = (
    <div className="action-bar">
      <button
        className="btn btn-primary"
        onClick={translateRemaining}
        disabled={running || starting || !approved || pendingCount === 0}
        title={!approved ? 'اول Glossary را تأیید کنید' : undefined}
      >
        {running ? 'در حال ترجمه…' : pendingCount === 0 ? 'همه‌ی فصل‌ها ترجمه شدند' : 'ترجمه‌ی باقی‌مانده'}
      </button>
      <button className="btn btn-secondary" onClick={runQa} disabled={running || qaRunning || !translated}>
        {qaRunning ? 'QA در حال اجرا…' : 'اجرای مرحله‌ی QA'}
      </button>
      {translated && (
        <a
          className={`btn ${complete ? 'btn-primary' : 'btn-secondary'}`}
          href={`/download/${jobId}`}
          download
        >
          {complete ? 'دانلود EPUB' : 'دانلود EPUB (ناقص)'}
        </a>
      )}
    </div>
  );

  return (
    <div>
      <div className="topbar" style={{ marginTop: 0 }}>
        <div>
          <h2 style={{ fontSize: 19, fontWeight: 650, margin: 0 }}>{title}</h2>
          <span className="job-chip">
            {provider} · {model || 'no model'}
          </span>
        </div>
        <span className="spacer" />
        <button className="btn btn-ghost" onClick={goSettings}>
          تنظیمات
        </button>
        <button className="btn btn-ghost" onClick={onNewBook}>
          کتاب جدید
        </button>
      </div>

      {error && <div className="warn">به‌روزرسانی وضعیت ناموفق بود ({error}) — تلاش دوباره به‌صورت خودکار.</div>}
      {status?.mock_mode && (
        <div className="progress-banner banner-running">
          <span className="spin" />
          <span>
            <strong>حالت آزمایشی روشن است</strong> — هیچ تماس API واقعی انجام نمی‌شود؛ همه‌ی خروجی‌ها داده‌ی تست
            (با علامت 【آزمایشی】). برای ترجمه‌ی واقعی در تنظیمات خاموشش کنید.
          </span>
        </div>
      )}
      {status && !status.provider_configured && (
        <div className="warn">
          کلید provider تنظیم نشده — قبل از ترجمه، تنظیمات را باز کنید و کلید را ذخیره کنید.
        </div>
      )}

      <ProgressBanner chapters={chapters} running={running} qa={qa} />

      <div className="stats-row">
        <div className="stat">
          <span className="stat-value">{chapters.length || '—'}</span>
          <span className="stat-label">فصل‌ها</span>
        </div>
        <div className="stat">
          <span className="stat-value">
            {doneCount}
            {failedCount > 0 && <span className="stat-sub"> +{failedCount} ناموفق</span>}
          </span>
          <span className="stat-label">ترجمه‌شده</span>
        </div>
        <div className="stat">
          <span className="stat-value">{fmtTokens(tokensUsed)}</span>
          <span className="stat-label">توکن مصرف‌شده</span>
          {remainingEstimate && <span className="stat-sub">حدود {fmtTokens(remainingEstimate)} باقی‌مانده</span>}
        </div>
        <div className="stat">
          <span className="stat-value">{fmtUsd(cost)}</span>
          <span className="stat-label">
            هزینه‌ی تخمینی{rate.source === 'settings' ? ' (نرخ‌های شما)' : rate.source === 'table' ? '' : ' — نرخ‌ها را در تنظیمات تعیین کنید'}
          </span>
        </div>
      </div>

      {status ? (
        <>
          <GlossaryCard jobId={jobId} glossary={status.glossary} refresh={refresh} notify={notify} />
          <ChapterList
            jobId={jobId}
            chapters={chapters}
            counts={counts}
            running={running}
            refresh={refresh}
            notify={notify}
            action={actionBar}
          />
          <QaCard
            jobId={jobId}
            notify={notify}
            runSignal={runQaSignal}
            onRefreshStatus={refresh}
            qaRunning={qaRunning}
            finalExists={Boolean(status?.final_epub)}
          />
        </>
      ) : (
        <div className="loading">در حال بارگذاری وضعیت job…</div>
      )}
    </div>
  );
}
