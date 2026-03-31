import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';
import { Button } from '@/components/ui';
import { Input } from '@/components/ui';
import { Card } from '@/components/ui';

export default function Setup() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [form, setForm] = useState({
    username: '',
    email: '',
    password: '',
    confirm_password: '',
    platform_name: 'pAWS',
  });

  useEffect(() => {
    api.get('/api/setup/status')
      .then(r => {
        if (r.data.initialized) {
          navigate('/login', { replace: true });
        } else {
          setLoading(false);
        }
      })
      .catch(() => setLoading(false));
  }, [navigate]);

  const handleChange = (field: string) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm(prev => ({ ...prev, [field]: e.target.value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (form.password !== form.confirm_password) {
      setError('Passwords do not match');
      return;
    }

    if (form.username.length < 3) {
      setError('Username must be at least 3 characters');
      return;
    }

    setSubmitting(true);
    try {
      await api.post('/api/setup/init', form);
      setSuccess(true);
      setTimeout(() => navigate('/login'), 2000);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Setup failed. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-paws-bg">
        <p className="text-paws-text-muted">Checking setup status...</p>
      </div>
    );
  }

  if (success) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-paws-bg">
        <Card className="w-full max-w-[480px] text-center">
          <div className="text-4xl mb-4">&#10003;</div>
          <h1 className="text-2xl font-bold text-paws-text mb-2">Setup Complete</h1>
          <p className="text-paws-text-muted">
            Redirecting to login...
          </p>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-paws-bg">
      <Card className="w-full max-w-[480px]">
        <h1 className="mb-2 text-center text-2xl font-bold text-paws-text">
          Welcome to pAWS
        </h1>
        <p className="mb-6 text-center text-paws-text-muted">
          Create your administrator account to get started.
        </p>

        {error && (
          <div className="mb-4 rounded-md bg-red-500/10 border border-red-500/30 px-3 py-2 text-center text-sm text-red-400">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <Input
            label="Platform Name"
            type="text"
            placeholder="pAWS"
            value={form.platform_name}
            onChange={handleChange('platform_name')}
          />

          <div className="border-t border-paws-border-subtle my-1" />

          <Input
            label="Admin Username"
            type="text"
            placeholder="admin"
            value={form.username}
            onChange={handleChange('username')}
            required
          />
          <Input
            label="Admin Email"
            type="email"
            placeholder="admin@example.com"
            value={form.email}
            onChange={handleChange('email')}
            required
          />
          <Input
            label="Password"
            type="password"
            placeholder="Strong password"
            value={form.password}
            onChange={handleChange('password')}
            required
          />
          <Input
            label="Confirm Password"
            type="password"
            placeholder="Confirm password"
            value={form.confirm_password}
            onChange={handleChange('confirm_password')}
            required
          />

          <Button
            type="submit"
            variant="primary"
            size="lg"
            className="w-full mt-2"
            disabled={submitting}
          >
            {submitting ? 'Initializing...' : 'Initialize PAWS'}
          </Button>
        </form>

        <p className="mt-4 text-center text-xs text-paws-text-dim">
          This page is only shown once. After setup, configure clusters and services from the admin panel.
        </p>
      </Card>
    </div>
  );
}
