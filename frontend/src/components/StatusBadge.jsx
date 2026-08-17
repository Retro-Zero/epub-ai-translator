const LABELS = {
  pending: 'در انتظار',
  in_progress: 'در حال اجرا',
  done: 'انجام شد',
  failed: 'ناموفق',
  skipped: 'رد شد',
};

export default function StatusBadge({ status }) {
  return (
    <span className={`badge badge-${status}`}>
      {status === 'in_progress' && <span className="spin" />}
      {LABELS[status] || status}
    </span>
  );
}
