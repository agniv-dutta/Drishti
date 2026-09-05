import React, { useState, useEffect, type FormEvent } from 'react';
import { motion } from 'framer-motion';
import { Activity, RefreshCw, MessageSquare, PhoneCall, Tag, FileText, ClipboardList, ArrowRight, Building2, X } from 'lucide-react';
import './LandingPage.css';

const LandingPage: React.FC = () => {
  const features = [
    {
      title: "Payment Retry Optimizer",
      desc: "Intelligent retry logic with soft decline detection",
      icon: <RefreshCw size={24} />,
      href: '#/page/platform',
    },
    {
      title: "SMS Recovery Campaigns",
      desc: "Personalized text outreach with link tracking",
      icon: <MessageSquare size={24} />,
      href: '#/page/solutions',
    },
    {
      title: "Voice Outreach (Hinglish)",
      desc: "IVR-based customer contact in local language",
      icon: <PhoneCall size={24} />,
      href: '#/page/integrations',
    },
    {
      title: "Smart Offer Engine",
      desc: "Dynamic discounts & installment plans",
      icon: <Tag size={24} />,
      href: '#/page/solutions',
    },
    {
      title: "B2B Receivables Chaser",
      desc: "Automated follow-up for overdue invoices",
      icon: <FileText size={24} />,
      href: '#/page/company',
    },
    {
      title: "Real-time Audit Trail",
      desc: "Full compliance logging & transparency",
      icon: <ClipboardList size={24} />,
      href: '#/page/company',
    }
  ];

  const testimonials = [
    {
      text: "Drishti gave our collections team a clear, AI-assisted recovery workflow with less manual coordination.",
      author: "Priya Sharma",
      company: "VP Finance, TechCorp India"
    },
    {
      text: "The localized Voice Outreach in Hinglish was a game changer for our Tier 2 customer base. Highly empathetic and incredibly effective.",
      author: "Rahul Desai",
      company: "Director of Operations, FinServe"
    },
    {
      text: "Their Smart Offer Engine balances recovery decisions with a thoughtful customer experience.",
      author: "Anita Patel",
      company: "Head of Payments, E-comm Plus"
    }
  ];

  const [currentTestimonial, setCurrentTestimonial] = useState(0);
  const [email, setEmail] = useState('');
  const [ctaIntent, setCtaIntent] = useState<'demo' | null>(null);

  const goToDashboard = () => {
    window.location.hash = '#/dashboard/overview';
  };

  const handleCtaContinue = () => {
    setCtaIntent(null);
    goToDashboard();
  };

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTestimonial((prev) => (prev + 1) % testimonials.length);
    }, 5000);
    return () => clearInterval(timer);
  }, [testimonials.length]);

  const openCtaModal = (intent: 'demo') => {
    setCtaIntent(intent);
  };

  const handleCtaSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    goToDashboard();
  };

  return (
    <div className="page-wrapper">
      <main className="hero">
      {/* Background Blobs */}
      <div className="blob blob-1"></div>
      <div className="blob blob-2"></div>
      <div className="blob blob-3"></div>

      {/* Header */}
      <header>
        <div className="logo-container">
          <svg width="24" height="24" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="32" height="32" rx="8" fill="var(--champagne)"/>
            <path d="M12 8H18C21.3137 8 24 10.6863 24 14V18C24 21.3137 21.3137 24 18 24H12V8Z" fill="var(--coral)"/>
            <path d="M12 12H16C18.2091 12 20 13.7909 20 16C20 18.2091 18.2091 20 16 20H12V12Z" fill="var(--champagne)"/>
          </svg>
          <span className="logo-text">Drishti</span>
        </div>
        
        <nav className="header-nav">
          <a href="#/page/platform" className="nav-link">Platform</a>
          <a href="#/page/solutions" className="nav-link">Solutions</a>
          <a href="#/page/integrations" className="nav-link">Integrations</a>
          <a href="#/page/company" className="nav-link">Company</a>
        </nav>

        <div className="login-container">
          <a href="#/page/client-login" className="client-login">Client Login</a>
          <a href="#/page/get-started" className="btn-started">Get Started</a>
        </div>
      </header>

      {/* Main Split Content */}
      <div className="split-layout">
        
        {/* Left Side (Text) */}
        <section className="left-panel">
          <motion.h1 
            className="headline"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
          >
            Recover Revenue Before It Disappears
          </motion.h1>
          
          <motion.p 
            className="subheadline"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
          >
            AI agents detect failed payments and execute recovery workflows—no manual intervention.
          </motion.p>
          
          <motion.button 
            className="cta-button"
            onClick={goToDashboard}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.2, ease: [0.16, 1, 0.3, 1] }}
          >
            Start Free Trial
          </motion.button>
        </section>

        {/* Right Side (Interactive Element) */}
        <section className="right-panel">
          <div className="viz-container">
            
            {/* Floating Stats */}
            <motion.div 
              className="floating-stat floating-stat-1"
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 1, delay: 0.5, ease: "easeOut" }}
            >
              <div className="flex items-center" style={{ gap: '8px', color: 'var(--coral)' }}>
                <Activity size={16} />
                <span className="stat-label">Recovery intelligence</span>
              </div>
              <span className="stat-value">Live signals</span>
            </motion.div>

            <motion.div 
              className="floating-stat floating-stat-2"
              initial={{ opacity: 0, y: -30 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 1, delay: 0.7, ease: "easeOut" }}
            >
              <div className="flex items-center" style={{ gap: '8px', color: 'var(--coral)' }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                </svg>
                <span className="stat-label">Recovery strategy</span>
              </div>
              <span className="stat-value">Adaptive</span>
            </motion.div>

            {/* Animation visualization */}
            <div style={{ position: 'relative', width: '300px', height: '300px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              
              {/* Central Node (Decline State) */}
              <motion.div 
                className="node-central"
                animate={{
                  boxShadow: [
                    "0 0 0px rgba(214, 74, 99, 0)",
                    "0 0 40px rgba(214, 74, 99, 0.6)",
                    "0 0 0px rgba(214, 74, 99, 0)"
                  ]
                }}
                transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
              />

              {/* Pulse rings */}
              <motion.div 
                className="pulse-ring"
                animate={{
                  scale: [1, 2, 2.5],
                  opacity: [0.8, 0, 0],
                  borderWidth: ["2px", "1px", "0px"]
                }}
                transition={{ duration: 2, repeat: Infinity, ease: "easeOut" }}
              />

              {/* Path 1 */}
              <div className="recovery-path path-1">
                <motion.div 
                  style={{ position: 'absolute', right: 0, top: '50%' }}
                  animate={{
                    opacity: [0, 1, 1, 0],
                    scale: [0.5, 1, 1, 0.5]
                  }}
                  transition={{ duration: 4, times: [0, 0.3, 0.7, 1], repeat: Infinity }}
                >
                  <div className="node-end" />
                </motion.div>
                <motion.div 
                  style={{ position: 'absolute', top: '-1px', left: 0, height: '4px', background: 'var(--coral)', width: '20px', borderRadius: '2px', filter: 'blur(2px)' }}
                  animate={{ left: ['0%', '100%'], opacity: [0, 1, 0] }}
                  transition={{ duration: 2, repeat: Infinity, ease: "linear", delay: 0.5 }}
                />
              </div>

              {/* Path 2 */}
              <div className="recovery-path path-2">
                <motion.div 
                  style={{ position: 'absolute', right: 0, top: '50%' }}
                  animate={{
                    opacity: [0, 1, 1, 0],
                    scale: [0.5, 1, 1, 0.5]
                  }}
                  transition={{ duration: 4, times: [0, 0.3, 0.7, 1], repeat: Infinity, delay: 0.5 }}
                >
                  <div className="node-end" />
                </motion.div>
                <motion.div 
                  style={{ position: 'absolute', top: '-1px', left: 0, height: '4px', background: 'var(--coral)', width: '20px', borderRadius: '2px', filter: 'blur(2px)' }}
                  animate={{ left: ['0%', '100%'], opacity: [0, 1, 0] }}
                  transition={{ duration: 2, repeat: Infinity, ease: "linear", delay: 1 }}
                />
              </div>

              {/* Path 3 */}
              <div className="recovery-path path-3">
                <motion.div 
                  style={{ position: 'absolute', right: 0, top: '50%' }}
                  animate={{
                    opacity: [0, 1, 1, 0],
                    scale: [0.5, 1, 1, 0.5]
                  }}
                  transition={{ duration: 4, times: [0, 0.3, 0.7, 1], repeat: Infinity, delay: 1 }}
                >
                  <div className="node-end" style={{ background: 'var(--coral)', boxShadow: '0 0 15px rgba(255, 107, 84, 0.5)' }} />
                </motion.div>
                <motion.div 
                  style={{ position: 'absolute', top: '-1px', left: 0, height: '4px', background: 'var(--coral)', width: '20px', borderRadius: '2px', filter: 'blur(2px)' }}
                  animate={{ left: ['0%', '100%'], opacity: [0, 1, 0] }}
                  transition={{ duration: 2, repeat: Infinity, ease: "linear", delay: 1.5 }}
                />
              </div>

            </div>
          </div>
        </section>
      </div>
      </main>

      {/* Features Section */}
      <section className="features-section">
        <motion.h2 
          className="section-title"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6 }}
        >
          Precision Recovery Tools
        </motion.h2>
        
        <div className="features-grid">
          {features.map((feature, index) => (
            <motion.div 
              key={index}
              className="feature-card"
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-50px" }}
              transition={{ duration: 0.5, delay: index * 0.1 }}
            >
              <div className="feature-icon">
                {feature.icon}
              </div>
              <h3 className="feature-title">{feature.title}</h3>
              <p className="feature-desc">{feature.desc}</p>
              <a href={feature.href} className="feature-link">
                Learn more <ArrowRight size={16} />
              </a>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Trust Section */}
      <section className="trust-section">
        <div className="trust-grid">
          
          {/* Column 1: Metrics */}
          <div className="trust-col">
            <h3>Proven Results</h3>
            <div className="metrics-container">
              <div className="metric-item">
                <span className="metric-stat highlight">Live</span>
                <span className="metric-label">Recovery data</span>
              </div>
              <div className="metric-item">
                <span className="metric-stat">Context-aware</span>
                <span className="metric-label">Strategy selection</span>
              </div>
              <div className="metric-item">
                <span className="metric-stat">Multi-channel</span>
                <span className="metric-label">Recovery orchestration</span>
              </div>
            </div>
          </div>

          {/* Column 2: Testimonial Carousel */}
          <div className="trust-col">
            <h3>Client Success</h3>
            <div className="testimonial-box">
              <div className="stars">★★★★★</div>
              <motion.p 
                key={currentTestimonial}
                className="testimonial-text"
                initial={{ opacity: 0, x: 10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.5 }}
              >
                "{testimonials[currentTestimonial].text}"
              </motion.p>
              <motion.div 
                key={`author-${currentTestimonial}`}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.5, delay: 0.2 }}
              >
                <div className="testimonial-author">{testimonials[currentTestimonial].author}</div>
                <div className="testimonial-company">{testimonials[currentTestimonial].company}</div>
              </motion.div>
              
              <div className="carousel-dots">
                {testimonials.map((_, idx) => (
                  <button 
                    key={idx} 
                    className={`dot ${idx === currentTestimonial ? 'active' : ''}`}
                    onClick={() => setCurrentTestimonial(idx)}
                    aria-label={`Go to testimonial ${idx + 1}`}
                  />
                ))}
              </div>
            </div>
          </div>

          {/* Column 3: Company Logos */}
          <div className="trust-col">
            <h3>Built for recovery teams</h3>
            <div className="logos-grid">
              {[1, 2, 3, 4, 5, 6].map((i) => (
                <div key={i} className="logo-item" title="Partner Logo Placeholder">
                  <Building2 size={32} />
                </div>
              ))}
            </div>
          </div>

        </div>
      </section>

      {/* Final CTA Section */}
      <section className="final-cta-section" aria-labelledby="final-cta-title">
        <motion.div
          className="final-cta-panel"
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-120px" }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        >
          <div className="final-cta-badge">Built for recovery-led growth</div>
          <h2 id="final-cta-title" className="final-cta-title">Ready to Stop Losing Revenue?</h2>
          <p className="final-cta-subtitle">Bring failed-payment recovery into one visible workflow with Drishti.</p>

          <div className="final-cta-actions" role="group" aria-label="Primary actions">
            <button
              type="button"
              className="final-cta-primary"
              onClick={goToDashboard}
            >
              Start Your Free Trial
            </button>
            <button
              type="button"
              className="final-cta-secondary"
              onClick={() => openCtaModal('demo')}
            >
              Schedule Demo
            </button>
          </div>

          <form className="final-cta-form" onSubmit={handleCtaSubmit}>
            <label className="sr-only" htmlFor="cta-email">Email address</label>
            <input
              id="cta-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@company.com"
              aria-label="Email address"
            />
            <button type="submit" className="final-cta-form-submit">
              Continue
            </button>
          </form>
        </motion.div>
      </section>

      {ctaIntent && (
        <div className="cta-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="cta-modal-title">
          <motion.div
            className="cta-modal"
            initial={{ opacity: 0, scale: 0.96, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ duration: 0.22, ease: 'easeOut' }}
          >
            <button className="cta-modal-close" type="button" onClick={() => setCtaIntent(null)} aria-label="Close dialog">
              <X size={18} />
            </button>
            <p className="cta-modal-kicker">Next step</p>
            <h3 id="cta-modal-title">
              Schedule your demo
            </h3>
            <p className="cta-modal-copy">
              {email
                ? `We’ll follow up with ${email} and get you into the right flow.`
                : 'Add your email above and we’ll route you to the right onboarding flow.'}
            </p>
            <div className="cta-modal-actions">
              <button type="button" className="cta-modal-primary" onClick={handleCtaContinue}>
                Continue
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </div>
  );
};

export default LandingPage;
