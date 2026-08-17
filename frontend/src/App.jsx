import { useCallback, useEffect, useState } from 'react';
import { api, get } from './api';
import Dashboard from './components/Dashboard';
import SettingsScreen from './components/SettingsScreen';
import UploadScreen from './components/UploadScreen';

const JOB_KEY = 'epub-ai-translator:job';

// Hash-based navigation: #/upload, #/settings, #/dashboard. The back/forward
// buttons, refresh, and deep links all restore the right screen; ?job=<id>
// still restores a specific job on top of the dashboard route.
const SCREENS = ['upload', 'settings', 'dashboard'];

function screenFromHash() {
  const h = window.location.hash.replace(/^#\/?/, '');
  return SCREENS.includes(h) ? h : null;
}

function toHash(screen) {
  return `#/${screen}`;
}

/**
 * Three-screen app with a persistent nav bar: upload (preview, no job
 * created) -> settings (BYOK) -> dashboard (per-job workspace). The last job
 * id survives in localStorage and ?job=<id> deep-links, so leaving and
 * coming back restores the dashboard instantly. Navigating between pages is
 * always one click away in the top nav — no dead ends.
 */
export default function App() {
  const [screen, setScreen] = useState(() => screenFromHash() || 'upload');
  const [jobId, setJobId] = useState(() => {
    const param = new URLSearchParams(window.location.search).get('job');
    return param || localStorage.getItem(JOB_KEY);
  });
  const [checking, setChecking] = useState(Boolean(jobId));
  const [pendingFile, setPendingFile] = useState(null); // File chosen, not yet committed
  const [msg, setMsg] = useState(null);
  const [settings, setSettings] = useState(null);

  // keep the address bar in sync with the screen; hashchange handles back/forward
  useEffect(() => {
    const wanted = toHash(screen);
    if (window.location.hash !== wanted) window.location.hash = wanted;
  }, [screen]);

  useEffect(() => {
    const onHash = () => {
      const s = screenFromHash();
      if (s) setScreen(s);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    get('/settings')
      .then(setSettings)
      .catch(() => {});
  }, []);

  // validate a restored job id (it may belong to an old server state)
  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;
    api(`/jobs/${jobId}`)
      .then(() => {
        if (cancelled) return;
        localStorage.setItem(JOB_KEY, jobId);
        setChecking(false);
        setScreen('dashboard');
      })
      .catch(() => {
        if (cancelled) return;
        localStorage.removeItem(JOB_KEY);
        setJobId(null);
        setChecking(false);
        setScreen('upload');
        setMsg({ ok: false, text: `job ${jobId} دیگر روی این سیستم وجود ندارد.` });
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const notify = useCallback((text, ok = true) => setMsg({ text, ok }), []);
  const dismiss = () => setMsg(null);

  const go = useCallback((s) => {
    setScreen(s);
    if (s === 'upload') window.scrollTo(0, 0);
  }, []);

  const commitUpload = async () => {
    if (!pendingFile) return;
    try {
      const fd = new FormData();
      fd.append('file', pendingFile);
      const body = await api('/upload', { method: 'POST', body: fd });
      localStorage.setItem(JOB_KEY, body.job_id);
      setJobId(body.job_id);
      setPendingFile(null);
      setScreen('dashboard');
      notify(
        `job ${body.job_id} آماده است — بررسی round-trip ${body.report.pass ? 'موفق' : 'ناموفق'}`
      );
    } catch (e) {
      notify(e.message, false);
    }
  };

  const handleContinue = (file) => {
    setPendingFile(file);
    if (settings?.provider_configured) {
      commitUpload();
    } else {
      notify('کلید provider را اضافه کنید، سپس ذخیره و ادامه دهید');
      setScreen('settings');
    }
  };

  const leaveSettings = () => {
    if (pendingFile) commitUpload();
    else if (jobId) setScreen('dashboard');
    else setScreen('upload');
  };
  const startNew = () => {
    localStorage.removeItem(JOB_KEY);
    setJobId(null);
    setPendingFile(null);
    setMsg(null);
    setScreen('upload');
  };

  const navTab = (id, label, active, onClick, disabled) => (
    <button
      className={`nav-tab${active ? ' active' : ''}`}
      onClick={onClick}
      disabled={disabled}
      aria-current={active ? 'page' : undefined}
    >
      {label}
    </button>
  );

  return (
    <div className="container">
      <div className="topbar">
        <h1>مترجم هوشمند EPUB</h1>
        <nav className="nav" aria-label="pages">
          {navTab('upload', 'کتاب جدید', screen === 'upload', () => go('upload'))}
          {navTab(
            'dashboard',
            'داشبورد',
            screen === 'dashboard',
            () => jobId && go('dashboard'),
            !jobId
          )}
          {navTab('settings', 'تنظیمات', screen === 'settings', () => go('settings'))}
        </nav>
        <span className="spacer" />
        {jobId && <span className="job-chip">job {jobId}</span>}
      </div>

      {msg && (
        <div className={`message ${msg.ok ? 'ok' : 'err'}`}>
          <span>{msg.text}</span>
          <button onClick={dismiss}>بستن</button>
        </div>
      )}

      {checking ? (
        <div className="loading">در حال بازیابی job شما…</div>
      ) : screen === 'dashboard' && !jobId ? (
        <UploadScreen notify={notify} onContinue={handleContinue} />
      ) : screen === 'upload' ? (
        <UploadScreen notify={notify} onContinue={handleContinue} />
      ) : screen === 'settings' ? (
        <SettingsScreen
          notify={notify}
          onSaved={setSettings}
          onContinue={leaveSettings}
        />
      ) : (
        <Dashboard
          key={jobId}
          jobId={jobId}
          notify={notify}
          settings={settings}
          goSettings={() => go('settings')}
          onNewBook={startNew}
        />
      )}
    </div>
  );
}
