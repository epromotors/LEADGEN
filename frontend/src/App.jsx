import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Leads from './pages/Leads'
import Audits from './pages/Audits'
import Campaigns from './pages/Campaigns'
import ActivityLog from './pages/ActivityLog'
import InboxPage from './pages/Inbox'
import EmailReview from './pages/EmailReview'

function PrivateRoute({ children }) {
  const token = localStorage.getItem('teb_token')
  return token ? children : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={<PrivateRoute><Layout /></PrivateRoute>}
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard"   element={<Dashboard />} />
          <Route path="leads"       element={<Leads />} />
          <Route path="audits"      element={<Audits />} />
          <Route path="campaigns"   element={<Campaigns />} />
          <Route path="inbox"       element={<InboxPage />} />
          <Route path="email-review" element={<EmailReview />} />
          <Route path="activity"    element={<ActivityLog />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
