const LABELS = {
  pending: 'pending',
  in_progress: 'in progress',
  done: 'done',
  failed: 'failed',
  skipped: 'skipped',
};

export default function StatusBadge({ status }) {
  return (
    <span className={`badge badge-${status}`}>
      {status === 'in_progress' && <span className="spin" />}
      {LABELS[status] || status}
    </span>
  );
}
