#!/usr/bin/env python3
"""
TEBSolutions master email template generator + linter.

How it works
- 10 niche-agnostic segment templates (SEGMENTS) contain <<slots>>.
- Each niche (NICHES) only fills 7 slots: plural, people, need, gain, loss, action, trust.
  This enforces the rule: adjust ONLY pain point, outcome, trust signal per niche.
- Platform {tokens} are NEVER substituted here.
- lint() fails the build if any rule is broken.

Usage:  python3 template_generator.py <output_dir>
To add niches (Batch 2/3): append dicts to NICHES, re-run, fix any lint errors.
"""
import json, re, sys
from pathlib import Path

VERSION = "1.0"

ALLOWED_TOKENS = {
    "business_name", "website", "domain", "audit_summary", "audit_findings",
    "audit_recommendations", "opportunity_summary", "proposal_summary",
    "suggested_service", "sender_name", "company_name", "company_website",
}

SLOTS = ["plural", "people", "need", "gain", "loss", "action", "trust"]

# ---------------------------------------------------------------- SEGMENTS
SEGMENTS = [
    dict(n=1, key="NO_WEBSITE_DESIGN", audit=False, anchor="business_name",
         subject="{business_name} \u2014 get online",
         alts=["Getting {business_name} online", "A website for {business_name}"],
         preview="No website found for {business_name}. Here's how we can help.",
         body="""Hello, team at {business_name},

I was searching for {business_name} online and noticed that **there is no active website** for your business.

Without a dedicated website, <<people>> searching for <<need>> may struggle to find you, which can mean <<loss>>.

At {company_name}, we build modern websites for <<plural>> that bring in <<gain>> via WhatsApp, phone, and enquiry form, with room for your <<trust>>.

### Every website we build includes:
- **Mobile-ready design** \u2014 matched to your services and branding
- **Direct enquiry capture** \u2014 one-tap WhatsApp, phone, and contact forms
- **Local search discoverability** \u2014 so nearby <<people>> find you first

If you are reviewing your online presence, reply here and I would be glad to share a few examples and a tailored quotation."""),

    dict(n=2, key="BROKEN_WEBSITE_REPAIR", audit=True, anchor="domain",
         subject="Issue found on {domain}",
         alts=["{domain} is unreachable", "{domain} error \u2014 quick note"],
         preview="{domain} has a technical error. Here's what we found.",
         body="""Hello, team at {business_name},

While reviewing <<plural>> in your area, I noticed that **{domain} is currently encountering a technical issue** that prevents visitors from reaching your site:

### Identified Technical Issue:
{audit_findings}

When a website is unreachable, <<people>> looking for <<need>> cannot find your contact details or services, which can mean <<loss>>.

At {company_name}, we diagnose and restore broken websites for <<plural>>. *If your team is already working on a fix, please disregard this note.* Otherwise, reply here and we can run a no-obligation diagnostic."""),

    dict(n=3, key="OUTDATED_WEBSITE_MODERNIZATION", audit=True, anchor="domain",
         subject="Mobile review: {domain}",
         alts=["Mobile gaps on {domain}", "{domain} mobile check"],
         preview="{domain} has mobile gaps that may affect enquiries. Audit inside.",
         body="""Hello, team at {business_name},

I reviewed {domain} and found several areas where the visitor experience falls short, *particularly on mobile devices*:

### Mobile & Usability Findings:
{audit_findings}

### Recommended Modernisation:
{audit_recommendations}

Many <<people>> search for <<need>> on their phones. A site that does not load well on mobile can mean <<loss>> before a visitor reads about your services.

Would a brief call this week work? I am happy to walk through a **tailored modernisation plan** specific to {business_name}."""),

    dict(n=4, key="VALID_WEBSITE_SEO", audit=True, anchor="domain",
         subject="SEO findings for {domain}",
         alts=["Technical SEO: {domain}", "Search gaps on {domain}"],
         preview="Technical SEO gaps on {domain} that may limit your visibility.",
         body="""Hello, team at {business_name},

We ran a technical audit of {domain} and identified specific gaps that may be reducing how often {business_name} appears when <<people>> search for <<need>>:

### Technical SEO Audit:
{audit_findings}

### Recommended Actions:
{audit_recommendations}

Fixing these technical foundations helps search engines index your pages accurately, making it much easier for <<people>> to find {business_name}, which supports **<<gain>>**.

If you would like the full report, just reply here."""),

    dict(n=5, key="VALID_WEBSITE_REDESIGN", audit=True, anchor="domain",
         subject="Design review: {domain}",
         alts=["UX notes for {domain}", "{domain} visitor experience"],
         preview="UX gaps on {domain} that may reduce enquiries. Here's what we saw.",
         body="""Hello, team at {business_name},

I reviewed {domain} and noted a few areas where the visitor experience may be reducing user trust or limiting **<<gain>>**:

### Design & User Experience Review:
{audit_findings}

### Recommended Design Enhancements:
{audit_recommendations}

A cleaner, modern layout makes it easier for <<people>> to see your <<trust>> and take the next step \u2014 whether that is calling, messaging on WhatsApp, or submitting a contact form.

If this is something your team is evaluating, reply here and I am happy to share a **quick visual walkthrough**."""),

    dict(n=6, key="VALID_WEBSITE_LINK_BUILDING", audit=True, anchor="domain",
         subject="Authority review: {domain}",
         alts=["Authority gaps: {domain}", "{domain} search authority"],
         preview="{domain} shows weak authority signals. Quick summary inside.",
         body="""Hello, team at {business_name},

We reviewed {domain} and examined how well it performs across search authority signals and verified digital references:

### Digital Authority & Citation Gaps:
{audit_findings}

### Actionable Authority Strategy:
{audit_recommendations}

Stronger citation coverage and verified business listings help {business_name} establish trust when <<people>> search for <<need>>, directly supporting **<<gain>>**.

Would you like to see a **structured plan** for improving your search authority? Reply here and I will put one together."""),

    dict(n=7, key="VALID_WEBSITE_MARKETING", audit=True, anchor="domain",
         subject="Getting more from {domain}",
         alts=["Conversion gaps: {domain}", "More enquiries: {domain}"],
         preview="{domain} has conversion gaps. Here's what may be in the way.",
         body="""Hello, team at {business_name},

I reviewed {domain} and identified several gaps between what your site communicates and what <<people>> searching for <<need>> are looking for:

### Conversion & Enquiry Audit:
{audit_findings}

### Priority Recommendations:
{audit_recommendations}

Aligning your site's messaging, call-to-action placement, and search visibility makes it far more likely that visitors will **call, WhatsApp, or <<action>>** rather than go elsewhere.

If useful, reply here and I'll share a short summary of the recommended changes."""),

    dict(n=8, key="GENERIC_FIRST_CONTACT", audit=False, anchor="domain",
         subject="Five checks for {domain}",
         alts=["{domain} website checklist", "Quick checklist: {domain}"],
         preview="Five checks I'd suggest for {domain} before your next update.",
         body="""Hello, team at {business_name},

I came across {domain} while reviewing <<plural>> in your area and wanted to share a quick checklist: *five things worth verifying before your next website update*.

### Five critical checks for <<plural>>:
\u2713 **Mobile responsiveness** \u2014 does the layout adapt cleanly to phones and tablets?
\u2713 **Page load speed** \u2014 does the site load quickly on a mobile connection?
\u2713 **Direct contact pathways** \u2014 can a visitor call, WhatsApp, or <<action>> in one tap?
\u2713 **Search visibility foundations** \u2014 does the homepage have clear title tags and local keyword signals?
\u2713 **Verified trust elements** \u2014 does the site prominently showcase your <<trust>>?

These factors directly influence <<gain>>.

If {business_name} would benefit from a full audit covering all of the above *(with no obligation)*, just reply and I'll get one prepared."""),

    dict(n=9, key="AUDIT_FOLLOW_UP", audit=True, anchor="domain",
         subject="Following up: {domain}",
         alts=["{domain} audit follow-up", "Still relevant? {domain}"],
         preview="Following up on {domain}. The audit is done; here's what we found.",
         body="""Hello, team at {business_name},

Just following up on my earlier note regarding **{domain}**.

We completed the technical review. Here is a summary of the key findings:

### Key Technical Findings:
{audit_findings}

### Recommended Next Steps:
{audit_recommendations}

Addressing these items will help {business_name} avoid *<<loss>>*.

*I'll keep this brief.* If it would help, I can put together a short summary document or jump on a **10-minute call** at your convenience."""),

    dict(n=10, key="PUBLIC_PROVIDER_DEMO", audit=False, anchor="business_name",
         subject="Website demo for {business_name}",
         alts=["Demo for {business_name}", "{business_name}: a quick demo"],
         preview="A no-obligation demo for {business_name}. Reply to arrange it.",
         body="""Hello, team at {business_name},

My name is {sender_name} from {company_name}. We help <<plural>> build or improve their digital presence: *websites, mobile experience, and local search visibility*.

I'd like to offer a brief, no-obligation demonstration of what an improved online presence could look like for {business_name}, with a focus on **<<gain>>**.

### What we typically showcase:
- **Mobile-ready design** \u2014 tailored specifically for <<plural>>
- **Direct enquiry capture** \u2014 via WhatsApp, phone, and contact form
- **Verified trust elements** \u2014 a place to display your <<trust>>

If you're open to a quick walkthrough, simply reply and I'll arrange it at a time that works for you."""),
]

# ------------------------------------------------------------------ NICHES
NICHES = [
    dict(id=1, name="Dental Clinics & Dentists",
         plural="dental clinics", people="patients", need="dental care",
         gain="appointment bookings", loss="missed appointment requests",
         action="book an appointment",
         trust="qualifications, treatment photos, and patient reviews"),
    dict(id=2, name="Medical Clinics & Hospitals",
         plural="clinics and hospitals", people="patients", need="medical care",
         gain="appointment requests", loss="missed appointment requests",
         action="request an appointment",
         trust="doctor profiles, department details, and patient reviews"),
    dict(id=3, name="Diagnostic Labs & Pathology Centres",
         plural="diagnostic labs and pathology centres", people="patients",
         need="diagnostic tests",
         gain="test bookings and sample-collection enquiries",
         loss="missed test booking enquiries", action="book a test",
         trust="accreditation details, test menus, and customer reviews"),
    dict(id=4, name="Pharmacies & Medical Stores",
         plural="pharmacies and medical stores", people="customers",
         need="medicines and health products",
         gain="product and delivery enquiries", loss="missed customer enquiries",
         action="send an enquiry",
         trust="store photos, licence details, and customer reviews"),
    dict(id=5, name="Coaching Institutes & Tuition Centres",
         plural="coaching institutes and tuition centres",
         people="students and parents", need="coaching and tuition",
         gain="admission enquiries", loss="missed admission enquiries",
         action="enquire about admission",
         trust="faculty profiles, batch details, and student reviews"),
    dict(id=6, name="Schools & Colleges",
         plural="schools and colleges", people="parents and students",
         need="admissions information",
         gain="admission enquiries", loss="missed admission enquiries",
         action="enquire about admission",
         trust="affiliation details, faculty profiles, and campus photos"),
    dict(id=7, name="Gyms & Fitness Centres",
         plural="gyms and fitness centres", people="local residents",
         need="fitness options nearby",
         gain="trial class bookings", loss="missed membership sign-ups",
         action="book a trial class",
         trust="trainer profiles, facility photos, and member reviews"),
    dict(id=8, name="Restaurants & Cafes",
         plural="restaurants and cafes", people="diners",
         need="places to eat nearby",
         gain="table reservations and takeaway orders", loss="empty tables",
         action="reserve a table",
         trust="menus, food photos, and customer reviews"),
    dict(id=9, name="Hotels & Guesthouses",
         plural="hotels and guesthouses", people="travellers",
         need="places to stay",
         gain="direct booking enquiries", loss="missed booking enquiries",
         action="request a booking",
         trust="room photos, tariff details, and guest reviews"),
    dict(id=10, name="Wedding Planners & Event Managers",
         plural="wedding planners and event managers",
         people="couples and families", need="wedding and event planning",
         gain="event enquiries", loss="missed event enquiries",
         action="request a quote",
         trust="portfolio photos, past events, and client reviews"),
    dict(id=11, name="Travel & Tourism Agencies",
         plural="travel and tourism agencies", people="travellers",
         need="holiday packages and tours",
         gain="trip enquiries", loss="missed trip enquiries",
         action="request a trip quote",
         trust="itineraries, destination photos, and traveller reviews"),
    dict(id=12, name="Salons & Spas",
         plural="salons and spas", people="clients",
         need="salon and spa services",
         gain="appointment bookings", loss="missed appointment requests",
         action="book an appointment",
         trust="service menus, work photos, and client reviews"),
    dict(id=13, name="Jewellery Stores",
         plural="jewellery stores", people="shoppers", need="jewellery",
         gain="store visits and product enquiries",
         loss="missed product enquiries", action="send an enquiry",
         trust="collection photos, hallmark details, and customer reviews"),
    dict(id=14, name="Clothing & Boutiques",
         plural="clothing stores and boutiques", people="shoppers",
         need="clothing and fashion",
         gain="store visits and order enquiries", loss="missed order enquiries",
         action="send an order enquiry",
         trust="collection photos, size guides, and customer reviews"),
    dict(id=15, name="Grocery & Retail Stores",
         plural="grocery and retail stores", people="customers",
         need="everyday essentials nearby",
         gain="order and delivery enquiries", loss="missed order enquiries",
         action="send an order enquiry",
         trust="product ranges, store photos, and customer reviews"),
    dict(id=16, name="Real Estate Agents & Property Dealers",
         plural="real estate agents and property dealers",
         people="buyers and tenants", need="properties",
         gain="property enquiries and site-visit requests",
         loss="missed property enquiries", action="request a site visit",
         trust="property listings, project photos, and client reviews"),
    dict(id=17, name="Interior Designers & Architects",
         plural="interior designers and architects", people="homeowners",
         need="design and renovation help",
         gain="project enquiries", loss="missed project enquiries",
         action="request a consultation",
         trust="project portfolios, before-and-after photos, and client reviews"),
    dict(id=18, name="Logistics & Freight Companies",
         plural="logistics and freight companies",
         people="shippers and businesses", need="freight and transport services",
         gain="shipment quote requests", loss="missed freight enquiries",
         action="request a shipment quote",
         trust="service coverage, fleet details, and client reviews"),
    dict(id=19, name="Trading & Manufacturing Companies",
         plural="trading and manufacturing companies", people="business buyers",
         need="suppliers and manufacturers",
         gain="quote requests", loss="missed business enquiries",
         action="request a quote",
         trust="product catalogues, certifications, and client references"),
    dict(id=20, name="IT & Software Companies",
         plural="IT and software companies", people="prospective clients",
         need="technology partners",
         gain="project enquiries",
         loss="losing project enquiries to firms with a stronger web presence",
         action="request a project consultation",
         trust="portfolio, case studies, and client reviews"),
    dict(id=21, name="CA & Tax Consultants",
         plural="CA firms and tax consultants",
         people="individuals and businesses", need="tax and accounting help",
         gain="consultation requests", loss="missed consultation requests",
         action="request a consultation",
         trust="service descriptions, qualifications, and contact details"),
    dict(id=22, name="Auto Garages & Car Service Centres",
         plural="auto garages and car service centres", people="car owners",
         need="car service and repairs",
         gain="service bookings", loss="missed service bookings",
         action="book a service",
         trust="service menus, workshop photos, and customer reviews"),
    dict(id=23, name="HR & Staffing Agencies",
         plural="HR and staffing agencies",
         people="employers and job seekers",
         need="hiring support and job opportunities",
         gain="hiring enquiries and candidate registrations",
         loss="missed hiring enquiries", action="send an enquiry",
         trust="service details, sectors served, and client reviews"),
    dict(id=24, name="Printing & Packaging Companies",
         plural="printing and packaging companies", people="business customers",
         need="printing and packaging suppliers",
         gain="quote requests", loss="missed quote requests",
         action="request a quote",
         trust="sample work, product range, and client reviews"),
    dict(id=25, name="Facility Management & Pest Control",
         plural="facility management and pest control companies",
         people="homeowners and businesses",
         need="facility and pest control services",
         gain="service enquiries", loss="missed service enquiries",
         action="request a service visit",
         trust="service details, licence information, and customer reviews"),
    dict(id=26, name="Furniture Stores",
         plural="furniture stores", people="shoppers", need="furniture",
         gain="store visits and product enquiries",
         loss="missed product enquiries", action="send an enquiry",
         trust="product galleries, material details, and customer reviews"),
]

# -------------------------------------------------------------------- BUILD
def fill(text, niche):
    for s in SLOTS:
        text = text.replace(f"<<{s}>>", niche[s])
    assert "<<" not in text, "unfilled slot"
    return text

def build(niches=None):
    out = []
    for niche in (niches or NICHES):
        for seg in SEGMENTS:
            out.append(dict(
                template_version=VERSION,
                niche_id=niche["id"], niche=niche["name"],
                segment_no=seg["n"], segment_key=seg["key"],
                audit_required=seg["audit"],
                subject=fill(seg["subject"], niche),
                subject_alternatives=[fill(a, niche) for a in seg["alts"]],
                preview=fill(seg["preview"], niche),
                body=fill(seg["body"], niche),
            ))
    return out

# --------------------------------------------------------------------- LINT
BANNED = [r"\bfree\b", r"\bguaranteed?\b", r"\bact now\b", r"\burgent\b",
          r"\bclick here\b", r"\bmake money\b", r"\brisk[- ]free\b",
          r"\bspecial offer\b", r"\bsale\b", r"\blimited time\b", r"\bbuy now\b",
          r"\benclosed\b", r"\bmost\b", r"above (your )?competitors",
          r"!!", r"\bunsubscribe\b", r"\bnumber one\b", r"\bbest in\b"]
SIGNOFF = re.compile(r"^(best regards|regards|warm regards|thanks|thank you|sincerely|cheers)\b", re.I | re.M)
DOMAIN_SAMPLE = "x" * 25 + ".in"          # 28 chars worst case
NAME_SAMPLE = "N" * 33                       # 33 chars worst case
SUBJ_MAX, PREV_MAX, PARA_MAX = 50, 90, 280

def sample(text):
    return text.replace("{domain}", DOMAIN_SAMPLE).replace("{business_name}", NAME_SAMPLE)

def lint(items):
    errs = []
    for t in items:
        tag = f"[niche {t['niche_id']} / seg {t['segment_no']}]"
        n = t["segment_no"]
        subs = [t["subject"]] + t["subject_alternatives"]
        for s in subs:
            if len(sample(s)) > SUBJ_MAX: errs.append(f"{tag} subject too long: {s}")
            if s.isupper(): errs.append(f"{tag} all-caps subject")
            if "!" in s: errs.append(f"{tag} exclamation in subject")
            anchor = "{business_name}" if n in (1, 10) else "{domain}"
            if n in (1, 10) and "{domain}" in s: errs.append(f"{tag} {{domain}} in subject: {s}")
            if n not in (1, 10) and "{domain}" not in s: errs.append(f"{tag} missing {{domain}} in subject: {s}")
        if len(sample(t["preview"])) > PREV_MAX: errs.append(f"{tag} preview too long ({len(sample(t['preview']))})")
        if n in (1, 10) and "{domain}" in t["preview"] + t["body"]: errs.append(f"{tag} {{domain}} used in seg 1/10")
        body = t["body"]
        if not body.startswith("Hello, team at {business_name},"): errs.append(f"{tag} greeting")
        if SIGNOFF.search(body): errs.append(f"{tag} sign-off in body")
        for pat in BANNED:
            for field, txt in (("body", body), ("preview", t["preview"]), ("subject", " | ".join(subs))):
                if re.search(pat, txt, re.I): errs.append(f"{tag} banned '{pat}' in {field}")
        for tok in re.findall(r"\{(\w+)\}", body + t["preview"] + " ".join(subs)):
            if tok not in ALLOWED_TOKENS: errs.append(f"{tag} unknown token {{{tok}}}")
        if t["audit_required"] and "{audit_findings}" not in body and n != 8:
            errs.append(f"{tag} audit segment missing {{audit_findings}}")
        if n in (3, 4, 5, 6, 7, 9) and "{audit_recommendations}" not in body:
            errs.append(f"{tag} missing {{audit_recommendations}}")
        if len(re.findall(r"\breply\b", body, re.I)) > 1: errs.append(f"{tag} more than one 'reply' CTA")
        for block in body.split("\n\n"):
            lines = block.split("\n")
            bullets = [l for l in lines if l.startswith(("- ", "\u2713 "))]
            if bullets and len(bullets) < 3: errs.append(f"{tag} bullet list <3 items")
            if not bullets and len(block) > PARA_MAX and "{audit_" not in block:
                errs.append(f"{tag} paragraph too long ({len(block)})")
        if "attach" in body.lower(): errs.append(f"{tag} mentions attachment")
    return errs

def to_markdown(items, label="Batch 1"):
    lines = [f"# TEBSolutions Master Template Library \u2014 {label}", ""]
    cur = None
    for t in items:
        if t["niche"] != cur:
            cur = t["niche"]
            lines += ["---", f"NICHE: {cur}", ""]
        lines += [f"SEGMENT {t['segment_no']} \u2014 {t['segment_key']}",
                  f"Subject: {t['subject']}", f"Preview: {t['preview']}",
                  "Body:", t["body"], ""]
    return "\n".join(lines)

if __name__ == "__main__":
    # usage: template_generator.py <outdir> <label e.g. batch2> <id range e.g. 8-15>
    outdir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    label = sys.argv[2] if len(sys.argv) > 2 else "batch1"
    lo, hi = map(int, (sys.argv[3] if len(sys.argv) > 3 else "1-7").split("-"))
    outdir.mkdir(parents=True, exist_ok=True)
    items = build([n for n in NICHES if lo <= n["id"] <= hi])
    errs = lint(items)
    print(f"{len(items)} templates built, {len(errs)} lint errors")
    for e in errs: print("  -", e)
    if errs: sys.exit(1)
    (outdir / f"templates_{label}.json").write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    pretty = "Complete Library (all niches)" if label == "all" else label.replace("batch", "Batch ")
    (outdir / f"templates_{label}.md").write_text(to_markdown(items, pretty), encoding="utf-8")
    print("written to", outdir)
