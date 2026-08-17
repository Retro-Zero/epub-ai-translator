export async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let body = {};
  try {
    body = await res.json();
  } catch {
    /* non-JSON error body */
  }
  if (!res.ok) {
    const detail =
      typeof body.detail === 'string'
        ? body.detail
        : Array.isArray(body.detail)
          ? body.detail.map((d) => d.msg || String(d)).join('; ')
          : `خطای HTTP ${res.status}`;
    throw new Error(detail);
  }
  return body;
}

export const get = (p) => api(p);

export const post = (p, body) =>
  api(p, {
    method: 'POST',
    ...(body === undefined
      ? {}
      : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  });

export const put = (p, body) =>
  api(p, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

export const patch = (p, body) =>
  api(p, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
