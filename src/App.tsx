import { BrowserRouter, Routes, Route } from "react-router-dom";
import Navigation from "./components/Navigation";
import Footer from "./components/Footer";
import ErrorBoundary from "./components/ErrorBoundary";
import HomePage from "./pages/HomePage";
import ChatPage from "./pages/ChatPage";
import ResearchPage from "./pages/ResearchPage";
import DashboardPage from "./pages/DashboardPage";
import IndiaDashboardPage from "./pages/IndiaDashboardPage";
import IndiaDemoIndexPage from "./pages/IndiaDemoIndexPage";
import HistoryPage from "./pages/HistoryPage";
import MethodologyPage from "./pages/MethodologyPage";
import TermsPage from "./pages/TermsPage";
import PrivacyPage from "./pages/PrivacyPage";
import AboutPage from "./pages/AboutPage";
import NotFoundPage from "./pages/NotFoundPage";

export default function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <div className="flex min-h-screen flex-col bg-paper font-sans text-ink">
          <Navigation />
          <main className="flex-1">
            <Routes>
              <Route path="/" element={<HomePage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/about" element={<AboutPage />} />
              <Route path="/methodology" element={<MethodologyPage />} />
              <Route path="/terms" element={<TermsPage />} />
              <Route path="/privacy" element={<PrivacyPage />} />
              <Route path="/research" element={<ResearchPage />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              {/* India research dashboard — the destination for a company the
                  backend routed to the India pipeline. */}
              <Route path="/dashboard/india" element={<IndiaDashboardPage />} />
              {/* India demo dashboards — development fixture data, clearly labeled */}
              <Route path="/dashboard/demo/india" element={<IndiaDemoIndexPage />} />
              <Route path="/dashboard/demo/india/:entity" element={<IndiaDashboardPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </main>
          <Footer />
        </div>
      </ErrorBoundary>
    </BrowserRouter>
  );
}
