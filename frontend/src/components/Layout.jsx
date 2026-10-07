import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Users, Search, Mail, Activity, LogOut, Zap, Inbox, MailCheck
} from 'lucide-react'
import { useState, useEffect } from 'react'

const navItems = [
  { to: '/dashboard',    icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/leads',        icon: Users,           label: 'Leads' },
  { to: '/audits',       icon: Search,          label: 'SEO Audits' },
  { to: '/campaigns',    icon: Mail,            label: 'Campaigns' },
  { to: '/inbox',        icon: Inbox,           label: 'Inbox',         badge: 'converted' },
  { to: '/email-review', icon: MailCheck,        label: 'Email Review',  badge: 'emailReview' },
  { to: '/activity',     icon: Activity,        label: 'Activity Log' },
]

export default function Layout() {
  const navigate = useNavigate()
  const [convertedCount, setConvertedCount]     = useState(0)
  const [emailReviewCount, setEmailReviewCount] = useState(0)

  useEffect(() => {
    const token = localStorage.getItem('teb_token')
    if (!token) return
    // Fetch converted lead count for the Inbox badge
    fetch('/api/replies/stats', {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setConvertedCount(d.converted || 0) })
      .catch(() => {})
    // Fetch pending email corrections count for the Email Review badge
    fetch('/api/email-review/stats', {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setEmailReviewCount(d.pending || 0) })
      .catch(() => {})
  }, [])

  function handleLogout() {
    localStorage.removeItem('teb_token')
    navigate('/login')
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* ── Sidebar ── */}
      <aside className="w-64 flex-shrink-0 bg-surface-card border-r border-surface-border flex flex-col">
        {/* Logo */}
        <div className="px-6 py-5 border-b border-surface-border">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-brand-600 rounded-lg flex items-center justify-center">
              <Zap size={16} className="text-white" />
            </div>
            <div>
              <p className="text-sm font-bold text-white">TEB Solutions</p>
              <p className="text-[10px] text-slate-500 uppercase tracking-widest">LeadGen OS</p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-4 overflow-y-auto">
          {navItems.map(({ to, icon: Icon, label, badge }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                isActive ? 'nav-link nav-link-active' : 'nav-link'
              }
            >
              <Icon size={18} />
              <span className="text-sm font-medium" style={{ flex: 1 }}>{label}</span>
              {badge === 'converted' && convertedCount > 0 && (
                <span style={{
                  background: '#16a34a', color: '#fff',
                  fontSize: 10, fontWeight: 700,
                  padding: '1px 6px', borderRadius: 20,
                  minWidth: 18, textAlign: 'center',
                }}>
                  {convertedCount}
                </span>
              )}
              {badge === 'emailReview' && emailReviewCount > 0 && (
                <span style={{
                  background: '#d97706', color: '#fff',
                  fontSize: 10, fontWeight: 700,
                  padding: '1px 6px', borderRadius: 20,
                  minWidth: 18, textAlign: 'center',
                }}>
                  {emailReviewCount}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Logout */}
        <div className="px-3 py-4 border-t border-surface-border">
          <button
            onClick={handleLogout}
            className="nav-link w-full rounded-lg text-red-400 hover:text-red-300 hover:bg-red-500/10 border-transparent"
          >
            <LogOut size={18} />
            <span className="text-sm font-medium">Logout</span>
          </button>
        </div>
      </aside>

      {/* ── Main content ── */}
      <main className="flex-1 overflow-y-auto bg-surface">
        <div className="page-enter">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
