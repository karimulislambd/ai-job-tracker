"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, refreshSession, setAccessToken, setSessionExpiredHandler } from "./api";
import type { TokenResponse, User } from "./types";

type Status = "loading" | "authenticated" | "anonymous";

interface AuthContextValue {
  user: User | null;
  status: Status;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName?: string) => Promise<void>;
  startDemo: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<Status>("loading");

  const accept = useCallback((data: TokenResponse) => {
    setAccessToken(data.access_token);
    setUser(data.user);
    setStatus("authenticated");
  }, []);

  // Restore the session from the httpOnly refresh cookie on first load.
  useEffect(() => {
    let cancelled = false;
    refreshSession().then((data) => {
      if (cancelled) return;
      if (data) accept(data);
      else setStatus("anonymous");
    });
    return () => {
      cancelled = true;
    };
  }, [accept]);

  useEffect(() => {
    setSessionExpiredHandler(() => {
      setAccessToken(null);
      setUser(null);
      setStatus("anonymous");
      router.replace("/login?expired=1");
    });
    return () => setSessionExpiredHandler(null);
  }, [router]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      status,
      login: async (email, password) => accept(await api.auth.login(email, password)),
      register: async (email, password, fullName) =>
        accept(await api.auth.register(email, password, fullName)),
      startDemo: async () => accept(await api.auth.demo()),
      logout: async () => {
        try {
          await api.auth.logout();
        } finally {
          setAccessToken(null);
          // Hard navigation: drops every bit of in-memory state, and avoids the
          // protected layout redirecting to /login mid-transition.
          window.location.replace("/");
        }
      },
    }),
    [user, status, accept],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
