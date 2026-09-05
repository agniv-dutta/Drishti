import React, { useCallback, useEffect, useState } from 'react';
import LandingPage from './components/LandingPage';
import DashboardOverview, { type DashboardSection } from './components/DashboardOverview';
import DashboardPage from './components/DashboardPage';
import FeaturePage, { type FeaturePageSlug } from './components/FeaturePage';
import AnalyticsDashboard from './components/AnalyticsDashboard';
import WorkflowBuilder from './components/WorkflowBuilder';
import ReceivablesPage from './components/ReceivablesPage';
import SubscriptionsPage from './components/SubscriptionsPage';
import VoiceCallPage from './components/VoiceCallPage';

type Route =
  | { name: 'landing' }
  | { name: 'dashboard'; section: DashboardSection }
  | { name: 'feature'; slug: FeaturePageSlug }
  | { name: 'receivables' }
  | { name: 'subscriptions' }
  | { name: 'journey'; paymentId: string | null }
   | { name: 'voice'; callId: string | null }

const isDashboardSection = (value: string | undefined): value is DashboardSection =>
  value === 'overview' ||
  value === 'payments' ||
  value === 'recoveries' ||
  value === 'receivables' ||
  value === 'subscriptions' ||
  value === 'analytics' ||
  value === 'workflows' ||
  value === 'audit-trail' ||
  value === 'settings';

const isFeatureSlug = (value: string | undefined): value is FeaturePageSlug =>
  value === 'platform' ||
  value === 'solutions' ||
  value === 'integrations' ||
  value === 'company' ||
  value === 'client-login' ||
  value === 'get-started';

const getRoute = (): Route => {
  const hash = window.location.hash.replace(/^#/, '');
  const segments = hash.split('/').filter(Boolean);

  if (segments[0] === 'dashboard') {
    const section = isDashboardSection(segments[1]) ? segments[1] : 'overview';
    return { name: 'dashboard', section };
  }
  if (segments[0] === 'journey') {
    return { name: 'journey', paymentId: segments[1] ?? null };
  }
  if (segments[0] === 'voice') {
    return { name: 'voice', callId: segments[1] ?? null };
  }
  if (segments[0] === 'recovery' && segments[2] === 'journey') {
    return { name: 'journey', paymentId: segments[1] ?? null };
  }
  if (segments[0] === 'receivables') {
    return { name: 'receivables' };
  }
  if (segments[0] === 'subscriptions') {
    return { name: 'subscriptions' };
  }
  if (segments[0] === 'page' && isFeatureSlug(segments[1])) {
    return { name: 'feature', slug: segments[1] };
  }
  return { name: 'landing' };
};

function App() {
  const [route, setRoute] = useState<Route>(getRoute);

  useEffect(() => {
    const onHashChange = () => {
      setRoute(getRoute());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const renderRoute = useCallback(() => {
    switch (route.name) {
      case 'dashboard':
        if (route.section === 'analytics') return <AnalyticsDashboard />;
        if (route.section === 'workflows') return <WorkflowBuilder />;
        if (route.section === 'receivables') return <ReceivablesPage />;
        if (route.section === 'subscriptions') return <SubscriptionsPage />;
        return <DashboardOverview section={route.section} />;
      case 'feature':
        return <FeaturePage slug={route.slug} />;
      case 'receivables':
        return <ReceivablesPage />;
      case 'subscriptions':
        return <SubscriptionsPage />;
      case 'journey':
        return <DashboardPage paymentId={route.paymentId} />;
      case 'voice':
        return <VoiceCallPage callId={route.callId} />;
      case 'landing':
      default:
        return <LandingPage />;
    }
  }, [route]);

  return renderRoute();
}

export default App;
