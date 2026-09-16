const API = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    const detail = typeof error.detail === "string" ? error.detail : response.statusText;
    throw new Error(detail || "Request failed");
  }
  return response.json();
}

export type StreamEvent =
  | { type: "start" }
  | { type: "delta"; content: string }
  | {
      type: "complete";
      referenced_fact_ids: string[];
      certainty: string;
    }
  | { type: "error"; detail: string; status: number };

export async function* streamApi(
  path: string,
  init?: RequestInit,
): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    const detail = typeof error.detail === "string" ? error.detail : response.statusText;
    throw new Error(detail || "Streaming request failed");
  }
  if (!response.body) throw new Error("Streaming response body is unavailable");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.trim()) yield JSON.parse(line) as StreamEvent;
    }

    if (done) break;
  }

  if (buffer.trim()) yield JSON.parse(buffer) as StreamEvent;
}
