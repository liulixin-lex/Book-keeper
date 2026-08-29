import React, { createContext, useContext, useState, useEffect } from "react";
import { User, AuthResponse } from "../types/api";
import { apiRequest, setCsrfToken } from "../api/client";

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  login: (payload: { identifier: string; password: string }) => Promise<void>;
  bootstrap: (payload: {
    username: string;
    email: string;
    password: string;
    workspace_name: string;
  }) => Promise<void>;
  register: (payload: {
    username: string;
    email: string;
    password: string;
    token: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const refreshUser = async () => {
    try {
      const currentUser = await apiRequest<User>("/auth/me");
      setUser(currentUser);
    } catch {
      setUser(null);
      setCsrfToken(null);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    refreshUser();
  }, []);

  const login: AuthContextType["login"] = async (payload) => {
    const res = await apiRequest<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setCsrfToken(res.csrf_token);
    setUser(res.user);
  };

  const bootstrap: AuthContextType["bootstrap"] = async (payload) => {
    const res = await apiRequest<AuthResponse>("/auth/bootstrap", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setCsrfToken(res.csrf_token);
    setUser(res.user);
  };

  const register: AuthContextType["register"] = async (payload) => {
    const res = await apiRequest<AuthResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setCsrfToken(res.csrf_token);
    setUser(res.user);
  };

  const logout = async () => {
    try {
      await apiRequest("/auth/logout", { method: "POST" });
    } finally {
      setUser(null);
      setCsrfToken(null);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        login,
        bootstrap,
        register,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
