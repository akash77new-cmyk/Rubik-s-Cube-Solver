/** Phase 9: log in, sign up, log out or delete the account, in one small dialog. */

import { useEffect, useState, type FormEvent } from "react";
import { Button, Segmented } from "@/components/ui";
import { AccountError, deleteAccount, logIn, logOut, signUp } from "@/lib/account";
import { useApp } from "@/state/AppStore";

type Mode = "login" | "signup";

export function AccountDialog({ onClose }: { onClose: () => void }) {
  const { account } = useApp();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  /** Run an account call; on success reload, so the socket reconnects as the new identity. */
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      window.location.reload();
    } catch (problem) {
      setError(problem instanceof AccountError ? problem.message : "The server can't be reached.");
      setBusy(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (account?.kind === "user") {
      void run(() => deleteAccount(password));
    } else {
      void run(() => (mode === "login" ? logIn(email, password) : signUp(email, password)));
    }
  };

  const signedIn = account?.kind === "user";

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal account-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Account"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="modal-head">
          <div>
            <h2 style={{ fontSize: 17 }}>{signedIn ? "Your account" : "Log in or sign up"}</h2>
            <p style={{ fontSize: 12.5, color: "var(--ink-3)" }}>
              {signedIn
                ? `Logged in as ${account.email}`
                : "You're a guest: your cube is yours alone, but it's gone when the visit ends."}
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} style={{ marginLeft: "auto" }}>
            Close
          </Button>
        </header>

        <form className="account-body" onSubmit={submit}>
          {signedIn ? (
            <>
              <p className="account-note">
                Your settings and solve history are saved to your account, on every device you log in from.
              </p>
              <Button variant="primary" type="button" loading={busy && !confirmDelete} onClick={() => void run(logOut)}>
                Log out
              </Button>
              {!confirmDelete ? (
                <Button variant="ghost" type="button" onClick={() => setConfirmDelete(true)}>
                  Delete my account…
                </Button>
              ) : (
                <>
                  <p className="account-note">
                    This deletes the account, its settings and its solve history. Enter your password to confirm.
                  </p>
                  <input
                    type="password"
                    autoComplete="current-password"
                    placeholder="Password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    required
                  />
                  <Button variant="danger" type="submit" loading={busy}>
                    Delete account
                  </Button>
                </>
              )}
            </>
          ) : (
            <>
              <Segmented
                value={mode}
                options={[
                  { value: "login", label: "Log in" },
                  { value: "signup", label: "Sign up" },
                ]}
                onChange={(next) => {
                  setMode(next);
                  setError(null);
                }}
              />
              <input
                type="email"
                autoComplete="email"
                placeholder="Email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
              <input
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                placeholder={mode === "login" ? "Password" : "Password (8 characters or more)"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                minLength={mode === "signup" ? 8 : undefined}
                required
              />
              <Button variant="primary" type="submit" loading={busy}>
                {mode === "login" ? "Log in" : "Create account"}
              </Button>
              <p className="account-note">
                With an account, your settings and solve history are saved and follow you to other devices.
              </p>
            </>
          )}
          {error && (
            <p className="account-error" role="alert">
              {error}
            </p>
          )}
        </form>
      </div>
    </div>
  );
}
