import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const read = (relativePath) => readFileSync(resolve(root, relativePath), 'utf8')
const requireText = (source, expected, label) => {
  if (!source.includes(expected)) throw new Error(`${label}: missing ${expected}`)
}

const verificationApi = read('../backend/app/routers/email_verification.py')
const reviewApi = read('../backend/app/routers/email_review.py')
const verificationUi = read('src/components/EmailVerificationAudit.jsx')
const reviewUi = read('src/pages/EmailReview.jsx')
const activityUi = read('src/pages/ActivityLog.jsx')

for (const field of ['"association_status"', '"association_reason"', '"email_source_url"', '"email_domain_match"']) {
  requireText(verificationApi, field, 'verification API payload')
}
for (const expected of ['ASSOCIATION_CONFIG', 'Business Association', 'Evidence source:', 'matched or approved']) {
  requireText(verificationUi, expected, 'verification UI')
}
for (const expected of ['Email Verification & Mismatch Review', 'does not approve business association', 'fail-closed checks']) {
  requireText(reviewUi, expected, 'mismatch review UI')
}
for (const expected of ['"verification_status"', '"association_status"', '"quarantine_reason"', '"reply_type"']) {
  requireText(reviewApi, expected, 'mismatch review API payload')
}
for (const expected of ['Search event, message, or lead ID', 'Event category', 'Activity events could not be loaded', 'Timestamp unavailable']) {
  requireText(activityUi, expected, 'activity log UI')
}

console.log('Phase 4D operational UI source checks passed.')
