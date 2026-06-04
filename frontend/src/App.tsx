import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from './stores/auth';
import Dashboard from './pages/Dashboard';
import JobsPage from './pages/JobsPage';
import { useEffect } from 'react';
import api from './api/client';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  const { setAuth, token } = useAuthStore();

  useEffect(() => {
    const cookieToken = document.cookie
      .split('; ')
      .find((row) => row.startsWith('token='))
      ?.split('=')[1];
    if (cookieToken && !token) {
      setAuth(cookieToken, '', '');
      api.get('/users').catch(() => {
        document.cookie = 'token=; max-age=0';
        window.location.href = '/login';
      });
    }
  }, []);

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <Routes>
        <Route path="/login" element={<div>Redirecting to login...</div>} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/jobs"
          element={
            <ProtectedRoute>
              <JobsPage />
            </ProtectedRoute>
          }
        />
      </Routes>
    </div>
  );
}
