"""
Comprehensive validator for Batches 1, 2, and 3 implementation.
Checks all 260 templates, all 780 subject rotations, niche router,
fail-closed guards, DB models, and live DB columns.
"""
import sys
import json
import asyncio
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

def verify_templates():
    print("=" * 60)
    print("1. VERIFYING ALL 260 TEMPLATES IN templates_all.json")
    print("=" * 60)
    
    from app.services.niche_template_service import (
        NicheTemplateLibrary, render_niche_template,
        AUDIT_REQUIRED_SEGMENTS, NO_DOMAIN_SEGMENTS, ALLOWED_TOKENS,
        NicheTemplateError
    )

    json_path = backend_dir / "app" / "templates_all.json"
    assert json_path.exists(), f"Missing {json_path}"

    with open(json_path, encoding="utf-8") as f:
        templates = json.load(f)

    assert len(templates) == 260, f"Expected 260 templates, got {len(templates)}"
    print(f"  [OK] Found exactly {len(templates)} templates in templates_all.json")

    # Check distribution: 26 niches x 10 segments
    niche_segments = {}
    for idx, t in enumerate(templates):
        nid = t.get("niche_id")
        sno = t.get("segment_no")
        assert 1 <= nid <= 26, f"Template {idx}: invalid niche_id {nid}"
        assert 1 <= sno <= 10, f"Template {idx}: invalid segment_no {sno}"
        
        pair = (nid, sno)
        assert pair not in niche_segments, f"Duplicate template for niche {nid}, segment {sno}"
        niche_segments[pair] = t

        # Verify required keys
        for key in ["niche_id", "niche", "segment_no", "segment_key", "subject", "subject_alternatives", "body", "preview", "template_version"]:
            assert key in t and t[key] is not None, f"Template ({nid}, {sno}) missing {key}"

        # Verify subject alternatives count
        alts = t["subject_alternatives"]
        assert isinstance(alts, list) and len(alts) == 2, f"Template ({nid}, {sno}) expected 2 subject alternatives, got {len(alts)}"

        # Verify lengths
        assert len(t["subject"]) <= 50, f"Template ({nid}, {sno}) subject > 50 chars: {len(t['subject'])} ('{t['subject']}')"
        for i, alt in enumerate(alts):
            assert len(alt) <= 50, f"Template ({nid}, {sno}) alt {i} > 50 chars: {len(alt)} ('{alt}')"
        assert len(t["preview"]) <= 90, f"Template ({nid}, {sno}) preview > 90 chars: {len(t['preview'])}"

        # Verify forbidden domain token
        if sno in NO_DOMAIN_SEGMENTS:
            all_text = f"{t['subject']} {' '.join(alts)} {t['body']}"
            assert "{domain}" not in all_text, f"Template ({nid}, {sno}) contains forbidden {{domain}}"

    assert len(niche_segments) == 260
    print("  [OK] All 26 niches x 10 segments verified structurally (lengths, alternatives, forbidden tokens)")

    # Test full rendering across all 780 rotations
    lib = NicheTemplateLibrary.get_instance()
    context = {
        "business_name": "Acme Services",
        "domain": "acmeservices.in",
        "website": "https://acmeservices.in",
        "audit_summary": "Site has 3 major issues",
        "audit_findings": "• Slow loading times (4.2s)\n• Missing meta descriptions on key pages\n• Mobile viewport improperly configured",
        "audit_recommendations": "• Optimize images and script delivery\n• Add meta tags\n• Adjust responsive CSS",
        "opportunity_summary": "Modernize infrastructure for improved conversions",
        "proposal_summary": "Comprehensive technical fix and performance optimization",
        "suggested_service": "Full Technical Modernization",
        "sender_name": "Alex Vance",
        "company_name": "Apex Digital",
        "company_website": "https://apexdigital.com",
        "city": "Dehradun",
        "niche_label": "Dental Clinic",
        "finding_count": "3",
        "contact_name": "Dr. Sharma",
    }

    render_count = 0
    for nid in range(1, 27):
        for sno in range(1, 11):
            subjects_seen = set()
            for rotation in range(3):
                rendered = render_niche_template(nid, sno, context)
                render_count += 1
                assert "{" not in rendered["subject"], f"Unresolved token in subject ({nid}, {sno}): {rendered['subject']}"
                assert "{" not in rendered["body"], f"Unresolved token in body ({nid}, {sno}): {rendered['body']}"
                subjects_seen.add(rendered["subject"])

            assert len(subjects_seen) == 3, f"Expected 3 distinct rotated subjects for ({nid}, {sno}), got {len(subjects_seen)}"

    print(f"  [OK] Successfully rendered {render_count} template variations (all 260 templates x 3 subject rotations)")

    # Verify fail-closed checks
    print("  Testing fail-closed rules...")
    # Missing audit findings on segment 4
    try:
        render_niche_template(1, 4, {"business_name": "Foo", "domain": "foo.com", "audit_findings": ""})
        assert False, "Should have failed closed on empty audit_findings for segment 4"
    except NicheTemplateError:
        pass

    # Unresolved token
    try:
        render_niche_template(1, 1, {})  # missing business_name
        assert False, "Should have failed closed on missing business_name"
    except NicheTemplateError:
        pass

    print("  [OK] Fail-closed rules validated.")

def verify_niche_router():
    print("\n" + "=" * 60)
    print("2. VERIFYING NICHE ROUTER AND NAME CLEANING")
    print("=" * 60)
    from app.services.niche_router import (
        classify_lead_niche, clean_business_name, is_social_domain, clean_domain,
        niche_name_from_id
    )

    # 1. Name cleaner
    raw = "Sharma Dental Clinic | Best Dentist in Dehradun | Implants Pvt Ltd"
    cleaned = clean_business_name(raw)
    assert cleaned == "Sharma Dental Clinic", f"Got: '{cleaned}'"
    print(f"  [OK] Cleaned name: '{raw}' -> '{cleaned}'")

    # 2. Social domains
    assert is_social_domain("https://www.facebook.com/sharmadental")
    assert is_social_domain("https://www.justdial.com/Dehradun/dentist")
    assert is_social_domain("indiamart.com/sharmadental")
    assert not is_social_domain("https://sharmadental.com")
    print("  [OK] Social / directory domain detection verified")

    # 3. Clean domain
    assert clean_domain("https://www.example.com/about?x=1") == "example.com"
    assert clean_domain("http://sub.test.in/") == "sub.test.in"
    print("  [OK] Domain cleaning verified")

    # 4. Keyword classification across test cases
    test_cases = [
        ("Sharma Dental Clinic", 1, "Dental"),
        ("City Care Multi Speciality Hospital", 2, "Medical"),
        ("Apex Diagnostic & Pathology Lab", 3, "Diagnostic"),
        ("Apollo Pharmacy Store", 4, "Pharmacies"),
        ("Bright Future Coaching & Tuition Classes", 5, "Coaching"),
        ("Delhi Public School & Campus", 6, "Schools"),
        ("Elite Fitness Gym & Crossfit", 7, "Gyms"),
        ("Tandoori Nights Restaurant & Cafe", 8, "Restaurants"),
        ("Hotel Grand View & Resort", 9, "Hotels"),
        ("Royal Heritage Wedding Planner & Event Hall", 10, "Wedding"),
        ("Wanderlust Travel & Tour Agency", 11, "Travel"),
        ("Radiance Beauty Salon & Spa", 12, "Salons"),
        ("Shreeji Jewellers & Diamond Gold", 13, "Jewellery"),
        ("Fashion Trends Clothing Boutique", 14, "Clothing"),
        ("Fresh Mart Supermarket & Grocery Store", 15, "Grocery"),
        ("Green Valley Real Estate & Property Dealers", 16, "Real Estate"),
        ("Prime Interiors & Architectural Design", 17, "Interior"),
        ("Speedy Cargo & Freight Logistics", 18, "Logistics"),
        ("Hindustan Trading Company & Manufacturers", 19, "Trading"),
        ("Silicon Valley Software & Technology Solutions", 20, "Software"),
        ("Malhotra & Associates Chartered Accountants & Tax Consultants", 21, "CA"),
        ("Car Care Multi Brand Auto Garage", 22, "Auto"),
        ("National Staffing & HR Recruitment Agency", 23, "HR"),
        ("Apex Offset Printing & Packaging Solutions", 24, "Printing"),
        ("SafeHome Pest Control & Facility Management", 25, "Facility"),
        ("Royal Teak Furniture Store & Modular Kitchen", 26, "Furniture"),
    ]

    for name, expected_id, label_sub in test_cases:
        nid, kw, conf = classify_lead_niche(name)
        assert nid == expected_id, f"Classified '{name}' as niche {nid} ({niche_name_from_id(nid)}), expected {expected_id}"
        assert conf > 0, f"Zero confidence for '{name}'"
        assert label_sub.lower() in niche_name_from_id(nid).lower()
        print(f"  [OK] Niche {nid:2d} ({niche_name_from_id(nid):<30}): '{name}' -> kw='{kw}', score={conf}")

async def verify_database():
    print("\n" + "=" * 60)
    print("3. VERIFYING DATABASE SCHEMA AND MODELS")
    print("=" * 60)
    from app.database import AsyncSessionLocal
    from sqlalchemy import text
    from app.models import Lead, SuppressionList

    async with AsyncSessionLocal() as session:
        # Check columns in leads table
        result = await session.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'leads' 
            AND column_name IN (
                'niche_id', 'niche_keyword', 'niche_confidence', 'niche_locked',
                'sequence_touch_count', 'last_sequence_touch_at', 'sequence_paused_until',
                'has_received_demo', 'is_suppressed', 'suppressed_at', 'suppression_reason'
            );
        """))
        cols = {row[0]: row[1] for row in result.fetchall()}
        expected_cols = [
            'niche_id', 'niche_keyword', 'niche_confidence', 'niche_locked',
            'sequence_touch_count', 'last_sequence_touch_at', 'sequence_paused_until',
            'has_received_demo', 'is_suppressed', 'suppressed_at', 'suppression_reason'
        ]
        for col in expected_cols:
            assert col in cols, f"Missing column '{col}' in leads table"
            print(f"  [OK] leads.{col} ({cols[col]})")

        # Check suppression_list table
        result = await session.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'suppression_list';
        """))
        supp_cols = {row[0]: row[1] for row in result.fetchall()}
        assert "email" in supp_cols, "Missing 'email' in suppression_list table"
        assert "reason" in supp_cols, "Missing 'reason' in suppression_list table"
        print(f"  [OK] suppression_list table verified with {len(supp_cols)} columns")

async def main():
    verify_templates()
    verify_niche_router()
    await verify_database()
    print("\n" + "=" * 60)
    print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY WITH ZERO ERRORS!")
    print("=" * 60)

if __name__ == "__main__":
    if sys.platform == "win32":
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
