import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';
import HomePage from './pages/HomePage';
import SearchPage from './pages/SearchPage';
import DocumentsPage from './pages/DocumentsPage';
import StatsPage from './pages/StatsPage';
import McpPage from './pages/McpPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <Layout>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/documents" element={<DocumentsPage />} />
            <Route path="/stats" element={<StatsPage />} />
            <Route path="/mcp" element={<McpPage />} />
          </Routes>
        </Layout>
      </Router>
    </QueryClientProvider>
  );
}

export default App;
