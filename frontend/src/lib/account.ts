/**
 * Accounts (Phase 9): who this browser is, and the calls that change it.
 *
 * The login token is an HttpOnly cookie that JavaScript can't read (so an injected
 * script can't steal it). These calls only send JSON to /api/auth/*; the browser
 * stores and sends the cookie by itself.
 */

export type Account = { kind: "guest" } | { kind: "user"; id: number; email: string };

/** A failed call's message, shown to the user. */
export class AccountError extends Error {}

async function call(path: string, body?: Record<string, unknown>): Promise<Account> {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = (await response.json().catch(() => ({}))) as Partial<Account> & { error?: string };
  if (!response.ok) {
    throw new AccountError(data.error ?? `The server answered ${response.status}.`);
  }
  return data as Account;
}

/** Who this browser is. A browser without a token becomes a new guest. */
export const fetchAccount = () => call("/api/auth/me");
export const signUp = (email: string, password: string) => call("/api/auth/signup", { email, password });
export const logIn = (email: string, password: string) => call("/api/auth/login", { email, password });
export const logOut = () => call("/api/auth/logout", {});
export const deleteAccount = (password: string) => call("/api/auth/delete", { password });
