"""
Email validation constants and domain classification utilities.

Data Source & Provenance:
- DISPOSABLE_DOMAINS: Curated blocklist of disposable / temporary / throwaway email service domains,
  compiled from open-source references including micke/valid_email2, AfterShip/email-verifier,
  and disposable-email-domains (Public Domain / MIT licensed).
- Limitations: Disposable email providers constantly register new domains. This blocklist serves
  as a fast, zero-latency layer 3 defense, complemented by MX record and domain age checks.
- Update Process: To update the list, new verified throwaway domains can be appended to the
  frozenset or loaded from an external maintained list in future releases.
"""

from __future__ import annotations
import re

# Popular email provider domains
POPULAR_DOMAINS: frozenset[str] = frozenset({
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "yahoo.co.in",
    "yahoo.in",
    "yahoo.co.uk",
    "yahoo.ca",
    "yahoo.fr",
    "yahoo.de",
    "ymail.com",
    "rocketmail.com",
    "hotmail.com",
    "hotmail.co.uk",
    "hotmail.fr",
    "outlook.com",
    "live.com",
    "msn.com",
    "icloud.com",
    "me.com",
    "mac.com",
    "aol.com",
    "zoho.com",
    "protonmail.com",
    "proton.me",
    "mail.com",
    "gmx.com",
    "gmx.net",
    "yandex.com",
    "yandex.ru",
    "fastmail.com",
    "tutanota.com",
    "rediffmail.com",
    "inbox.com",
    "email.com",
    "qq.com",
    "163.com",
    "126.com",
})

# Canonical public email providers (webmail / consumer email services)
PUBLIC_EMAIL_PROVIDERS: frozenset[str] = POPULAR_DOMAINS

# Direct map for common typos observed in lead intake and manual data entry
COMMON_TYPO_MAP: dict[str, str] = {
    # Gmail typos
    "gmial.com": "gmail.com",
    "gamil.com": "gmail.com",
    "gmai.com": "gmail.com",
    "gmaill.com": "gmail.com",
    "gmaik.com": "gmail.com",
    "gmajl.com": "gmail.com",
    "gmal.com": "gmail.com",
    "gmeil.com": "gmail.com",
    "gmail.co": "gmail.com",
    "gmail.cm": "gmail.com",
    "gmail.con": "gmail.com",
    "gmaill.con": "gmail.com",
    "gmaio.com": "gmail.com",
    "googlemail.con": "googlemail.com",

    # Yahoo typos
    "yaho.com": "yahoo.com",
    "yahooo.com": "yahoo.com",
    "yahu.com": "yahoo.com",
    "yahou.com": "yahoo.com",
    "yhaoo.com": "yahoo.com",
    "yahoo.co": "yahoo.com",
    "yahoo.con": "yahoo.com",

    # Hotmail typos
    "hotmial.com": "hotmail.com",
    "hotmaill.com": "hotmail.com",
    "hotmil.com": "hotmail.com",
    "hotmai.com": "hotmail.com",
    "hotmaik.com": "hotmail.com",
    "hotmale.com": "hotmail.com",
    "hotmail.con": "hotmail.com",
    "hotmail.co": "hotmail.com",

    # Outlook / Live / MSN typos
    "outlok.com": "outlook.com",
    "outloo.com": "outlook.com",
    "outllok.com": "outlook.com",
    "outlool.com": "outlook.com",
    "outlock.com": "outlook.com",
    "outlook.con": "outlook.com",
    "outlook.co": "outlook.com",
    "liv.com": "live.com",
    "ms.com": "msn.com",

    # iCloud / Apple typos
    "icld.com": "icloud.com",
    "iclud.com": "icloud.com",
    "icoud.com": "icloud.com",
    "icloud.con": "icloud.com",

    # Proton typos
    "protonmal.com": "protonmail.com",
    "protonmial.com": "protonmail.com",
    "protonmaill.com": "protonmail.com",
}

# Curated list of disposable, temporary, and throwaway domains
_DISPOSABLE_DOMAINS_TUPLE: tuple[str, ...] = (
    "0-mail.com",
    "0815.ru",
    "0clickemail.com",
    "10minutemail.be",
    "10minutemail.cf",
    "10minutemail.co.uk",
    "10minutemail.co.za",
    "10minutemail.com",
    "10minutemail.de",
    "10minutemail.net",
    "10minutemail.nl",
    "10minutemail.org",
    "10minutemail.pro",
    "10minutemailbox.com",
    "123-m.com",
    "12hourmail.com",
    "1pad.de",
    "20email.eu",
    "20minutemail.com",
    "20minutemail.it",
    "2prong.com",
    "30minutemail.com",
    "33mail.com",
    "3d-painting.com",
    "4warding.com",
    "4warding.net",
    "4warding.org",
    "5mail.org",
    "60minutemail.com",
    "675hosting.com",
    "675hosting.net",
    "675hosting.org",
    "6url.com",
    "75hosting.com",
    "75hosting.net",
    "75hosting.org",
    "7tags.com",
    "9ox.net",
    "a-bc.net",
    "afrobacon.com",
    "agedmail.com",
    "ajaxapp.net",
    "amilearth.com",
    "amiri.net",
    "amiriindustries.com",
    "anappthat.com",
    "anonaddy.com",
    "anonaddy.me",
    "anonbox.net",
    "anonymbox.com",
    "antichef.com",
    "antichef.net",
    "antispam.de",
    "armyspy.com",
    "baxomale.ht.cx",
    "beefmilk.com",
    "binkmail.com",
    "bio-muesli.net",
    "bobmail.info",
    "bodhi.lawlita.com",
    "bofthew.com",
    "brefmail.com",
    "brennendesreich.de",
    "broadbandninja.com",
    "bsnow.net",
    "bugmenot.com",
    "bumpymail.com",
    "bund.us",
    "burnmail.in",
    "burnermail.io",
    "burnthespam.info",
    "cachedot.net",
    "camerapro.net",
    "cannypack.com",
    "cantv.net",
    "care2.com",
    "casualdx.com",
    "centermail.com",
    "centermail.net",
    "chogmail.com",
    "chong-soft.com",
    "clrmail.com",
    "cmail.club",
    "cmail.com",
    "cobinhood.com",
    "cock.li",
    "cool.fr.nf",
    "correo.blogos.net",
    "cosmorph.com",
    "courrieltemporaire.com",
    "crapmail.org",
    "crazymailing.com",
    "crossroads.nu",
    "cuoly.com",
    "curryjunkie.com",
    "cust.in",
    "cuvox.de",
    "dacoolest.com",
    "dandikmail.com",
    "dayrep.com",
    "deadaddress.com",
    "deadspam.com",
    "delikatesy.pl",
    "despam.it",
    "devnullmail.com",
    "dfgh.net",
    "digitalsanctuary.com",
    "discard.email",
    "discardbox.email",
    "discardmail.com",
    "discardmail.de",
    "disposable-email.ml",
    "disposable.com",
    "disposableaddress.com",
    "disposableemailaddresses.com",
    "disposableinbox.com",
    "disposablemail.com",
    "disposeamail.com",
    "disposemail.com",
    "dispostable.com",
    "dmcontact.net",
    "dodgeit.com",
    "dodgit.com",
    "donemail.ru",
    "dontreg.com",
    "dontsendmespam.de",
    "drdrb.net",
    "drope.ml",
    "dropmail.me",
    "duetomorrow.org",
    "dump-email.info",
    "dumpmail.de",
    "dumpyemail.com",
    "e-mail.am",
    "e4ward.com",
    "easytrashmail.com",
    "einrot.com",
    "email-fake.com",
    "email60.com",
    "emailage.com",
    "emaildienst.de",
    "emaildrop.io",
    "emailfake.com",
    "emailfreedom.ml",
    "emailgo.de",
    "emailias.com",
    "emailmiser.com",
    "emailproxsy.com",
    "emailsensei.com",
    "emailstash.net",
    "emailtemporanea.net",
    "emailtemporaire.fr",
    "emailthe.net",
    "emailtin.com",
    "emailto.de",
    "emailwarden.com",
    "emailx.at.tc",
    "emailxfer.com",
    "emeil.in",
    "emil.com",
    "emltmp.com",
    "emz.net",
    "enterthegame.com",
    "ephemail.net",
    "eskimo.com",
    "espritemail.com",
    "evade.im",
    "everymail.net",
    "evomail.com",
    "explodemail.com",
    "eyepaste.com",
    "ezlo.info",
    "fackme.gq",
    "fake-box.com",
    "fakeinbox.com",
    "fakemail.fr",
    "fakemailgenerator.com",
    "fakemailgenerator.net",
    "fast-email.org",
    "fastchemail.com",
    "fastinbox.com",
    "fastjunkmail.com",
    "femail.at.tc",
    "filzmail.com",
    "fivemail.de",
    "fixmail.tk",
    "flemail.ru",
    "flyspam.com",
    "forward.cat",
    "frapmail.com",
    "free-email.org",
    "freemail.ms",
    "freenet.de",
    "freerangekitten.com",
    "fromru.com",
    "front14.org",
    "fudgerub.com",
    "fux0ringduh.com",
    "garliclife.com",
    "gelbe-erdbeere.de",
    "getairmail.com",
    "getnada.com",
    "getonemail.com",
    "gettempmail.com",
    "ghostlymail.com",
    "giantmail.de",
    "girlsundertheinfluence.com",
    "gishpuppy.com",
    "gmial.com",
    "gmx.at",
    "gmx.ch",
    "goatmail.uk",
    "gowikicars.com",
    "greenkarmamail.com",
    "grr.la",
    "gsrv.co.uk",
    "guerillamail.biz",
    "guerillamail.block",
    "guerillamail.com",
    "guerillamail.de",
    "guerillamail.info",
    "guerillamail.net",
    "guerillamail.org",
    "guerrillamail.biz",
    "guerrillamail.block",
    "guerrillamail.com",
    "guerrillamail.de",
    "guerrillamail.info",
    "guerrillamail.net",
    "guerrillamail.org",
    "guerrillamailblock.com",
    "gustr.com",
    "h8s.org",
    "haltospam.com",
    "harakirimail.com",
    "hartbot.de",
    "hazelnutchocolate.com",
    "hds-email.cf",
    "hellokitty.com",
    "herp.in",
    "hidemail.de",
    "hmamail.com",
    "hopto.org",
    "hot-mail.cf",
    "hot-mail.gq",
    "hot-mail.ml",
    "hot-mail.tk",
    "hotpop.com",
    "hulapla.de",
    "hushmail.com",
    "ibunny.net",
    "ignorelist.com",
    "ihateclowns.com",
    "iheartspam.org",
    "ikemail.com",
    "imails.info",
    "imgof.com",
    "inbax.tk",
    "inbox.si",
    "inboxalias.com",
    "inboxbear.com",
    "inboxclean.com",
    "inboxclean.org",
    "inboxdesign.me",
    "inboxkitten.com",
    "incognitomail.com",
    "incognitomail.net",
    "incognitomail.org",
    "inorbit.com",
    "insorg-mail.info",
    "instant-mail.de",
    "instantemailaddress.com",
    "instantmail.org",
    "interfree.it",
    "internetoftrash.com",
    "ipoo.org",
    "ironymail.com",
    "is.gd",
    "ist-hier.de",
    "itsme.im",
    "itunesgiftcardsgiveaway.com",
    "ivolo.net",
    "iximail.com",
    "j-p.biz",
    "jamit.de",
    "je-suis-une-ordure.com",
    "jetable.com",
    "jetable.fr.nf",
    "jetable.net",
    "jetable.org",
    "jnxjn.com",
    "jourrapide.com",
    "junk1e.com",
    "junkmail.com",
    "junkmail.de",
    "junkmail.org",
    "k-mail.tk",
    "kasmail.com",
    "keepmymail.com",
    "killmail.com",
    "killmail.net",
    "klzlk.com",
    "kocaelispor.org",
    "krypton.ch",
    "ktbbh.com",
    "kuerzestemusse.de",
    "l-c-a.org",
    "lacedmail.com",
    "lakemail.tk",
    "landmail.co",
    "lastmail.co",
    "lazyinbox.com",
    "leeching.net",
    "letthemeatspam.com",
    "lhsdv.com",
    "lifebyfood.com",
    "link2mail.net",
    "litedrop.com",
    "loadby.us",
    "lol.ovh",
    "lookugly.com",
    "lortemail.dk",
    "lovebirdmusic.com",
    "lr-online.de",
    "lroid.com",
    "luxusmail.org",
    "m-mail.tk",
    "m4il.tk",
    "ma-il.tk",
    "maboard.com",
    "madhero.net",
    "magicbox.ro",
    "magimail.de",
    "mail-abuse.org",
    "mail-filter.com",
    "mail-free.org",
    "mail-handle.com",
    "mail-owl.com",
    "mail-temporaire.fr",
    "mail-trash.com",
    "mail.by",
    "mail.com.de",
    "mail.mezimages.net",
    "mail.misterpinball.de",
    "mail.sven-kuegler.de",
    "mail.trashcanmail.com",
    "mail1a.de",
    "mail2000.us",
    "mail2rss.org",
    "mail333.com",
    "mail4trash.com",
    "mailbidon.com",
    "mailbiscuit.com",
    "mailblocks.com",
    "mailbucket.org",
    "mailcatch.com",
    "maildechet.com",
    "maildechet.fr",
    "maildev.com",
    "maildrop.cc",
    "maildu.de",
    "maildrop.cf",
    "maildrop.ga",
    "maildrop.gq",
    "maildrop.ml",
    "maildrop.tk",
    "maileater.com",
    "mailexpire.com",
    "mailfa.tk",
    "mailfake.com",
    "mailforspam.com",
    "mailfreeonline.com",
    "mailfs.com",
    "mailguard.me",
    "mailhazel.com",
    "mailimate.com",
    "mailin8r.com",
    "mailina.com",
    "mailinator.com",
    "mailinator.net",
    "mailinator.org",
    "mailinator2.com",
    "mailincubator.com",
    "mailisrael.net",
    "mailjunk.tk",
    "mailkeep.net",
    "mailme.ae",
    "mailme.ir",
    "mailmoat.com",
    "mailmup.com",
    "mailna.biz",
    "mailna.co",
    "mailna.in",
    "mailna.me",
    "mailna.org",
    "mailnator.com",
    "mailnes.com",
    "mailnull.com",
    "mailop.net",
    "mailorg.org",
    "mailox.biz",
    "mailpaste.com",
    "mailperso.com",
    "mailpoof.com",
    "mailprox.com",
    "mailqwerty.com",
    "mailsac.com",
    "mailsafe.org",
    "mailscrap.com",
    "mailseal.de",
    "mailshack.com",
    "mailshield.net",
    "mailslap.com",
    "mailslurp.com",
    "mailspire.com",
    "mailt.ml",
    "mailtechx.com",
    "mailtemp.net",
    "mailtemporaire.com",
    "mailtothis.com",
    "mailtrash.net",
    "mailueberfall.de",
    "mailzilla.org",
    "makememail.com",
    "manytrash.com",
    "maxmail.in",
    "mbx.cc",
    "mega.zik.dj",
    "meltmail.com",
    "meowmail.net",
    "messagebeamer.de",
    "metamail.ch",
    "mezimages.net",
    "migmail.pl",
    "minmail.net",
    "mintemail.com",
    "miserymail.com",
    "mohmal.com",
    "mohmal.im",
    "mohmal.in",
    "mohmal.tech",
    "moncourrier.fr.nf",
    "monemail.fr.nf",
    "monmail.fr.nf",
    "mowgli.junglecode.net",
    "mp-j.pe.hu",
    "msgsafe.io",
    "mspeoplesoft.com",
    "mt2014.com",
    "mt2015.com",
    "muchomail.com",
    "my10minutemail.com",
    "myanonbox.com",
    "mycleaninbox.com",
    "mydropmail.com",
    "mymail-in.net",
    "mymaily.net",
    "mymtmail.com",
    "mynetstore.de",
    "myspamfunder.org",
    "myspt.com",
    "mytempemail.com",
    "mytrashmail.com",
    "mzi.at",
    "nadamail.com",
    "nada.ltd",
    "netcourrier.com",
    "netzidiot.de",
    "neverbox.com",
    "nice-4u.com",
    "niftymail.com",
    "nobulk.com",
    "noclickemail.com",
    "nodepositbonuscasino.org",
    "noface.net",
    "noleak.net",
    "nomail.xl.cx",
    "nospam.ze.tc",
    "nospam4.us",
    "nospamfor.us",
    "nospammail.net",
    "nospamthanks.info",
    "notmailinator.com",
    "novalocal",
    "nowmymail.com",
    "nowres.com",
    "nullbox.org",
    "nursemail.org",
    "nyms.net",
    "objectmail.com",
    "obobbo.com",
    "oddbot.org",
    "ohaa.de",
    "omgspam.com",
    "oneoffmail.com",
    "onewaymail.com",
    "online.ms",
    "oogabooga.org",
    "opentrash.com",
    "optinpass.com",
    "otherinbox.com",
    "ourproject.org",
    "ourtrashcan.com",
    "outlawthru.com",
    "owlpic.com",
    "pacopack.com",
    "pamparam.com",
    "panama-immo.info",
    "parlons.fr.nf",
    "passemapeste.com",
    "pemail.net",
    "penisgo.com",
    "peppymail.com",
    "pookmail.com",
    "postinbox.com",
    "posttrash.com",
    "powerencry.com",
    "privacy.net",
    "privatdemail.net",
    "privy-mail.de",
    "proxymail.eu",
    "prtnx.com",
    "puppymail.de",
    "putthisinyourspamdatabase.com",
    "quickinbox.com",
    "quickmail.info",
    "rcpt.at",
    "re-gister.com",
    "reconmail.com",
    "redchan.it",
    "refurbe.com",
    "regbypass.com",
    "regme.me",
    "remail.ch",
    "remailer.net",
    "revolab.net",
    "rhyta.com",
    "rmq.kr",
    "ro.lt",
    "robbins.org",
    "rootfest.net",
    "rppkn.com",
    "safetymail.info",
    "safetypost.de",
    "sandvikcoromant.pizza",
    "scatmail.com",
    "schafmail.de",
    "schrottmail.ch",
    "schrottmail.org",
    "secmail.net",
    "sendfree.org",
    "sharklasers.com",
    "shielded.co",
    "shieldemail.com",
    "shortmail.net",
    "shoutmail.net",
    "sibermail.com",
    "sinnlos-mail.de",
    "skeptik.org",
    "slaskpost.se",
    "slopsbox.com",
    "smashmail.de",
    "smellfear.com",
    "snkmail.com",
    "sofort-mail.de",
    "sogetthis.com",
    "soodonims.com",
    "spambob.com",
    "spambob.net",
    "spambob.org",
    "spambog.com",
    "spambog.de",
    "spambog.ru",
    "spambox.info",
    "spambox.us",
    "spamcan.org",
    "spamcannon.com",
    "spamcannon.net",
    "spamcon.org",
    "spamcorptastic.com",
    "spamcowboy.com",
    "spamday.com",
    "spameater.org",
    "spamex.com",
    "spamfree24.de",
    "spamfree24.eu",
    "spamfree24.info",
    "spamfree24.net",
    "spamfree24.org",
    "spamgourmet.com",
    "spamgourmet.net",
    "spamgourmet.org",
    "spamhole.com",
    "spamify.com",
    "spaminator.de",
    "spamkill.info",
    "spaml.de",
    "spamlot.com",
    "spammash.com",
    "spammatador.com",
    "spammenot.com",
    "spammo.net",
    "spamnada.com",
    "spampow.com",
    "spamspot.com",
    "spamthis.co.uk",
    "spamtrail.com",
    "superrito.com",
    "suremail.info",
    "tafmail.com",
    "teewars.org",
    "teleworm.us",
    "temp-mail.de",
    "temp-mail.org",
    "temp-mail.ru",
    "tempail.com",
    "tempemail.co",
    "tempemail.com",
    "tempemail.net",
    "tempinbox.co.uk",
    "tempinbox.com",
    "tempmail.co",
    "tempmail.com",
    "tempmail.de",
    "tempmail.eu",
    "tempmail.fr",
    "tempmail.in",
    "tempmail.it",
    "tempmail.net",
    "tempmail.ninja",
    "tempmail.org",
    "tempmail.pro",
    "tempmail.space",
    "tempmail24.net",
    "tempmailer.com",
    "tempmailer.de",
    "tempmailer.net",
    "temporaryemail.net",
    "temporaryemail.org",
    "temporaryforwarding.com",
    "temporaryinbox.com",
    "temppost.com",
    "tempthe.net",
    "throwawayemailaddress.com",
    "throwawaymail.com",
    "tikmail.com",
    "tmail.com",
    "tmail.io",
    "tmails.net",
    "toddsbighouseofspam.com",
    "trash-mail.at",
    "trash-mail.ch",
    "trash-mail.com",
    "trash-mail.de",
    "trash-mail.net",
    "trash-me.com",
    "trashcanmail.com",
    "trashmail.at",
    "trashmail.ch",
    "trashmail.com",
    "trashmail.de",
    "trashmail.io",
    "trashmail.me",
    "trashmail.net",
    "trashmail.org",
    "trashmailer.com",
    "trashymail.com",
    "trbvm.com",
    "trickmail.net",
    "tvnmail.com",
    "twohourmail.com",
    "uemail99.com",
    "uggsrock.com",
    "unglaublich.de",
    "unlimit.com",
    "unterderbruecke.de",
    "upliftnow.com",
    "urhen.com",
    "validdns.com",
    "vefsmail.com",
    "veryrealemail.com",
    "vidalia.onion",
    "vipermail.de",
    "vpn.st",
    "vubox.com",
    "walala.org",
    "walkmail.net",
    "watchmail.de",
    "webemail.me",
    "webm4il.in",
    "webmail.ms",
    "wegwerf-adresse.de",
    "wegwerfadresse.de",
    "wegwerfemail.com",
    "wegwerfemail.de",
    "wegwerfmail.de",
    "wegwerfmail.net",
    "wegwerfmail.org",
    "wetrainbayarea.com",
    "wh4f.org",
    "whatpaas.com",
    "whyspam.me",
    "wmail.club",
    "wr.ht",
    "wronghead.com",
    "wuzup.net",
    "wuzupmail.net",
    "wwwnew.eu",
    "xagloo.com",
    "xemaps.com",
    "xents.com",
    "xmaily.com",
    "xmailzone.com",
    "xoxy.net",
    "yapped.net",
    "yert.org",
    "yep.it",
    "yomail.info",
    "yopmail.com",
    "yopmail.fr",
    "yopmail.net",
    "ypmail.webcindario.com",
    "yudmail.com",
    "zehnminutenmail.de",
    "zippymail.info",
    "zoemail.org",
    "zxcvbnm.co.uk",
)

DISPOSABLE_DOMAINS: frozenset[str] = frozenset(_DISPOSABLE_DOMAINS_TUPLE)


def normalize_domain(domain: str | None) -> str:
    """
    Safely normalizes a domain string.
    - Strips surrounding whitespace
    - Lowercases ASCII
    - Strips trailing dots (FQDN notation)
    - Encodes IDN / non-ASCII domains to punycode safely (RFC 3492 / 5891)
    """
    if not domain:
        return ""
    
    clean = str(domain).strip().lower().rstrip(".")
    if not clean:
        return ""
    
    # Handle IDN / Unicode domain normalization
    try:
        clean = clean.encode("idna").decode("ascii")
    except Exception:
        # Fallback to stripped lowercase if idna conversion fails
        pass

    return clean


def is_disposable_domain(domain: str | None) -> bool:
    """
    Checks if a domain or its parent domain belongs to the disposable domains set.
    Example: 'sub.mailinator.com' matches 'mailinator.com'.
    """
    norm = normalize_domain(domain)
    if not norm or ".." in norm:
        return False
    
    # Check exact match
    if norm in DISPOSABLE_DOMAINS:
        return True
    
    # Check hierarchical parent domains
    parts = norm.split(".")
    for i in range(1, len(parts) - 1):
        parent = ".".join(parts[i:])
        if parent in DISPOSABLE_DOMAINS:
            return True
            
    return False


def is_public_email_provider(domain: str | None) -> bool:
    """
    Checks if a domain or its parent domain belongs to the recognized public email providers.
    Example: 'gmail.com', 'yahoo.co.in', 'sub.outlook.com'.
    """
    norm = normalize_domain(domain)
    if not norm or ".." in norm:
        return False

    if norm in PUBLIC_EMAIL_PROVIDERS:
        return True

    parts = norm.split(".")
    for i in range(1, len(parts) - 1):
        parent = ".".join(parts[i:])
        if parent in PUBLIC_EMAIL_PROVIDERS:
            return True

    return False


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Computes basic Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def suggest_domain_typo(domain: str | None) -> str | None:
    """
    Suggests a correction if a domain is a known or close typo of a popular provider.
    Returns None if:
    - Domain is already a valid popular domain (no false positive)
    - Domain is not a known typo or close match
    - Domain is empty/invalid
    """
    norm = normalize_domain(domain)
    if not norm:
        return None
    
    # Never suggest a replacement for a domain that is already correct
    if norm in POPULAR_DOMAINS:
        return None
    
    # 1. Direct dictionary lookup (fastest & highest precision)
    if norm in COMMON_TYPO_MAP:
        return COMMON_TYPO_MAP[norm]
    
    # 2. Strict distance check against POPULAR_DOMAINS
    # Only evaluate domains with standard top-level endings and length >= 6
    if len(norm) < 6 or "." not in norm:
        return None
    
    norm_tld = norm.rsplit(".", 1)[-1]
    
    best_candidate: str | None = None
    min_dist = 999
    
    for pop in POPULAR_DOMAINS:
        pop_tld = pop.rsplit(".", 1)[-1]
        # Only compare if TLDs are identical or both common (.com, .co, .con)
        if norm_tld != pop_tld and not (norm_tld in ("co", "con", "cm") and pop_tld == "com"):
            continue
            
        dist = _levenshtein_distance(norm, pop)
        # Only suggest if distance is exactly 1 (e.g. 1 letter transposed/inserted/deleted)
        if dist == 1 and dist < min_dist:
            min_dist = dist
            best_candidate = pop

    return best_candidate


def is_custom_email_domain(domain: str | None) -> bool:
    """
    Returns True if domain is a plausible private/custom/business domain:
    - Normalizes properly
    - Not a known disposable domain
    - Not a recognized public email provider
    - Not a recognized typo of a public email provider
    - Contains at least one dot and no double dots
    - Not localhost, loopback, or private IP
    """
    norm = normalize_domain(domain)
    if not norm or "." not in norm or ".." in norm:
        return False

    if is_disposable_domain(norm):
        return False

    if is_public_email_provider(norm):
        return False

    typo = suggest_domain_typo(norm)
    if typo and is_public_email_provider(typo):
        return False

    if is_third_party_directory_or_aggregator(norm):
        return False

    return True


NON_BUSINESS_DOMAINS_TLD: tuple[str, ...] = (
    ".gov",
    ".gov.in",
    ".nic.in",
    ".mil",
    ".edu",
    ".ac.in",
    ".court.in",
    ".highcourt.in",
    ".judiciary.in",
)


THIRD_PARTY_DIRECTORY_DOMAINS: frozenset[str] = frozenset({
    # Corporate registries & government / business registries
    "zaubacorp.com",
    "tofler.in",
    "quickcompany.in",
    "instafinancials.com",
    "company360.in",
    "corporatedir.com",
    "mca.gov.in",
    "companieshouse.gov.uk",
    "sec.gov",
    "opencorporates.com",
    "chambers.com",
    # B2B marketplaces & directories
    "indiamart.com",
    "imimg.com",
    "tradeindia.com",
    "exportersindia.com",
    "tradekey.com",
    "justdial.com",
    "sulekha.com",
    "yellowpages.com",
    "yellowpagesonline.in",
    "yellowpages.in",
    "infodriveindia.com",
    "indiabizlist.com",
    "dialme.in",
    "webindia123.com",
    "kompass.com",
    "europages.com",
    "alibaba.com",
    "aliexpress.com",
    "garment-india.com",
    "helloindia.co",
    "mayoworld.com",
    "howtoexportimport.com",
    "shippingaviation.com",
    "flax.bio",
    "recycleinme.com",
    "exporttrademart.com",
    # Business data & credit aggregators
    "dnb.com",
    "dnb.co.in",
    "zoominfo.com",
    "apollo.io",
    "crunchbase.com",
    "pitchbook.com",
    "bloomberg.com",
    "manta.com",
    "bbb.org",
    "yelp.com",
    "tripadvisor.com",
    "trustpilot.com",
    # Social media & major tech aggregators
    "facebook.com",
    "fb.com",
    "linkedin.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "pinterest.com",
    "reddit.com",
    "medium.com",
    "wikipedia.org",
    # Search engines
    "google.com",
    "google.co.in",
    "bing.com",
    "duckduckgo.com",
    "baidu.com",
})

SEARCH_ENGINE_WEBSITE_DOMAINS: frozenset[str] = frozenset({
    "google.com",
    "google.co.in",
    "bing.com",
    "yahoo.com",
    "yandex.com",
    "duckduckgo.com",
    "baidu.com",
})


def is_third_party_directory_or_aggregator(url_or_domain: str | None) -> bool:
    """
    Returns True if the given URL or domain is a third-party company registry,
    directory, search result, social media platform, or business aggregator.
    Such sources are evidence provenance, NOT a company's official website.
    Safely matches domains and subdomains without false positives on legitimate company names.
    """
    if not url_or_domain:
        return False
    raw = str(url_or_domain).strip().lower()
    if "://" in raw:
        try:
            from urllib.parse import urlparse
            raw = urlparse(raw).netloc
        except Exception:
            pass
    # Strip port if present
    if ":" in raw:
        raw = raw.split(":")[0]
    norm = normalize_domain(raw)
    if not norm:
        return False
    if norm in THIRD_PARTY_DIRECTORY_DOMAINS or norm in SEARCH_ENGINE_WEBSITE_DOMAINS:
        return True
    if any(norm.endswith("." + d) for d in THIRD_PARTY_DIRECTORY_DOMAINS):
        return True
    if any(norm.endswith("." + d) for d in SEARCH_ENGINE_WEBSITE_DOMAINS):
        return True
    return False


def is_directory_or_platform_email(email: str | None) -> bool:
    """
    Returns True if the email address domain belongs to a third-party directory,
    registry, aggregator, marketplace, or directory platform.
    Explicitly excludes standard consumer/public email providers (e.g. Gmail, Yahoo, Outlook).
    Such platform emails (e.g. info@yellowpagesonline.in, india@dnb.com) must NOT be treated
    as a company-owned email address without independent evidence.
    """
    if not email or "@" not in str(email):
        return False
    parts = str(email).lower().strip().split("@")
    if len(parts) != 2:
        return False
    domain = normalize_domain(parts[1].strip())
    if not domain:
        return False
    if is_public_email_provider(domain):
        return False
    if domain in THIRD_PARTY_DIRECTORY_DOMAINS:
        return True
    return any(domain.endswith("." + d) for d in THIRD_PARTY_DIRECTORY_DOMAINS)


def infer_website_candidate_from_email(email: str | None) -> str | None:
    """
    Safely infers an unverified website candidate URL from a business email address.
    Returns a normalized HTTPS URL (e.g. 'https://abhiyancargo.com') or None if ineligible.
    
    Safe rules:
    - Parses and normalizes the domain safely.
    - Skips generic/free email providers (Gmail, Yahoo, Outlook, Hotmail, etc.).
    - Skips typos of public providers (e.g. yahoo.co).
    - Skips disposable email domains.
    - Skips third-party directories, registries, or aggregators.
    - Skips invalid domains, IPs, localhost/private-network, and government/court/non-commercial TLDs.
    - Strips credentials, path, query strings, and fragments.
    - Does NOT make live HTTP requests.
    """
    if not email or "@" not in str(email):
        return None
    parts = str(email).lower().strip().split("@")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return None
    raw_dom = parts[1].strip()
    norm = normalize_domain(raw_dom)
    if not norm or "." not in norm or ".." in norm:
        return None
    # Block loopback, localhost, private hostnames
    if norm in ("localhost", "127.0.0.1", "0.0.0.0") or norm.endswith(".local") or norm.endswith(".lan") or norm.endswith(".internal"):
        return None
    # Block raw IPv4 addresses
    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", norm):
        return None
    # Block third-party directories / aggregators
    if is_third_party_directory_or_aggregator(norm):
        return None
    # Verify custom business domain
    if not is_custom_email_domain(norm):
        return None
    # Filter institutional / government / court domains
    if any(norm == tld.lstrip(".") or norm.endswith(tld) for tld in NON_BUSINESS_DOMAINS_TLD) or any(k in norm for k in ("highcourt.", "judiciary.", "court.gov")):
        return None
    return f"https://{norm}"


