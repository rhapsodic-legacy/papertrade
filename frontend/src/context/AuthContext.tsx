"use client";

import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { api } from "@/lib/api";

interface User {
  id: string;
  email: string;
  display_name: string;
  cash_balance: number;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, displayName?: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (token) {
      api.setToken(token);
      api
        .getProfile()
        .then((profile) => {
          setUser({
            id: profile.id,
            email: "",
            display_name: profile.display_name,
            cash_balance: profile.cash_balance,
          });
        })
        .catch(() => {
          localStorage.removeItem("access_token");
          api.setToken(null);
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const signIn = async (email: string, password: string) => {
    const resp = await api.signIn(email, password);
    localStorage.setItem("access_token", resp.access_token);
    api.setToken(resp.access_token);
    const profile = await api.getProfile();
    setUser({
      id: resp.user_id,
      email: resp.email,
      display_name: profile.display_name,
      cash_balance: profile.cash_balance,
    });
  };

  const signUp = async (email: string, password: string, displayName?: string) => {
    const resp = await api.signUp(email, password, displayName);
    if (resp.access_token) {
      localStorage.setItem("access_token", resp.access_token);
      api.setToken(resp.access_token);
      const profile = await api.getProfile();
      setUser({
        id: resp.user_id,
        email: resp.email,
        display_name: profile.display_name,
        cash_balance: profile.cash_balance,
      });
    }
  };

  const signOut = () => {
    localStorage.removeItem("access_token");
    api.setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signUp, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
