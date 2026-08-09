type Props = {
  open: boolean;
  title: string;
  description: string;
  reason: string;
  setReason: (value: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
  confirmLabel?: string;
};

export function ConfirmDialog({
  open,
  title,
  description,
  reason,
  setReason,
  onCancel,
  onConfirm,
  confirmLabel = "Confirm",
}: Props) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/40 p-4 backdrop-blur-sm">
      <div className="glass-strong w-full max-w-md rounded-3xl p-6 animate-fade-rise">
        <h3 className="font-display text-xl text-ink-900 dark:text-ink-50">{title}</h3>
        <p className="mt-1.5 text-sm text-ink-600 dark:text-ink-300">{description}</p>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="field mt-4 h-24 resize-none"
          placeholder="Reason"
        />
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-full px-4 py-2 text-sm font-medium text-ink-700 transition hover:bg-ink-900/[0.06] dark:text-ink-300 dark:hover:bg-white/[0.08]"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-full bg-accent-500 px-4 py-2 text-sm font-medium text-white ring-1 ring-inset ring-white/20 transition hover:bg-accent-600 disabled:pointer-events-none disabled:opacity-40"
            disabled={reason.trim().length < 3}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
