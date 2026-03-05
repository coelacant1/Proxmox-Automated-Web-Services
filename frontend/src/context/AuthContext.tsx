import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import api from '../api/client';

interface User {
  id: string;
  email: string;
  username: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  auth_provider: string;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  loginWithOAuth: () => void;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (token) {
      api.get('/api/auth/me')
        .then((res) => setUser(res.data))
        .catch(() => {
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const login = async (username: string, password: string) => {
    const res = await api.post('/api/auth/login', { username, password });
    localStorage.setItem('access_token', res.data.access_token);
    localStorage.setItem('refresh_token', res.data.refresh_token);
    const me = await api.get('/api/auth/me');
    setUser(me.data);
  };

  const loginWithOAuth = () => {
    const redirectUri = `${window.location.origin}/oauth/callback`;
    api.get(`/api/auth/oauth/login?redirect_uri=${encodeURIComponent(redirectUri)}`)
      .then((res) => {
        window.location.href = res.data.authorization_url;
      });
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, loginWithOAuth, logout, isAuthenticated: !!user }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
}
