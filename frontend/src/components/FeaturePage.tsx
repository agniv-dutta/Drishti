import React from 'react';
import { motion } from 'framer-motion';
import {
  ArrowRight,
  Building2,
  Globe2,
  LogIn,
  ShieldCheck,
  Sparkles,
  Zap,
} from 'lucide-react';
import './FeaturePage.css';

export type FeaturePageSlug =
  | 'platform'
  | 'solutions'
  | 'integrations'
  | 'company'
  | 'client-login'
  | 'get-started';

type FeaturePageProps = {
  slug: FeaturePageSlug;
};

const content: Record<FeaturePageSlug, {
  eyebrow: string;
  title: string;
  copy: string;
  primary: { label: string; href: string };
  secondary: { label: string; href: string };
  stats: Array<{ label: string; value: string }>;
  points: string[];
}> = {
  platform: {
    eyebrow: 'Platform',
    title: 'A control layer for failed payment recovery',
    copy: 'Use one place to see retries, automation, audit history, and the live recovery state of each account.',
    primary: { label: 'Open Dashboard', href: '#/dashboard/overview' },
    secondary: { label: 'Explore Solutions', href: '#/page/solutions' },
    stats: [
      { label: 'Coverage', value: 'Multi-channel' },
      { label: 'Visibility', value: 'Real-time' },
      { label: 'Workflow', value: 'Adaptive' },
    ],
    points: [
      'Live metrics on recovery progress',
      'Actionable audit trail for every step',
      'Built-in routing for human escalation',
    ],
  },
  solutions: {
    eyebrow: 'Solutions',
    title: 'Tools that turn failed payments into recovered revenue',
    copy: 'Retry orchestration, smart offers, SMS recovery, and voice escalation work together as one pipeline.',
    primary: { label: 'See Platform', href: '#/page/platform' },
    secondary: { label: 'Start Free Trial', href: '#/page/get-started' },
    stats: [
      { label: 'Retries', value: 'Automated' },
      { label: 'Offers', value: 'Dynamic' },
      { label: 'Support', value: 'Concierge-ready' },
    ],
    points: [
      'Retry strategy based on failure context',
      'Offer engine for soft collections',
      'Notification flows tuned per customer',
    ],
  },
  integrations: {
    eyebrow: 'Integrations',
    title: 'Connect your stack without rebuilding your ops',
    copy: 'Payments, CRM, SMS, email, and support tools can plug into the recovery flow.',
    primary: { label: 'View Platform', href: '#/page/platform' },
    secondary: { label: 'Open Dashboard', href: '#/dashboard/overview' },
    stats: [
      { label: 'Sync', value: 'Near real-time' },
      { label: 'Data', value: 'Bi-directional' },
      { label: 'Setup', value: 'Low-friction' },
    ],
    points: [
      'Push failed-payment events into the pipeline',
      'Keep CRM and collections states in sync',
      'Expose every action to the audit trail',
    ],
  },
  company: {
    eyebrow: 'Company',
    title: 'Built for teams that care about recovery and trust',
    copy: 'Verity is designed around visibility, compliance, and a clean handoff between automation and humans.',
    primary: { label: 'Meet the Platform', href: '#/page/platform' },
    secondary: { label: 'Contact Sales', href: '#/page/client-login' },
    stats: [
      { label: 'Focus', value: 'Recovery ops' },
      { label: 'Promise', value: 'Transparency' },
      { label: 'Audience', value: 'Finance teams' },
    ],
    points: [
      'Every action remains traceable',
      'Designed for operational confidence',
      'Easy handoff to client-facing workflows',
    ],
  },
  'client-login': {
    eyebrow: 'Client Login',
    title: 'Enter the client workspace',
    copy: 'This destination is ready for later authentication or a tenant selector. For now, it leads into the recovery dashboard.',
    primary: { label: 'Go to Dashboard', href: '#/dashboard/overview' },
    secondary: { label: 'Learn Platform', href: '#/page/platform' },
    stats: [
      { label: 'Access', value: 'Tenant-ready' },
      { label: 'Security', value: 'RBAC ready' },
      { label: 'Status', value: 'Preview' },
    ],
    points: [
      'Hook this route to auth later',
      'Use it as the entry point for clients',
      'Connect it to your onboarding flow',
    ],
  },
  'get-started': {
    eyebrow: 'Get Started',
    title: 'Start a trial and move into the dashboard',
    copy: 'This page gives the free-trial route a real destination before taking users into the main workspace.',
    primary: { label: 'Open Dashboard', href: '#/dashboard/overview' },
    secondary: { label: 'Back to Home', href: '#/' },
    stats: [
      { label: 'Trial', value: 'Instant' },
      { label: 'Setup', value: 'Fast' },
      { label: 'Flow', value: 'Guided' },
    ],
    points: [
      'Use this as the onboarding entry point',
      'Add signup steps later if needed',
      'Send users into the dashboard immediately',
    ],
  },
};

const iconMap: Record<FeaturePageSlug, React.ReactNode> = {
  platform: <Globe2 size={22} />,
  solutions: <Sparkles size={22} />,
  integrations: <Zap size={22} />,
  company: <Building2 size={22} />,
  'client-login': <LogIn size={22} />,
  'get-started': <ShieldCheck size={22} />,
};

const navItems: Array<{ label: string; href: string; slug: FeaturePageSlug }> = [
  { label: 'Platform', href: '#/page/platform', slug: 'platform' },
  { label: 'Solutions', href: '#/page/solutions', slug: 'solutions' },
  { label: 'Integrations', href: '#/page/integrations', slug: 'integrations' },
  { label: 'Company', href: '#/page/company', slug: 'company' },
];

const FeaturePage: React.FC<FeaturePageProps> = ({ slug }) => {
  const data = content[slug];

  return (
    <div className="feature-page">
      <header className="feature-topbar">
        <a href="#/" className="feature-brand">
          <span className="feature-brand-mark" aria-hidden="true">
            V
          </span>
          <span>Verity</span>
        </a>

        <nav className="feature-nav" aria-label="Primary">
          {navItems.map((item) => (
            <a key={item.slug} href={item.href} className={item.slug === slug ? 'active' : ''}>
              {item.label}
            </a>
          ))}
        </nav>

        <div className="feature-actions">
          <a href="#/page/client-login" className="feature-secondary-action">
            Client Login
          </a>
          <a href="#/page/get-started" className="feature-primary-action">
            Get Started
          </a>
        </div>
      </header>

      <main className="feature-main">
        <motion.section
          className="feature-hero"
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
        >
          <div className="feature-hero-icon">{iconMap[slug]}</div>
          <p className="feature-eyebrow">{data.eyebrow}</p>
          <h1>{data.title}</h1>
          <p className="feature-copy">{data.copy}</p>

          <div className="feature-actions-row">
            <a href={data.primary.href} className="feature-primary-cta">
              {data.primary.label}
              <ArrowRight size={16} />
            </a>
            <a href={data.secondary.href} className="feature-secondary-cta">
              {data.secondary.label}
            </a>
          </div>

          <div className="feature-stats">
            {data.stats.map((stat) => (
              <div key={stat.label} className="feature-stat">
                <span>{stat.label}</span>
                <strong>{stat.value}</strong>
              </div>
            ))}
          </div>
        </motion.section>

        <section className="feature-grid" aria-label={`${data.eyebrow} details`}>
          {data.points.map((point, index) => (
            <motion.article
              key={point}
              className="feature-card"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: index * 0.06 }}
            >
              <span className="feature-card-index">0{index + 1}</span>
              <p>{point}</p>
            </motion.article>
          ))}
        </section>
      </main>
    </div>
  );
};

export default FeaturePage;
