"use client";

import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { getAuthToken, setAuthToken, verifyAuth } from "@/lib/api";

interface AuthContextType {
  authenticated: boolean;
  loading: boolean;
  login: (token: string) => Promise<boolean>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType>({
  authenticated: false,
  loading: true,
  login: async () => false,
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getAuthToken();
    if (token) {
      verifyAuth(token).then((ok) => {
        setAuthenticated(ok);
        setLoading(false);
      }).catch(() => setLoading(false));
    } else {
      // Try without token (server might not require auth)
      verifyAuth("").then((ok) => {
        setAuthenticated(ok);
        setLoading(false);
      }).catch(() => setLoading(false));
    }
  }, []);

  const login = async (token: string) => {
    const ok = await verifyAuth(token);
    if (ok) {
      setAuthToken(token);
      setAuthenticated(true);
    }
    return ok;
  };

  const logout = () => {
    setAuthToken("");
    setAuthenticated(false);
    if (typeof window !== "undefined") {
      localStorage.removeItem("ethan_token");
    }
  };

  return (
    <AuthContext.Provider value={{ authenticated, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
