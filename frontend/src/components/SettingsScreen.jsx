import { useEffect, useState } from 'react';
import { get, post, put } from '../api';
import { MODELS } from '../pricing';

const PROVIDER_LABELS = {
  deepseek: 'DeepSeek',
  openai: 'OpenAI',
  gemini: 'Gemini',
  custom: 'Custom endpoint (OpenAI-compatible)',
};

/**
 * Screen 2 — provider / API key settings (BYOK).
 * The key is stored in a local config file on this machine (data/settings.json)
 * and used only by the local server to call the provider — it is never sent
 * anywhere else. The trust note is deliberately prominent.
 */
export default function SettingsScreen({ notify, onSaved, onContinue }) {
  const [form, setForm] = useState({
    provider: 'deepseek',
    base_url: '',
    model: '',
    api_key: '',
    price_in_per_m: '',
    price_out_per_m: '',
    mock_mode: false,
  });
  const [present, setPresent] = useState(false);
  const [masked, setMasked] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    get('/settings')
      .then((s) => {
        setPresent(s.api_key_present);
        setMasked(s.api_key_masked);
        setForm({
          provider: s.provider || 'deepseek',
          base_url: s.base_url || '',
          model: s.model || '',
          api_key: '',
          price_in_per_m: s.price_in_per_m ?? '',
          price_out_per_m: s.price_out_per_m ?? '',
          mock_mode: Boolean(s.mock_mode),
        });
      })
      .catch(() => {});
  }, []);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async (continueAfter) => {
    setSaving(true);
    try {
      const body = {
        provider: form.provider,
        model: form.model.trim(),
        base_url: form.base_url.trim(),
        price_in_per_m: form.price_in_per_m === '' ? null : Number(form.price_in_per_m),
        price_out_per_m: form.price_out_per_m === '' ? null : Number(form.price_out_per_m),
        mock_mode: Boolean(form.mock_mode),
      };
      if (form.api_key.trim()) body.api_key = form.api_key.trim();
      const saved = await put('/settings', body);
      setPresent(saved.api_key_present);
      setMasked(saved.api_key_masked);
      setForm((f) => ({ ...f, api_key: '' }));
      onSaved?.(saved);
      notify('settings saved');
      if (continueAfter) onContinue?.();
    } catch (e) {
      notify(e.message, false);
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await post('/settings/test', {
        base_url: form.base_url.trim() || undefined,
        api_key: form.api_key.trim() || undefined,
        model: form.model.trim() || undefined,
      });
      setTestResult({ ok: true, text: `connected — ${(r.models || []).join(', ')}` });
    } catch (e) {
      setTestResult({ ok: false, text: e.message });
    } finally {
      setTesting(false);
    }
  };

  const clearKey = async () => {
    try {
      const s = await put('/settings', { clear_api_key: true });
      setPresent(false);
      setMasked('');
      onSaved?.(s);
      notify('saved key removed');
    } catch (e) {
      notify(e.message, false);
    }
  };

  const modelList = MODELS[form.provider] || [];
  const isCustom = form.provider === 'custom';

  return (
    <div className="card">
      <h2>Provider settings</h2>
      <p className="card-sub">
        Choose where translations run and which model does the work. Nothing is charged until you
        start a translation.
      </p>

      <div className="trust-note">
        <strong>Your key stays on this device.</strong> It is stored in a local config file on
        this machine and used only to call {PROVIDER_LABELS[form.provider] || 'your provider'}{' '}
        directly from your own server. It is never sent to or stored by any other service.
      </div>

      <label className="checkbox-row" style={{ marginTop: 14 }}>
        <input
          type="checkbox"
          checked={form.mock_mode}
          onChange={(e) => setForm((f) => ({ ...f, mock_mode: e.target.checked }))}
        />
        <span>
          <strong>Mock mode</strong> — test the whole flow with zero API calls
        </span>
      </label>
      <p className="small muted" style={{ marginTop: 2 }}>
        Runs the full pipeline against an in-process fake. No key needed, nothing is charged —
        but the output is test data, clearly marked.
      </p>

      <label>Provider</label>
      <select value={form.provider} onChange={set('provider')}>
        {Object.entries(PROVIDER_LABELS).map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>

      {isCustom && (
        <>
          <label>Base URL</label>
          <input
            type="text"
            value={form.base_url}
            onChange={set('base_url')}
            placeholder="http://127.0.0.1:11434/v1"
          />
        </>
      )}

      <label>Model</label>
      {modelList.length ? (
        <select value={form.model} onChange={set('model')}>
          {!form.model && <option value="">choose a model…</option>}
          {modelList.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          type="text"
          value={form.model}
          onChange={set('model')}
          placeholder="model id, e.g. llama3"
        />
      )}

      <label>API key</label>
      <div className="key-row">
        <input
          type={showKey ? 'text' : 'password'}
          value={form.api_key}
          onChange={set('api_key')}
          placeholder={present ? `${masked} — leave blank to keep` : 'sk-…'}
          autoComplete="off"
        />
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => setShowKey((v) => !v)}
          disabled={!form.api_key}
        >
          {showKey ? 'hide' : 'show'}
        </button>
      </div>
      {present && (
        <button className="btn btn-ghost small" onClick={clearKey}>
          Remove saved key
        </button>
      )}

      <div className="form-row">
        <div>
          <label>Price per 1M input tokens (USD)</label>
          <input
            type="number"
            step="0.01"
            min="0"
            value={form.price_in_per_m}
            onChange={set('price_in_per_m')}
            placeholder="0.28"
          />
        </div>
        <div>
          <label>Price per 1M output tokens (USD)</label>
          <input
            type="number"
            step="0.01"
            min="0"
            value={form.price_out_per_m}
            onChange={set('price_out_per_m')}
            placeholder="1.10"
          />
        </div>
      </div>
      <p className="small muted">
        Used for the dashboard cost estimate. Leave blank to use the built-in table for the
        selected model.
      </p>

      <div className="form-actions">
        <button className="btn btn-primary" onClick={() => save(true)} disabled={saving}>
          {saving ? 'Saving…' : 'Save and continue'}
        </button>
        <button className="btn btn-secondary" onClick={() => save(false)} disabled={saving}>
          Save only
        </button>
        <button className="btn btn-ghost" onClick={test} disabled={testing}>
          {testing ? 'testing…' : 'Test connection'}
        </button>
        {testResult && (
          <span className={`small ${testResult.ok ? '' : 'muted'}`}>{testResult.text}</span>
        )}
      </div>
    </div>
  );
}
