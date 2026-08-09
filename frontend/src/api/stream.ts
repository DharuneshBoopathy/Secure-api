import { getStreamTicket } from "@/api/client";

/**
 * Open a server-sent-events stream authenticated by a short-lived ticket.
 *
 * EventSource can't set an Authorization header, so the credential has to sit
 * in the URL — where it reaches every access log on the path. The server
 * therefore accepts only a ~60s, stream-scoped ticket there rather than the
 * caller's access token (see app/security.py::create_stream_ticket).
 *
 * That expiry is shorter than the stream's own lifetime, which is why this
 * takes over reconnection. EventSource's built-in retry replays the original
 * URL, so after the first drop it would loop on an expired ticket forever;
 * instead each attempt mints a fresh one, backing off to 30s so a server
 * outage doesn't turn into a request flood.
 */
export function openTicketedStream(path: string, onMessage: (ev: MessageEvent) => void): () => void {
  let source: EventSource | null = null;
  let retryTimer: number | undefined;
  let attempt = 0;
  let closed = false;

  function scheduleRetry() {
    if (closed) return;
    const delay = Math.min(30_000, 1_000 * 2 ** attempt);
    attempt += 1;
    retryTimer = window.setTimeout(() => void connect(), delay);
  }

  async function connect() {
    if (closed) return;
    let ticket: string;
    try {
      ticket = (await getStreamTicket()).ticket;
    } catch {
      scheduleRetry();
      return;
    }
    // The await above yields, so the consumer may have unmounted meanwhile.
    if (closed) return;

    const src = new EventSource(`${path}?ticket=${encodeURIComponent(ticket)}`);
    source = src;
    src.onopen = () => {
      attempt = 0;
    };
    src.onmessage = onMessage;
    src.onerror = () => {
      src.close();
      if (source === src) source = null;
      scheduleRetry();
    };
  }

  void connect();

  return () => {
    closed = true;
    window.clearTimeout(retryTimer);
    source?.close();
    source = null;
  };
}
