import { useEffect, useState } from 'react';
import { Shield, Smartphone, CheckCircle, XCircle } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  Input, Badge,
} from '@/components/ui';

interface MFAStatus {
  enabled: boolean;
  method: string | null;
  verified: boolean;
}

export default function MFASettings() {
  const [status, setStatus] = useState<MFAStatus>({ enabled: false, method: null, verified: false });
  const [loading, setLoading] = useState(true);
  const [setupData, setSetupData] = useState<{ secret: string; qr_uri: string } | null>(null);
  const [verifyCode, setVerifyCode] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    api.get('/api/auth/mfa/status')
      .then((res) => setStatus(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleEnable = async () => {
    setError('');
    try {
      const res = await api.post('/api/auth/mfa/enable', { method: 'totp' });
      setSetupData(res.data);
    } catch {
      setError('Failed to initiate MFA setup.');
    }
  };

  const handleVerify = async () => {
    setError('');
    try {
      await api.post('/api/auth/mfa/verify', { code: verifyCode });
      setStatus({ enabled: true, method: 'totp', verified: true });
      setSetupData(null);
      setVerifyCode('');
    } catch {
      setError('Invalid code. Please try again.');
    }
  };

  const handleDisable = async () => {
    if (!confirm('Disable MFA? This reduces account security.')) return;
    try {
      await api.post('/api/auth/mfa/disable');
      setStatus({ enabled: false, method: null, verified: false });
    } catch {
      setError('Failed to disable MFA.');
    }
  };

  if (loading) return <p className="text-paws-text-muted p-8">Loading...</p>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-paws-text">Multi-Factor Authentication</h1>
        <p className="text-sm text-paws-text-muted mt-1">Secure your account with an additional verification step.</p>
      </div>

      <div className="max-w-lg space-y-6">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Shield className="h-5 w-5" /> MFA Status
              </CardTitle>
              {status.enabled ? (
                <Badge variant="success">
                  <CheckCircle className="h-3 w-3 mr-1" /> Enabled
                </Badge>
              ) : (
                <Badge variant="danger">
                  <XCircle className="h-3 w-3 mr-1" /> Disabled
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {status.enabled ? (
              <div className="space-y-4">
                <p className="text-sm text-paws-text">
                  MFA is active using <strong>{status.method?.toUpperCase()}</strong>. Your account is protected.
                </p>
                <Button variant="danger" size="sm" onClick={handleDisable}>Disable MFA</Button>
              </div>
            ) : setupData ? (
              <div className="space-y-4">
                <p className="text-sm text-paws-text">
                  Scan this with your authenticator app or enter the secret manually:
                </p>
                <div className="bg-paws-bg rounded-md p-3 font-mono text-xs text-paws-text break-all">
                  {setupData.secret}
                </div>
                <Input
                  label="Verification Code"
                  placeholder="Enter 6-digit code"
                  value={verifyCode}
                  onChange={(e) => setVerifyCode(e.target.value)}
                  maxLength={6}
                />
                {error && <p className="text-sm text-paws-danger">{error}</p>}
                <div className="flex gap-2">
                  <Button onClick={handleVerify} disabled={verifyCode.length !== 6}>Verify & Enable</Button>
                  <Button variant="outline" onClick={() => setSetupData(null)}>Cancel</Button>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <p className="text-sm text-paws-text-muted">
                  MFA adds a second layer of security. You'll need an authenticator app like Google Authenticator or Authy.
                </p>
                {error && <p className="text-sm text-paws-danger">{error}</p>}
                <Button onClick={handleEnable}>
                  <Smartphone className="h-4 w-4 mr-1" /> Enable TOTP
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
