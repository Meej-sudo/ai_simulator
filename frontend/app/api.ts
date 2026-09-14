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
