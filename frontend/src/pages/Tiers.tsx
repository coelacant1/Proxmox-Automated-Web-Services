import { useState, useEffect } from 'react';
import api from '../api/client';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Modal } from '@/components/ui/Modal';
import { Textarea } from '@/components/ui/Textarea';
import { useToast } from '@/components/ui/Toast';
import { Shield, Check, Clock, X } from 'lucide-react';

interface Tier {
  id: string;
  name: string;
  description: string | null;
  capabilities: string[];
  is_default: boolean;
}

interface TierRequest {
  id: string;
  tier_id: string;
  tier_name: string | null;
  reason: string | null;
  status: string;
  admin_notes: string | null;
  reviewed_by: string | null;
  created_at: string | null;
}

const CAPABILITY_LABELS: Record<string, string> = {
  'template.request': 'Request VM Templates',
  'ha.manage': 'Manage High Availability',
  'group.create': 'Create Groups',
  'group.manage': 'Manage Groups',
  'volume.share': 'Share Volumes',
  'vpc.share': 'Share VPCs',
  'resource.share': 'Share Resources',
  'bucket.share': 'Share Buckets',
};

export default function Tiers() {
  const [tiers, setTiers] = useState<Tier[]>([]);
  const [myTier, setMyTier] = useState<Tier | null>(null);
  const [requests, setRequests] = useState<TierRequest[]>([]);
  const [showRequest, setShowRequest] = useState(false);
  const [selectedTier, setSelectedTier] = useState<Tier | null>(null);
  const [reason, setReason] = useState('');
  const toast = useToast();

  const fetchAll = () => {
    api.get('/api/tiers/').then(r => setTiers(r.data || [])).catch(() => {});
    api.get('/api/tiers/me').then(r => setMyTier(r.data)).catch(() => setMyTier(null));
    api.get('/api/tiers/requests/mine').then(r => setRequests(r.data || [])).catch(() => {});
  };

  useEffect(() => { fetchAll(); }, []);

  const pendingRequest = requests.find(r => r.status === 'pending');

  const openRequest = (tier: Tier) => {
    setSelectedTier(tier);
    setReason('');
    setShowRequest(true);
  };

  const submitRequest = async () => {
    if (!selectedTier) return;
    try {
      await api.post('/api/tiers/request', { tier_id: selectedTier.id, reason: reason || null });
      toast.toast('Tier request submitted for admin review', 'success');
      setShowRequest(false);
      fetchAll();
    } catch (e: any) {
      const d = e.response?.data?.detail;
      toast.toast(typeof d === 'string' ? d : 'Failed to submit request', 'error');
    }
  };

  const statusBadge = (status: string) => {
    if (status === 'approved') return <Badge variant="success"><Check className="w-3 h-3 mr-1" />Approved</Badge>;
    if (status === 'rejected') return <Badge variant="danger"><X className="w-3 h-3 mr-1" />Rejected</Badge>;
    return <Badge variant="warning"><Clock className="w-3 h-3 mr-1" />Pending</Badge>;
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-paws-text">Account Tiers</h1>
        <p className="text-paws-text-muted text-sm mt-1">
          Tiers unlock additional capabilities. Request a tier upgrade below.
        </p>
      </div>

      {/* Current Tier */}
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Shield className="w-5 h-5" /> Your Current Tier</CardTitle></CardHeader>
        <CardContent>
          {myTier ? (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-paws-text font-medium text-lg">{myTier.name}</span>
                {myTier.is_default && <Badge variant="info">Default</Badge>}
              </div>
              {myTier.description && <p className="text-paws-text-muted text-sm mb-3">{myTier.description}</p>}
              <div className="flex flex-wrap gap-2">
                {myTier.capabilities.map(cap => (
                  <Badge key={cap} variant="success">{CAPABILITY_LABELS[cap] || cap}</Badge>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-paws-text-muted">No tier assigned. You have base-level access.</p>
          )}
        </CardContent>
      </Card>

      {/* Pending Request */}
      {pendingRequest && (
        <Card>
          <CardContent>
            <div className="flex items-center gap-3">
              <Clock className="w-5 h-5 text-yellow-400" />
              <div>
                <p className="text-paws-text font-medium">Pending Tier Request</p>
                <p className="text-paws-text-muted text-sm">
                  You requested <span className="font-medium text-paws-text">{pendingRequest.tier_name}</span>
                  {pendingRequest.reason && <> &mdash; "{pendingRequest.reason}"</>}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Available Tiers */}
      <div>
        <h2 className="text-paws-text font-semibold mb-3">Available Tiers</h2>
        {tiers.length === 0 ? (
          <p className="text-paws-text-muted text-sm">No tiers have been configured by the administrator.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {tiers.map(tier => {
              const isCurrent = myTier?.id === tier.id;
              return (
                <Card key={tier.id} className={isCurrent ? 'ring-2 ring-paws-accent' : ''}>
                  <CardHeader>
                    <CardTitle className="flex items-center justify-between">
                      <span>{tier.name}</span>
                      {isCurrent && <Badge variant="success">Current</Badge>}
                      {tier.is_default && !isCurrent && <Badge variant="info">Default</Badge>}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {tier.description && <p className="text-paws-text-muted text-sm mb-3">{tier.description}</p>}
                    <div className="space-y-1 mb-4">
                      <p className="text-xs text-paws-text-muted font-medium uppercase tracking-wide">Capabilities</p>
                      {tier.capabilities.length === 0 ? (
                        <p className="text-paws-text-muted text-sm">Base access only</p>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {tier.capabilities.map(cap => (
                            <span key={cap} className="text-xs bg-paws-bg-lighter px-2 py-0.5 rounded text-paws-text">
                              {CAPABILITY_LABELS[cap] || cap}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    {!isCurrent && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => openRequest(tier)}
                        disabled={!!pendingRequest}
                      >
                        {pendingRequest ? 'Request Pending' : 'Request This Tier'}
                      </Button>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>

      {/* Request History */}
      {requests.length > 0 && (
        <div>
          <h2 className="text-paws-text font-semibold mb-3">Request History</h2>
          <div className="space-y-2">
            {requests.map(req => (
              <Card key={req.id}>
                <CardContent>
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-paws-text font-medium">{req.tier_name}</span>
                      {req.reason && <span className="text-paws-text-muted text-sm ml-2">&mdash; {req.reason}</span>}
                      {req.admin_notes && (
                        <p className="text-xs text-paws-text-muted mt-1">Admin: {req.admin_notes}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {statusBadge(req.status)}
                      {req.created_at && (
                        <span className="text-xs text-paws-text-muted">
                          {new Date(req.created_at).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Request Modal */}
      <Modal open={showRequest} onClose={() => setShowRequest(false)} title={`Request Tier: ${selectedTier?.name}`}>
        <div className="space-y-3">
          {selectedTier?.description && (
            <p className="text-paws-text-muted text-sm">{selectedTier.description}</p>
          )}
          {selectedTier && selectedTier.capabilities.length > 0 && (
            <div>
              <p className="text-xs text-paws-text-muted font-medium mb-1">This tier unlocks:</p>
              <div className="flex flex-wrap gap-1">
                {selectedTier.capabilities.map(cap => (
                  <Badge key={cap} variant="info">{CAPABILITY_LABELS[cap] || cap}</Badge>
                ))}
              </div>
            </div>
          )}
          <Textarea
            label="Reason (optional)"
            rows={3}
            value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder="Why do you need this tier?"
          />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setShowRequest(false)}>Cancel</Button>
            <Button onClick={submitRequest}>Submit Request</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
