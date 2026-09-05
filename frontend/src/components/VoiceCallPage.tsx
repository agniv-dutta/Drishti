import React, { useEffect, useState } from 'react';
import { ArrowLeft, PhoneCall } from 'lucide-react';

type VoiceCallPageProps = {
  callId: string | null;
};

const VoiceCallPage: React.FC<VoiceCallPageProps> = ({ callId }) => {
  const [status, setStatus] = useState<'connecting' | 'active' | 'ended'>('connecting');

  useEffect(() => {
    if (!callId) setStatus('ended');
  }, [callId]);

  const elapsedLabel = status === 'connecting' ? 'Connecting...' : status === 'active' ? 'Call in progress' : 'Call ended';

  return (
    <div className="page-shell" style={{ padding: '2rem', maxWidth: 720, margin: '0 auto' }}>
      <a
        href="#/dashboard"
        style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#4f46e5', textDecoration: 'none', marginBottom: '1.5rem' }}
      >
        <ArrowLeft size={16} /> Back to dashboard
      </a>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: '1.25rem' }}>
        <PhoneCall size={28} style={{ color: '#4f46e5' }} />
        <div>
          <h2 style={{ margin: 0 }}>Voice IVR Outreach</h2>
          <div style={{ color: status === 'active' ? '#16a34a' : '#6b7280' }}>{elapsedLabel}</div>
        </div>
      </div>
      <div style={{ borderRadius: 12, border: '1px solid #e5e7eb', padding: '1.5rem', background: '#f9fafb' }}>
        {callId ? (
          <div>
            <div style={{ fontWeight: 600 }}>Call #{callId.slice(0, 10)}</div>
            <div style={{ marginTop: 6, color: '#6b7280' }}>IVR recovery outreach for a failed payment. Transcript and outcomes will appear here once the call completes.</div>
          </div>
        ) : (
          <div>Select a recovery with a high-touch voice strategy to start an IVR call.</div>
        )}
      </div>
    </div>
  );
};

export default VoiceCallPage;