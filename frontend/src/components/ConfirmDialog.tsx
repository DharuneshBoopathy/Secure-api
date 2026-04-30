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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-4 shadow-xl dark:border-slate-700 dark:bg-slate-900">
        <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{description}</p>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="mt-3 h-24 w-full rounded-lg border border-slate-200 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-950"
          placeholder="Reason"
        />
        <div className="mt-3 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="rounded-md border border-slate-200 px-3 py-1 text-sm">
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-md bg-brand-600 px-3 py-1 text-sm text-white"
            disabled={reason.trim().length < 3}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
