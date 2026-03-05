import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Button } from '@/components/ui';
import { Input } from '@/components/ui';
import { Card } from '@/components/ui';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const { login, loginWithOAuth } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await login(username, password);
      navigate('/');
    } catch {
      setError('Invalid credentials');
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-paws-bg">
      <Card className="w-full max-w-[400px]">
        <h1 className="mb-6 text-center text-2xl font-bold text-paws-text">pAWS</h1>
        <p className="mb-6 text-center text-paws-text-muted">
          Sign in to manage your infrastructure
        </p>

        {error && (
          <div className="mb-4 text-center text-paws-danger">{error}</div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <Input
            type="text"
            placeholder="Username"
            label="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
          <Input
            type="password"
            placeholder="Password"
            label="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <Button type="submit" variant="primary" size="lg" className="w-full">
            Sign In
          </Button>
        </form>

        <div className="relative my-6 border-t border-paws-border-subtle">
          <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-paws-surface px-2 text-sm text-paws-text-dim">
            or
          </span>
        </div>

        <Button onClick={loginWithOAuth} variant="outline" size="lg" className="w-full">
          Sign in with SSO (Authentik)
        </Button>
      </Card>
    </div>
  );
}
