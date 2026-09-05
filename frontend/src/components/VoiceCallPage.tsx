import React, { useEffect, useState } from 'react';
import { ArrowLeft, PhoneCall } from 'lucide-react';
import './VoiceCallPage.css';

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
    <div className="voice-page">
      <a
        href="#/dashboard"
        className="voice-back"
      >
        <ArrowLeft size={16} /> Back to dashboard
      </a>
      <main className="voice-shell">
        <div className="voice-heading">
          <div>
            <p className="voice-eyebrow">Recovery operations</p>
            <h1>Voice IVR Outreach</h1>
            <p>High-touch recovery support for customers who need a human-guided payment path.</p>
          </div>
          <div className={`voice-status ${status === 'active' ? 'live' : 'closed'}`}>
            <i />
            {elapsedLabel}
          </div>
        </div>
        <section className="voice-grid">
          <article className="voice-panel">
            <div className="voice-panel-heading">
              <h2><PhoneCall size={20} /> Call details</h2>
            </div>
            {callId ? (
              <div className="voice-result">
                <span>Call reference</span>
                <strong>#{callId.slice(0, 10)}</strong>
                <p>IVR recovery outreach for a failed payment. Transcript and outcomes will appear here once the call completes.</p>
              </div>
            ) : (
              <p className="voice-empty">Select a recovery with a high-touch voice strategy to start an IVR call.</p>
            )}
          </article>
        </section>
      </main>
    </div>
  );
};

export default VoiceCallPage;