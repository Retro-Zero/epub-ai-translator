/**
 * Hardcoded per-model pricing (USD per 1M tokens, input/output).
 * Approximate public list prices — refresh periodically. Per-model rates
 * saved in Settings override the table; unknown models fall back to 0
 * (cost shown as "no rate").
 */
export const MODELS = {
  deepseek: [
    { id: 'deepseek-v4-flash', label: 'DeepSeek V4 flash', in: 0.28, out: 1.1 },
    { id: 'deepseek-v4-pro', label: 'DeepSeek V4 pro', in: 2.0, out: 8.0 },
  ],
  openai: [
    { id: 'gpt-4o-mini', label: 'GPT-4o mini', in: 0.15, out: 0.6 },
    { id: 'gpt-4o', label: 'GPT-4o', in: 2.5, out: 10.0 },
    { id: 'gpt-4.1-mini', label: 'GPT-4.1 mini', in: 0.4, out: 1.6 },
    { id: 'gpt-4.1', label: 'GPT-4.1', in: 2.0, out: 8.0 },
  ],
  gemini: [
    { id: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 flash-lite', in: 0.1, out: 0.4 },
    { id: 'gemini-2.5-flash', label: 'Gemini 2.5 flash', in: 0.3, out: 2.5 },
    { id: 'gemini-2.5-pro', label: 'Gemini 2.5 pro', in: 1.25, out: 10.0 },
  ],
  custom: [],
};

/** Rates for a model: settings override wins, then the table. */
export function priceFor(model, settings) {
  const sp = settings || {};
  const hasSettingsRates =
    Number(sp.price_in_per_m) > 0 || Number(sp.price_out_per_m) > 0;
  if (hasSettingsRates) {
    return { in: Number(sp.price_in_per_m) || 0, out: Number(sp.price_out_per_m) || 0, source: 'settings' };
  }
  for (const list of Object.values(MODELS)) {
    const m = list.find((x) => x.id === model);
    if (m) return { in: m.in, out: m.out, source: 'table' };
  }
  return { in: 0, out: 0, source: null };
}

export function estCost(usage = {}, model, settings) {
  const p = priceFor(model, settings);
  return (usage.prompt_tokens || 0) / 1e6 * p.in + (usage.completion_tokens || 0) / 1e6 * p.out;
}

export function fmtTokens(n) {
  return Number(n || 0).toLocaleString();
}

export function fmtUsd(n) {
  if (!Number.isFinite(n) || n === 0) return '$0.0000';
  if (n < 0.01) return `$${n.toFixed(4)}`;
  if (n < 100) return `$${n.toFixed(2)}`;
  return `$${Math.round(n).toLocaleString()}`;
}
