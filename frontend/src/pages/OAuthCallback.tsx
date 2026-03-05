import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import api from '../api/client';

export default function OAuthCallback() {
  const [searchParams] = useSearchParams();
  const [error, setError] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    const code = searchParams.get('code');
    if (!code) {
      setError('No authorization code received');
      return;
    }

    const redirectUri = `${window.location.origin}/oauth/callback`;
    api.get(`/api/auth/oauth/callback?code=${code}&redirect_uri=${encodeURIComponent(redirectUri)}`)
      .then((res) => {
        localStorage.setItem('access_token', res.data.access_token);
        localStorage.setItem('refresh_token', res.data.refresh_token);
        navigate('/');
      })
      .catch(() => setError('OAuth authentication failed'));
  }, [searchParams, navigate]);

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-paws-danger">{error}</div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen">
      <p className="text-paws-text-muted">Completing sign in...</p>
    </div>
  );
}
