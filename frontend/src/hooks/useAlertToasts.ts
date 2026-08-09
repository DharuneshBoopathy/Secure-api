import { useEffect } from "react";
import { AUTO_DISMISS_MS } from "@/components/ToastHost";
import { getApiKey } from "@/api/client";
import { openTicketedStream } from "@/api/stream";
import { useAppStore } from "@/store/appStore";

type StreamedAlert = {
  id: number;
  alert_type: string;
  severity: string;
  title: string;
  detail: string;
};

/** Subscribes to GET /api/alerts/stream (see app/routers/alerts.py) for the
 * lifetime of the component that calls this — Layout.tsx calls it once so
 * the subscription (and the toasts it produces) survive page navigation.
 * Authentication goes through a short-lived stream ticket rather than the
 * access token, so nothing long-lived ends up in an access log; see
 * openTicketedStream for the reconnect handling that requires. */
export function useAlertToasts(): void {
  const token = useAppStore((s) => s.accessToken);
  const pushToast = useAppStore((s) => s.pushToast);
  const dismissToast = useAppStore((s) => s.dismissToast);

  useEffect(() => {
    if (!token && !getApiKey()) return;

    return openTicketedStream("/api/alerts/stream", (ev) => {
      let alert: StreamedAlert;
      try {
        alert = JSON.parse(ev.data) as StreamedAlert;
      } catch {
        return; // shouldn't happen for a named "data:" frame, but never let a bad payload crash the app
      }
      const variant: "bad" | "warn" = alert.severity === "high" || alert.severity === "critical" ? "bad" : "warn";
      const toastId = pushToast({
        title: alert.title,
        description: `${alert.alert_type} — ${alert.detail}`.slice(0, 140),
        variant,
        href: "/alerts",
      });
      window.setTimeout(() => dismissToast(toastId), AUTO_DISMISS_MS);
    });
  }, [token, pushToast, dismissToast]);
}
