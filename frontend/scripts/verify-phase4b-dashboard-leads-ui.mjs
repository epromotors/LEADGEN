import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import { MemoryRouter } from 'react-router-dom'

const root = fileURLToPath(new URL('..', import.meta.url))

const vite = await createServer({
  root,
  server: { middlewareMode: true },
  appType: 'custom',
  logLevel: 'error',
})

try {
  console.log('Testing Phase 4B Dashboard & Leads UI components via Vite SSR...')

  // ── 1. Load Dashboard components ──
  const { default: DashboardKpiCards } = await vite.ssrLoadModule('/src/components/dashboard/DashboardKpiCards.jsx')
  const { default: LeadPipelineBreakdown } = await vite.ssrLoadModule('/src/components/dashboard/LeadPipelineBreakdown.jsx')
  const { default: AuditHealthPanel } = await vite.ssrLoadModule('/src/components/dashboard/AuditHealthPanel.jsx')
  const { default: RecentActivityFeed } = await vite.ssrLoadModule('/src/components/dashboard/RecentActivityFeed.jsx')
  const { default: RecentLeadsTable } = await vite.ssrLoadModule('/src/components/dashboard/RecentLeadsTable.jsx')
  const { default: DashboardSkeleton } = await vite.ssrLoadModule('/src/components/dashboard/DashboardSkeleton.jsx')

  // ── 2. Load Leads components ──
  const {
    LifecycleBadge,
    VerificationBadge,
    AssociationBadge,
    WebsiteStatusBadge,
    SkippedReasonBadge,
  } = await vite.ssrLoadModule('/src/components/lead/LeadStatusBadge.jsx')
  const { default: LeadRowMobileCard } = await vite.ssrLoadModule('/src/components/lead/LeadRowMobileCard.jsx')
  const { default: LeadTableSkeleton } = await vite.ssrLoadModule('/src/components/lead/LeadTableSkeleton.jsx')
  const { default: LeadEmptyState } = await vite.ssrLoadModule('/src/components/lead/LeadEmptyState.jsx')
  const { default: EditLeadModal } = await vite.ssrLoadModule('/src/components/lead/EditLeadModal.jsx')
  const { default: AuditModeModal } = await vite.ssrLoadModule('/src/components/lead/AuditModeModal.jsx')
  const { default: AuditDoneModal } = await vite.ssrLoadModule('/src/components/lead/AuditDoneModal.jsx')

  // Verify DashboardSkeleton
  console.log('Testing DashboardSkeleton...')
  const skeletonHtml = renderToStaticMarkup(React.createElement(DashboardSkeleton))
  assert.match(skeletonHtml, /animate-pulse/)

  // Verify DashboardKpiCards
  console.log('Testing DashboardKpiCards...')
  const mockMetrics = {
    total_leads: 1250,
    audits_complete: 850,
    emails_sent: 420,
    campaigns_active: 3,
  }
  const mockAuditStats = {
    total: 1250,
    new: 300,
    auditing: 100,
    audited: 850,
    emailed: 420,
    replied: 45,
    skipped: 12,
    batch_running: true,
  }
  const mockEmailStats = {
    total_leads: 1250,
    deliverable: 780,
    valid: 800,
    invalid: 50,
    disposable: 20,
    catch_all: 100,
    risky: 30,
    not_found: 20,
    unverified: 230,
    quarantined: 70,
    pending_verification: 230,
    active_pool: 780,
    demo_only_eligible: 15,
  }
  const mockCampaigns = [
    { id: 'cmp-1', name: 'Q4 Dental Outreach', status: 'sending', sent_count: 140, total_leads: 200 },
    { id: 'cmp-2', name: 'Law Firms Pilot', status: 'completed', sent_count: 85, total_leads: 85 },
  ]

  const kpiHtml = renderToStaticMarkup(
    React.createElement(
      MemoryRouter,
      null,
      React.createElement(DashboardKpiCards, {
        metrics: mockMetrics,
        auditStats: mockAuditStats,
        emailStats: mockEmailStats,
        campaigns: mockCampaigns,
      })
    )
  )
  assert.match(kpiHtml, /Total Leads Ingested/)
  assert.match(kpiHtml, /1,250/)
  assert.match(kpiHtml, /SEO Audits Completed/)
  assert.match(kpiHtml, /850/)
  assert.match(kpiHtml, /Deliverability Pool/)
  assert.match(kpiHtml, /780/)
  assert.match(kpiHtml, /Campaigns &amp; Outreach/)
  assert.match(kpiHtml, /3 Active/)
  assert.match(kpiHtml, /Crawling/)

  // Verify LeadPipelineBreakdown
  console.log('Testing LeadPipelineBreakdown...')
  const pipelineHtml = renderToStaticMarkup(
    React.createElement(
      MemoryRouter,
      null,
      React.createElement(LeadPipelineBreakdown, {
        auditStats: mockAuditStats,
        emailStats: mockEmailStats,
      })
    )
  )
  assert.match(pipelineHtml, /Lead Lifecycle Pipeline/)
  assert.match(pipelineHtml, /New/)
  assert.match(pipelineHtml, /Auditing/)
  assert.match(pipelineHtml, /Audited/)
  assert.match(pipelineHtml, /Emailed/)
  assert.match(pipelineHtml, /Replied/)
  assert.match(pipelineHtml, /Skipped/)
  assert.match(pipelineHtml, /Deliverability &amp; Safety Gate/)
  assert.match(pipelineHtml, /Sendable/)
  assert.match(pipelineHtml, /Demo-Only/)
  assert.match(pipelineHtml, /Quarantined/)

  // Verify AuditHealthPanel
  console.log('Testing AuditHealthPanel...')
  const auditHealthHtml = renderToStaticMarkup(
    React.createElement(
      MemoryRouter,
      null,
      React.createElement(AuditHealthPanel, {
        auditStats: mockAuditStats,
        campaigns: mockCampaigns,
      })
    )
  )
  assert.match(auditHealthHtml, /Audit Engine &amp; Campaigns/)
  assert.match(auditHealthHtml, /Batch Crawler Active/)
  assert.match(auditHealthHtml, /100 In Queue/)
  assert.match(auditHealthHtml, /12 Skipped \/ Unreachable Sites/)
  assert.match(auditHealthHtml, /Q4 Dental Outreach/)

  // Verify RecentActivityFeed
  console.log('Testing RecentActivityFeed...')
  const mockActivities = [
    {
      id: 1,
      event_type: 'leads_imported',
      message: 'Imported 50 leads from q4_leads.csv. Skipped 2 duplicates.',
      created_at: new Date().toISOString(),
    },
    {
      id: 2,
      event_type: 'audit_done',
      message: 'Audit completed for Apex Dental (apexdental.com)',
      created_at: new Date().toISOString(),
    },
  ]
  const activityHtml = renderToStaticMarkup(
    React.createElement(
      MemoryRouter,
      null,
      React.createElement(RecentActivityFeed, { activities: mockActivities })
    )
  )
  assert.match(activityHtml, /Live Operations Feed/)
  assert.match(activityHtml, /Imported 50 leads from q4_leads\.csv/)
  assert.match(activityHtml, /Audit completed for Apex Dental/)

  // Verify RecentLeadsTable
  console.log('Testing RecentLeadsTable...')
  const mockRecentLeads = [
    {
      id: 'lead-1',
      business_name: 'Apex Dental Care',
      email: 'dr.smith@apexdental.com',
      website: 'https://apexdental.com',
      status: 'audited',
      email_verification_status: 'valid',
      is_quarantined: false,
    },
    {
      id: 'lead-2',
      business_name: 'Beacon Law Group',
      email: 'contact@beaconlaw.com',
      website: 'https://beaconlaw.com',
      status: 'new',
      email_verification_status: 'unverified',
      is_quarantined: true,
      quarantine_reason: 'Disposable domain',
    },
  ]
  const recentLeadsHtml = renderToStaticMarkup(
    React.createElement(
      MemoryRouter,
      null,
      React.createElement(RecentLeadsTable, { leads: mockRecentLeads })
    )
  )
  assert.match(recentLeadsHtml, /Recent Lead Intake/)
  assert.match(recentLeadsHtml, /Apex Dental Care/)
  assert.match(recentLeadsHtml, /Beacon Law Group/)
  assert.match(recentLeadsHtml, /Quarantined/)

  // Verify LeadStatusBadge components
  console.log('Testing LeadStatusBadge components...')
  const lifecycleAuditingHtml = renderToStaticMarkup(
    React.createElement(LifecycleBadge, { status: 'auditing', isAuditing: true })
  )
  assert.match(lifecycleAuditingHtml, /Auditing…/)

  const lifecycleEmailedHtml = renderToStaticMarkup(
    React.createElement(LifecycleBadge, { status: 'emailed', lastEmailedAt: '2026-10-18T10:00:00Z' })
  )
  assert.match(lifecycleEmailedHtml, /✉ Sent/)

  const verifValidHtml = renderToStaticMarkup(
    React.createElement(VerificationBadge, { status: 'valid' })
  )
  assert.match(verifValidHtml, /Deliverable/)

  const verifDisposableHtml = renderToStaticMarkup(
    React.createElement(VerificationBadge, { status: 'disposable' })
  )
  assert.match(verifDisposableHtml, /Disposable/)

  const assocMatchHtml = renderToStaticMarkup(
    React.createElement(AssociationBadge, { status: 'matched' })
  )
  assert.match(assocMatchHtml, /Domain Match/)

  const websiteCandidateHtml = renderToStaticMarkup(
    React.createElement(WebsiteStatusBadge, { status: 'candidate_match' })
  )
  assert.match(websiteCandidateHtml, /Candidate/)

  const skippedBadgeHtml = renderToStaticMarkup(
    React.createElement(SkippedReasonBadge, { auditError: 'SITE_STATUS:DOMAIN_PARKED' })
  )
  assert.match(skippedBadgeHtml, /DOMAIN PARKED/)

  // Verify LeadTableSkeleton & LeadEmptyState
  console.log('Testing LeadTableSkeleton and LeadEmptyState...')
  const tableSkeletonHtml = renderToStaticMarkup(React.createElement(LeadTableSkeleton, { rows: 3 }))
  assert.match(tableSkeletonHtml, /animate-pulse/)

  const emptyFilteredHtml = renderToStaticMarkup(
    React.createElement(LeadEmptyState, { isFiltered: true, onResetFilters: () => {} })
  )
  assert.match(emptyFilteredHtml, /No Matching Leads Found/)
  assert.match(emptyFilteredHtml, /Reset Filters &amp; Search/)

  const emptyUnfilteredHtml = renderToStaticMarkup(
    React.createElement(LeadEmptyState, { isFiltered: false, onResetFilters: () => {} })
  )
  assert.match(emptyUnfilteredHtml, /Lead Workspace Is Empty/)

  // Verify LeadRowMobileCard
  console.log('Testing LeadRowMobileCard...')
  const mobileCardHtml = renderToStaticMarkup(
    React.createElement(
      MemoryRouter,
      null,
      React.createElement(LeadRowMobileCard, {
        lead: mockRecentLeads[0],
        isSelected: false,
        onToggleSelect: () => {},
        onEdit: () => {},
        onAudit: () => {},
        onDelete: () => {},
        isAuditing: false,
      })
    )
  )
  assert.match(mobileCardHtml, /Apex Dental Care/)
  assert.match(mobileCardHtml, /dr\.smith@apexdental\.com/)
  assert.match(mobileCardHtml, /apexdental\.com/)
  assert.match(mobileCardHtml, /Deliverable/)

  // Verify AuditModeModal
  console.log('Testing AuditModeModal...')
  const auditModalHtml = renderToStaticMarkup(
    React.createElement(AuditModeModal, {
      stats: mockAuditStats,
      onSelect: () => {},
      onClose: () => {},
    })
  )
  assert.match(auditModalHtml, /Configure Batch Audit Session/)
  assert.match(auditModalHtml, /New Sites Only/)
  assert.match(auditModalHtml, /All Not Emailed/)
  assert.match(auditModalHtml, /Re-audit Everything/)
  assert.match(auditModalHtml, /Re-audit Skipped Sites/)

  // Verify AuditDoneModal
  console.log('Testing AuditDoneModal...')
  const doneModalHtml = renderToStaticMarkup(
    React.createElement(AuditDoneModal, { count: 25, onOk: () => {} })
  )
  assert.match(doneModalHtml, /Audit Batch Complete!/)
  assert.match(doneModalHtml, /25 lead websites were audited/)

  console.log('ALL PHASE 4B DASHBOARD & LEADS UI COMPONENTS PASSED SSR VERIFICATION SUCCESSFULLY!')
} finally {
  await vite.close()
}
