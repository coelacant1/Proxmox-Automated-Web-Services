import { createContext, useContext, useState, useEffect, useRef, useCallback, ReactNode } from 'react';
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
  sessionTimeoutMinutes: number;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [sessionTimeoutMinutes, setSessionTimeoutMinutes] = useState(0);
  const lastActivityRef = useRef(Date.now());
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fetch public settings for session timeout
  useEffect(() => {
    api.get('/api/admin/settings/public')
      .then(r => {
        const val = parseInt(r.data?.session_timeout_minutes || '0', 10);
        if (val > 0) setSessionTimeoutMinutes(val);
      })
      .catch(() => {});
  }, []);

  // Track user activity
  useEffect(() => {
    const onActivity = () => { lastActivityRef.current = Date.now(); };
    window.addEventListener('click', onActivity);
    window.addEventListener('keydown', onActivity);
    window.addEventListener('mousemove', onActivity, { passive: true });
    return () => {
      window.removeEventListener('click', onActivity);
      window.removeEventListener('keydown', onActivity);
      window.removeEventListener('mousemove', onActivity);
    };
  }, []);

  const doLogout = useCallback(() => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    setUser(null);
  }, []);

  // Session timeout checker
  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (!user || sessionTimeoutMinutes <= 0) return;

    timerRef.current = setInterval(() => {
      const idleMs = Date.now() - lastActivityRef.current;
      if (idleMs > sessionTimeoutMinutes * 60 * 1000) {
        doLogout();
        window.location.href = '/login?reason=timeout';
      }
    }, 30000); // check every 30s

    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [user, sessionTimeoutMinutes, doLogout]);

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
    lastActivityRef.current = Date.now();
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

  return (
    <AuthContext.Provider value={{ user, loading, login, loginWithOAuth, logout: doLogout, isAuthenticated: !!user, sessionTimeoutMinutes }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
}
