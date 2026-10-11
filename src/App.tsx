import { useRef } from 'react';
import { HashRouter, Link, Route, Routes, useLocation, useSearchParams } from 'react-router-dom';
import { BottomTabBar, ErrorBoundary, OfflineBanner, ProtectedRoute, ScrollKeeper, TopBar } from './components/AppShell';
import { ToastProvider } from './hooks/toast';
import { HomePage } from './pages/HomePage';
import { AuthPage } from './pages/AuthPage';
import { ResearchPage } from './pages/ResearchPage';
import { DashboardPage, DashboardTopActions } from './pages/DashboardPage';
import { HistoryPage } from './pages/HistoryPage';
import { ProfilePage } from './pages/ProfilePage';
import { ChatPage } from './pages/ChatPage';
import { AboutPage, LegalPage, LetterPage, MethodologyPage, MoreScreen, NotFoundPage, ReviewsPage } from './pages/StaticPages';

function Shell() {
  const loc = useLocation();
  const [params] = useSearchParams();
  const mainRef = useRef<HTMLElement | null>(null);
  const path = loc.pathname;

  const isProcessing = path === '/research' && params.has('ticker');
  const isChat = path === '/chat';
  const isAuth = path === '/auth';

  let title = '';
  let root = false;
  let action: React.ReactNode = null;

  if (path === '/') { title = ''; root = true; action = <Link to="/more" aria-label="More options" className="pressable flex h-11 w-11 items-center justify-center rounded-xl font-display text-[19px] font-bold text-white">⋯</Link>; }
  else if (path === '/auth') title = 'Welcome';
  else if (path === '/research') title = isProcessing ? 'Researching' : 'Research';
  else if (path === '/dashboard') { title = 'Dashboard'; action = <DashboardTopActions />; }
  else if (path === '/history') { title = 'History'; root = true; }
  else if (path === '/profile') { title = 'Profile'; root = true; }
  else if (path === '/chat') { title = 'Ask AI'; root = true; }
  else if (path === '/methodology') title = 'Methodology';
  else if (path === '/about') title = 'About';
  else if (path === '/reviews') title = 'Reviews';
  else if (path === '/limit') title = 'Quota';
  else if (path === '/terms') title = 'Terms';
  else if (path === '/privacy') title = 'Privacy';
  else if (path === '/more') title = 'More';
  else title = 'Finora';

  return (
    <div className="app-outer">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-xl focus:bg-[#ff5a1f] focus:px-4 focus:py-2 focus:text-white">
        Skip to content
      </a>
      <div className="app-column">
        <OfflineBanner />
        {!isProcessing && !isChat && !isAuth && <TopBar title={title} action={action} root={root} />}
        {(isChat || isAuth) && <TopBar title={title} action={action} root={path === '/chat'} />}
        <main id="main" ref={mainRef} className="app-main" tabIndex={-1}>
          <ScrollKeeper mainRef={mainRef} />
          <div key={path + (isProcessing ? params.get('ticker') : '')} className={isChat ? 'anim-route h-full' : 'anim-route min-h-full'}>
            <Routes location={loc}>
              <Route path="/" element={<HomePage />} />
              <Route path="/auth" element={<AuthPage />} />
              <Route path="/methodology" element={<MethodologyPage />} />
              <Route path="/about" element={<AboutPage />} />
              <Route path="/reviews" element={<ReviewsPage />} />
              <Route path="/limit" element={<LetterPage />} />
              <Route path="/terms" element={<LegalPage kind="terms" />} />
              <Route path="/privacy" element={<LegalPage kind="privacy" />} />
              <Route path="/research" element={<ProtectedRoute><ResearchPage /></ProtectedRoute>} />
              <Route path="/dashboard" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
              <Route path="/history" element={<ProtectedRoute><HistoryPage /></ProtectedRoute>} />
              <Route path="/profile" element={<ProtectedRoute><ProfilePage /></ProtectedRoute>} />
              <Route path="/chat" element={<ProtectedRoute><ChatPage /></ProtectedRoute>} />
              <Route path="/more" element={<MoreScreen />} />
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </div>
        </main>
        <BottomTabBar />
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <HashRouter>
        <ToastProvider>
          <Shell />
        </ToastProvider>
      </HashRouter>
    </ErrorBoundary>
  );
}
