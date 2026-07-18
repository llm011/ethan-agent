
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
    const retryVerify = async (token: string, retries = 3): Promise<boolean> => {
      for (let i = 0; i < retries; i++) {
        try {
          const ok = await verifyAuth(token);
          return ok;
        } catch (err) {
          if (i < retries - 1) await new Promise((r) => setTimeout(r, 2000));
        }
      }
      return false;
    };

    const token = getAuthToken();
    retryVerify(token ?? "").then((ok) => {
      setAuthenticated(ok);
      setLoading(false);
    });
  }, []);

  const login = async (token: string) => {
    try {
      const ok = await verifyAuth(token);
      if (ok) {
        setAuthToken(token);
        setAuthenticated(true);
      }
      return ok;
    } catch {
      return false;
    }
  };

  const logout = () => {
    setAuthToken("");
    setAuthenticated(false);
    if (typeof window !== "undefined") {
      localStorage.removeItem("ethan_token");
      document.cookie = "ethan_token=; max-age=0; path=/";
    }
  };

  return (
    <AuthContext.Provider value={{ authenticated, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
