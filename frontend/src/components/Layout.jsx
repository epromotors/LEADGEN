import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, Users, Search, Mail, Activity, LogOut, Zap, Inbox, MailCheck, Menu, X
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
  const location = useLocation()
  const [convertedCount, setConvertedCount]     = useState(0)
  const [emailReviewCount, setEmailReviewCount] = useState(0)
  const [mobileOpen, setMobileOpen]             = useState(false)

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

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

  const renderNavContent = () => (
    <>
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
    </>
  )

  return (
    <div className="flex flex-col md:flex-row h-screen overflow-hidden">
      {/* ── Mobile Top Header ── */}
      <div className="md:hidden flex items-center justify-between px-4 py-3 bg-surface-card border-b border-surface-border flex-shrink-0 z-30">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 bg-brand-600 rounded-lg flex items-center justify-center">
            <Zap size={14} className="text-white" />
          </div>
          <div>
            <p className="text-sm font-bold text-white">TEB Solutions</p>
          </div>
        </div>
        <button
          onClick={() => setMobileOpen(!mobileOpen)}
          className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-surface-elevated transition-colors"
          aria-label="Toggle navigation"
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* ── Desktop Sidebar ── */}
      <aside className="hidden md:flex md:w-64 flex-shrink-0 bg-surface-card border-r border-surface-border flex-col">
        {renderNavContent()}
      </aside>

      {/* ── Mobile Drawer ── */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden flex">
          <div
            className="fixed inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="relative w-64 max-w-[85%] bg-surface-card border-r border-surface-border flex flex-col z-10 h-full shadow-2xl">
            {renderNavContent()}
          </aside>
        </div>
      )}

      {/* ── Main content ── */}
      <main className="flex-1 overflow-y-auto bg-surface">
        <div className="page-enter">
          <Outlet />
        </div>
      </main>
    </div>
  )
}

