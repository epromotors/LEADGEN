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
  console.log('Testing Phase 4C Campaigns & Inbox UI components via Vite SSR...')

  // ── 1. Load Campaign Components ──
  const { default: CampaignKpiCards } = await vite.ssrLoadModule('/src/components/campaign/CampaignKpiCards.jsx')
  const { default: CampaignSkeleton } = await vite.ssrLoadModule('/src/components/campaign/CampaignSkeleton.jsx')
  const { default: CampaignLogsViewer } = await vite.ssrLoadModule('/src/components/campaign/CampaignLogsViewer.jsx')
  const { default: CampaignActionModal } = await vite.ssrLoadModule('/src/components/campaign/CampaignActionModal.jsx')
  const { default: CampaignListTable } = await vite.ssrLoadModule('/src/components/campaign/CampaignListTable.jsx')
  const { default: TestEmailModal } = await vite.ssrLoadModule('/src/components/campaign/TestEmailModal.jsx')
  const { default: CampaignEditorPanel } = await vite.ssrLoadModule('/src/components/campaign/CampaignEditorPanel.jsx')

  // ── 2. Load Inbox Components ──
  const { default: InboxKpiCards } = await vite.ssrLoadModule('/src/components/inbox/InboxKpiCards.jsx')
  const { default: InboxSkeleton } = await vite.ssrLoadModule('/src/components/inbox/InboxSkeleton.jsx')
  const { default: ReplyDetailModal } = await vite.ssrLoadModule('/src/components/inbox/ReplyDetailModal.jsx')
  const { default: Email2ComposeModal } = await vite.ssrLoadModule('/src/components/inbox/Email2ComposeModal.jsx')
  const { default: ConvertedLeadsTable } = await vite.ssrLoadModule('/src/components/inbox/ConvertedLeadsTable.jsx')
  const { default: AllRepliesTable } = await vite.ssrLoadModule('/src/components/inbox/AllRepliesTable.jsx')
  const { default: InboxSyncPanel } = await vite.ssrLoadModule('/src/components/inbox/InboxSyncPanel.jsx')

  // ── 3. Verify CampaignSkeleton ──
  console.log('Testing CampaignSkeleton...')
  const campSkelHtml = renderToStaticMarkup(React.createElement(CampaignSkeleton))
  assert.match(campSkelHtml, /animate-pulse/)
  assert.match(campSkelHtml, /card-elevated/)

  // ── 4. Verify CampaignKpiCards ──
  console.log('Testing CampaignKpiCards...')
  const mockCampaigns = [
    {
      id: 'c-1',
      name: 'Q4 Dental Outreach',
      status: 'sending',
      lead_ids: ['l-1', 'l-2', 'l-3'],
      sent_count: 2,
      failed_count: 0,
      skipped_count: 1,
    },
    {
      id: 'c-2',
      name: 'Modern Web Design Pilot',
      status: 'done',
      lead_ids: ['l-4', 'l-5'],
      sent_count: 2,
      failed_count: 0,
      skipped_count: 0,
    },
  ]
  const mockSenderStatus = {
    status: 'configured',
    configured: true,
    accounts: [
      {
        email: 'outreach@tebsolutions.in',
        daily_limit: 1000,
        sent_today: 4,
      },
    ],
    total_daily_capacity: 1000,
    remaining_today: 996,
  }

  const campKpiHtml = renderToStaticMarkup(
    React.createElement(CampaignKpiCards, {
      campaigns: mockCampaigns,
      senderStatus: mockSenderStatus,
    })
  )
  assert.match(campKpiHtml, /Campaign Overview/)
  assert.match(campKpiHtml, /Delivery Volume/)
  assert.match(campKpiHtml, /Delivery Health Rate/)
  assert.match(campKpiHtml, /Sender Infrastructure/)
  assert.match(campKpiHtml, /1 Running/)
  assert.match(campKpiHtml, /996 Left/)
  assert.match(campKpiHtml, /Fail-Closed/)

  // ── 5. Verify CampaignActionModal ──
  console.log('Testing CampaignActionModal...')
  const modalHtml = renderToStaticMarkup(
    React.createElement(CampaignActionModal, {
      isOpen: true,
      action: 'send',
      campaign: mockCampaigns[0],
      onConfirm: () => {},
      onCancel: () => {},
    })
  )
  assert.match(modalHtml, /Launch Campaign: Q4 Dental Outreach/)
  assert.match(modalHtml, /Safety Safeguards Active/)
  assert.match(modalHtml, /rate-limit protection/)
  assert.match(modalHtml, /Confirm &amp; Launch Outreach/)

  // ── 6. Verify CampaignListTable ──
  console.log('Testing CampaignListTable...')
  const tableHtml = renderToStaticMarkup(
    React.createElement(CampaignListTable, {
      campaigns: mockCampaigns,
      onAction: () => {},
      onRetryFailed: () => {},
      onRecalculate: () => {},
    })
  )
  assert.match(tableHtml, /Q4 Dental Outreach/)
  assert.match(tableHtml, /Modern Web Design Pilot/)
  assert.match(tableHtml, /Delivery Progress/)
  assert.match(tableHtml, /sending/)
  assert.match(tableHtml, /done/)

  // ── 7. Verify CampaignEditorPanel ──
  console.log('Testing CampaignEditorPanel...')
  const mockLeads = [
    {
      id: 'lead-1',
      business_name: 'Apex Dental Care',
      email: 'contact@apexdental.com',
      website: 'https://apexdental.com',
      email_verification_status: 'valid',
      email_business_association_status: 'matched',
      is_quarantined: false,
      audit_status: 'done',
    },
    {
      id: 'lead-2',
      business_name: 'City Auto Repair',
      email: 'cityauto@gmail.com',
      website: '',
      email_verification_status: 'valid',
      email_business_association_status: 'approved',
      is_quarantined: false,
    },
  ]
  const mockSegments = {
    generic_first_contact: {
      name: 'Generic First Contact',
      description: 'Professional, neutral outreach',
      subject: 'Hello {business_name}',
      template: 'Hi {business_name}, checking your presence.',
      requires_audit: false,
    },
  }

  const editorHtml = renderToStaticMarkup(
    React.createElement(CampaignEditorPanel, {
      leads: mockLeads,
      segments: mockSegments,
      onClose: () => {},
      onCreate: () => {},
    })
  )
  assert.match(editorHtml, /Create Segmented Outreach Campaign/)
  assert.match(editorHtml, /Campaign Name/)
  assert.match(editorHtml, /Subject Line Template/)
  assert.match(editorHtml, /Outreach Body Template/)
  assert.match(editorHtml, /Apex Dental Care/)
  assert.match(editorHtml, /Audience Eligibility Breakdown/)

  // ── 8. Verify TestEmailModal ──
  console.log('Testing TestEmailModal...')
  const testEmailHtml = renderToStaticMarkup(
    React.createElement(TestEmailModal, {
      isOpen: true,
      onClose: () => {},
      leads: mockLeads,
      segments: mockSegments,
    })
  )
  assert.match(testEmailHtml, /Send Test Outreach Preview/)
  assert.match(testEmailHtml, /Deliver Preview To/)
  assert.match(testEmailHtml, /Apex Dental Care/)

  // ── 9. Verify InboxSkeleton ──
  console.log('Testing InboxSkeleton...')
  const inboxSkelHtml = renderToStaticMarkup(React.createElement(InboxSkeleton))
  assert.match(inboxSkelHtml, /animate-pulse/)

  // ── 10. Verify InboxKpiCards ──
  console.log('Testing InboxKpiCards...')
  const mockReplyStats = {
    converted: 12,
    soft_bounce: 3,
    deleted_today: 7,
  }
  const inboxKpiHtml = renderToStaticMarkup(
    React.createElement(InboxKpiCards, {
      stats: mockReplyStats,
      lastSynced: new Date('2026-10-21T10:30:00Z'),
    })
  )
  assert.match(inboxKpiHtml, /Converted Leads/)
  assert.match(inboxKpiHtml, /12/)
  assert.match(inboxKpiHtml, /Soft Bounces \(OOO\)/)
  assert.match(inboxKpiHtml, /3/)
  assert.match(inboxKpiHtml, /Suppressed &amp; Purged Today/)
  assert.match(inboxKpiHtml, /7/)
  assert.match(inboxKpiHtml, /Hostinger SSL/)

  // ── 11. Verify ConvertedLeadsTable ──
  console.log('Testing ConvertedLeadsTable...')
  const mockConverted = [
    {
      id: 'lead-conv-1',
      business_name: 'Metro Dental Clinic',
      email: 'drsmith@metrodental.com',
      website: 'https://metrodental.com',
      reply_snippet: 'Yes, please send me the redesign proposal and pricing details.',
      status: 'converted',
      reply_type: 'positive',
      replied_at: '2026-10-21T09:15:00Z',
    },
  ]
  const convTableHtml = renderToStaticMarkup(
    React.createElement(
      MemoryRouter,
      null,
      React.createElement(ConvertedLeadsTable, {
        leads: mockConverted,
        total: 1,
        page: 1,
        pageSize: 25,
        setPage: () => {},
        onPreview: () => {},
        onCompose: () => {},
        onReclassify: () => {},
        onDelete: () => {},
      })
    )
  )
  assert.match(convTableHtml, /Metro Dental Clinic/)
  assert.match(convTableHtml, /POSITIVE REPLY/)
  assert.match(convTableHtml, /drsmith@metrodental\.com/)
  assert.match(convTableHtml, /Yes, please send me the redesign proposal/)
  assert.match(convTableHtml, /Compose Email 2/)

  // ── 12. Verify AllRepliesTable ──
  console.log('Testing AllRepliesTable...')
  const mockAllReplies = [
    ...mockConverted,
    {
      id: 'lead-repl-2',
      business_name: 'Downtown Law Firm',
      email: 'info@downtownlaw.com',
      website: 'https://downtownlaw.com',
      reply_snippet: 'I am currently out of the office until next Monday.',
      status: 'emailed',
      reply_type: 'soft_bounce',
      replied_at: '2026-10-21T08:00:00Z',
    },
  ]
  const allRepliesHtml = renderToStaticMarkup(
    React.createElement(AllRepliesTable, {
      replies: mockAllReplies,
      total: 2,
      onPreview: () => {},
      onCompose: () => {},
      onReclassify: () => {},
      onDelete: () => {},
    })
  )
  assert.match(allRepliesHtml, /Metro Dental Clinic/)
  assert.match(allRepliesHtml, /Downtown Law Firm/)
  assert.match(allRepliesHtml, /Out of Office/)
  assert.match(allRepliesHtml, /Positive \(YES\)/)
  assert.match(allRepliesHtml, /Compliance &amp; Suppression/)

  // ── 13. Verify ReplyDetailModal ──
  console.log('Testing ReplyDetailModal...')
  const replyModalHtml = renderToStaticMarkup(
    React.createElement(ReplyDetailModal, {
      lead: mockConverted[0],
      onClose: () => {},
      onReclassify: () => {},
      reclassifying: false,
    })
  )
  assert.match(replyModalHtml, /Metro Dental Clinic/)
  assert.match(replyModalHtml, /Positive \(YES \/ Interested\)/)
  assert.match(replyModalHtml, /Yes, please send me the redesign proposal/)
  assert.match(replyModalHtml, /Move to Other/)

  // ── 14. Verify Email2ComposeModal ──
  console.log('Testing Email2ComposeModal...')
  const email2Html = renderToStaticMarkup(
    React.createElement(Email2ComposeModal, {
      lead: mockConverted[0],
      onClose: () => {},
      onSent: () => {},
    })
  )
  assert.match(email2Html, /Compose Email 2 Proposal/)
  assert.match(email2Html, /Metro Dental Clinic/)
  assert.match(email2Html, /Visual Preview/)
  assert.match(email2Html, /Edit HTML Source/)

  // ── 15. Verify InboxSyncPanel ──
  console.log('Testing InboxSyncPanel...')
  const mockSyncResult = {
    fetched: 25,
    positive: 3,
    deleted: 4,
    soft_bounce: 2,
    other: 16,
    errors: 0,
  }
  const syncPanelHtml = renderToStaticMarkup(
    React.createElement(InboxSyncPanel, {
      onSync: () => {},
      syncing: false,
      lastSynced: new Date('2026-10-21T10:00:00Z'),
      syncResult: mockSyncResult,
    })
  )
  assert.match(syncPanelHtml, /Hostinger IMAP Inbox Synchronization/)
  assert.match(syncPanelHtml, /imap\.hostinger\.com:993/)
  assert.match(syncPanelHtml, /Sync Inbox Now/)
  assert.match(syncPanelHtml, /Emails Fetched/)
  assert.match(syncPanelHtml, /Newly Converted/)
  assert.match(syncPanelHtml, /Suppressed \/ Purged/)
  assert.match(syncPanelHtml, /Automated Reply Classification &amp; Suppression Pipeline/)

  console.log('ALL PHASE 4C CAMPAIGNS & INBOX UI COMPONENTS PASSED SSR VERIFICATION SUCCESSFULLY!')
} finally {
  await vite.close()
}
