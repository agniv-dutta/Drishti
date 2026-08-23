import React, { useCallback, useEffect, useState } from 'react';
import LandingPage from './components/LandingPage';
import DashboardOverview from './components/DashboardOverview';
import DashboardPage from './components/DashboardPage';

type Route =
  | { name: 'landing' }
  | { name: 'dashboard' }
  | { name: 'journey'; paymentId: string | null };

const getRoute = (): Route => {
  const hash = window.location.hash.replace(/^#/, '');
  const segments = hash.split('/').filter(Boolean);

  if (segments[0] === 'dashboard') {
    return { name: 'dashboard' };
  }
  if (segments[0] === 'journey') {
    return { name: 'journey', paymentId: segments[1] ?? null };
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
        return <DashboardOverview />;
      case 'journey':
        return <DashboardPage paymentId={route.paymentId} />;
      case 'landing':
      default:
        return <LandingPage />;
    }
  }, [route]);

  return renderRoute();
}

export default App;
