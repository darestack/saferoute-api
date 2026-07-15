"""Email notification utilities for SafeRoute API.

Uses Resend for transactional email delivery. Supports notifications for:
- New form submissions
- Failed deliveries
- Daily digests
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import httpx
from resend import Resend

from app.config import settings

logger = logging.getLogger(__name__)

_resend_client = None

# ---------------------------------------------------------------------------
# Disposable email detection
# ---------------------------------------------------------------------------
_DISPOSABLE_EMAIL_DOMAINS: set[str] = set()
"""Runtime-loaded set of disposable email domains.

Loaded from ``DISPOSABLE_EMAIL_LIST_URL`` if set, otherwise falls back to
an embedded minimal list. The cache is refreshed on every ``settings``
reload (typically only on startup).
"""

_DISPOSABLE_EMAIL_LIST_URL = os.environ.get(
    "DISPOSABLE_EMAIL_LIST_URL",
    "https://raw.githubusercontent.com/ivolo/disposable-email-domains/master/index.json",
)
"""Source for disposable email domains. Set to empty string to disable."""

_EMBEDDED_DISPOSABLE_DOMAINS = {
    "10minutemail.com",
    "guerrillamail.com",
    "mailinator.com",
    "trashmail.com",
    "tempmail.com",
    "yopmail.com",
    "throwaway.email",
    "fakeinbox.com",
    "temp-mail.org",
    "dispostable.com",
    "mailnesia.com",
    "tempail.com",
    "mohmal.com",
    "emailondeck.com",
    "burnermail.io",
    "getnada.com",
    "inboxes.com",
    "maildrop.cc",
    "mintemail.com",
    "sharklasers.com",
    "guerrillamailblock.com",
    "pokemail.net",
    "spam4.me",
    "grr.la",
    "disign-concept.com",
    "tempmailaddress.com",
    "tmpmail.net",
    "tmpmail.org",
    "tmpbox.net",
    "mytemp.email",
    "tempemail.co.za",
    "throwam.com",
    "getairmail.com",
    "dropmail.me",
    "harakirimail.com",
    "mailshell.com",
    "mailzilla.com",
    "mytrashmail.com",
    "noclickemail.com",
    "quickinbox.com",
    "rcpt.at",
    "recode.me",
    "regbypass.com",
    "rmqkr.net",
    "royal.net",
    "s0ny.net",
    "safersignup.de",
    "safetymail.info",
    "sanity.job",
    "saynotospam.com",
    "scbox.one",
    "schachrol.com",
    "selfdestructingmail.com",
    "sendspamhere.com",
    "sharedmailbox.org",
    "shieldemail.com",
    "shiftmail.com",
    "shitmail.me",
    "shortmail.net",
    "showslow.de",
    "sibmail.com",
    "slapsfromlastnight.com",
    "slaskpost.se",
    "smashmail.de",
    "smellfear.com",
    "snakemail.com",
    "sneakemail.com",
    "snkmail.com",
    "sofimail.com",
    "solvemail.info",
    "sogetthis.com",
    "spamail.com",
    "spamarrest.com",
    "spambog.com",
    "spambog.de",
    "spambog.ru",
    "spambooger.com",
    "spambox.info",
    "spambox.org",
    "spambox.us",
    "spamcannon.com",
    "spamcannon.net",
    "spamcon.org",
    "spamcorptastic.com",
    "spamcowboy.com",
    "spamday.com",
    "spamex.com",
    "spamfree.eu",
    "spamfree24.com",
    "spamfree24.de",
    "spamfree24.eu",
    "spamfree24.info",
    "spamfree24.net",
    "spamfree24.org",
    "spamgoes.in",
    "spamgourmet.com",
    "spamgourmet.net",
    "spamgourmet.org",
    "spamherelots.com",
    "spamhole.com",
    "spamify.com",
    "spaml.com",
    "spaml.de",
    "spammotel.com",
    "spamobox.com",
    "spamoff.de",
    "spamsalad.com",
    "spamslicer.com",
    "spamspot.com",
    "spamthis.co.uk",
    "spamthisplease.com",
    "spamtrap.co",
    "spamtroll.net",
    "speed.1s.fr",
    "spikio.com",
    "spoofmail.de",
    "spr.io",
    "squizzy.de",
    "squizzy.net",
    "sroff.com",
    "stamfordlincoln.com",
    "starlight-breaker.net",
    "startfu.com",
    "stealthmail.com",
    "sterlingfinance.com",
    "stinkefinger.de",
    "stop-my-spam.com",
    "stuffmail.de",
    "super-auswahl.de",
    "supergreatmail.com",
    "supermailer.jp",
    "superrito.com",
    "supersite.it",
    "superstachel.de",
    "suremail.info",
    "svk.jp",
    "sweetxxx.de",
    "tafmail.com",
    "tefl.com",
    "teleworm.com",
    "teleworm.us",
    "temp-mail.com",
    "temp-mail.de",
    "temp.bartdevos.be",
    "temp.email.gq",
    "temp.mail",
    "tempail.com",
    "tempemail.co.za",
    "tempemail.co",
    "tempemail.com",
    "tempemail.net",
    "tempinbox.co.uk",
    "tempmail.co",
    "tempmail.com",
    "tempmail.de",
    "tempmail.eu",
    "tempmail.io",
    "tempmail.pro",
    "tempmail.space",
    "tempmailaddress.com",
    "tempmaildemo.com",
    "tempmailer.com",
    "tempmailer.de",
    "tempmailo.com",
    "tempmails.com",
    "tempomail.fr",
    "temporaryemail.us",
    "temporaryforwarding.com",
    "temporaryinbox.com",
    "tempr.email",
    "tempsky.com",
    "tempthe.net",
    "tempymail.com",
    "testore.com",
    "thanksnospam.info",
    "thankyou2010.com",
    "thecloudindex.com",
    "themail.com",
    "themail.me",
    "thismail.net",
    "thismail.org",
    "throam.com",
    "throwam.com",
    "throwawayemailaddress.com",
    "tilien.com",
    "tittbit.com",
    "tizi.com",
    "tmail.ws",
    "tmailinator.com",
    "tmpmail.net",
    "tmpmail.org",
    "toddsbargainbins.com",
    "toiea.com",
    "tokenmail.de",
    "topinrock.cf",
    "topranklist.de",
    "tormail.org",
    "totesmail.com",
    "tpwls.com",
    "trash-mail.at",
    "trash-mail.cf",
    "trash-mail.ga",
    "trash-mail.gq",
    "trash-mail.ml",
    "trash-mail.tk",
    "trash2009.com",
    "trash2010.com",
    "trash2011.com",
    "trashbox.eu",
    "trashdevil.com",
    "trashdevil.de",
    "trashemail.de",
    "trashemails.de",
    "trashmail.at",
    "trashmail.com",
    "trashmail.de",
    "trashmail.io",
    "trashmail.me",
    "trashmail.net",
    "trashmail.org",
    "trashmail.ws",
    "trashymail.com",
    "trashymail.net",
    "trickmail.net",
    "trollproject.com",
    "truckerz.com",
    "twinmail.de",
    "twoweirdtricks.com",
    "tyhe.ro",
    "uacro.com",
    "ubismail.net",
    "ucche.com",
    "ufxqsg.site",
    "uguuchante.com",
    "uk.to",
    "umail.net",
    "unimark.org",
    "unitel.com",
    "unmail.ru",
    "upliftnow.com",
    "uplipht.com",
    "upozowac.com",
    "urfey.com",
    "us.to",
    "ushijima1124.club",
    "vda.li",
    "vemomail.win",
    "veryrealemail.com",
    "vidchart.com",
    "viditag.com",
    "viewcastmedia.com",
    "viewcastmedia.net",
    "vipmail.name",
    "vipmail.org",
    "viralplays.com",
    "vkcode.ru",
    "vmail.digital",
    "vmail.me",
    "vmpanda.com",
    "vorga.com",
    "votiputox.com",
    "vpn.st",
    "vps30.com",
    "vpslists.com",
    "vsimcard.com",
    "vubby.com",
    "vuiy.com",
    "vztc.com",
    "w3site.org",
    "wakingupesther.com",
    "walkmail.net",
    "walkmail.ru",
    "wasteland.rfc822.org",
    "watch-harry-potter.com",
    "watchever.biz",
    "wazabi.club",
    "wbdev.tech",
    "we-fuck.com",
    "webemail.me",
    "webm4il.info",
    "webuser.in",
    "wee.my",
    "wef.gr",
    "wefjo.com",
    "wemel.top",
    "wetrainbayarea.com",
    "wetrainbayarea.org",
    "wh4f.org",
    "whatiaas.com",
    "whatifanalytics.com",
    "whopy.com",
    "wibblesmith.com",
    "widaryanto.info",
    "widget.gg",
    "wiemei.com",
    "wierie.tk",
    "wifimaple.com",
    "wiki24.nl",
    "wilelink.com",
    "willhackforfood.biz",
    "winemails.info",
    "wmail.club",
    "wokcy.com",
    "wolfmail.ml",
    "wolfsmail.tk",
    "wollan.info",
    "worldspace.link",
    "wovz.org",
    "wr.moeri.org",
    "wralaw.com",
    "writeme.us",
    "wronghead.com",
    "ws.gy",
    "wudet.men",
    "wuespn.com",
    "wupics.com",
    "x1x.spymail.one",
    "xagloo.co",
    "xcompress.com",
    "xcoxc.com",
    "xmail.com",
    "xmail.net",
    "xmail2.net",
    "xn--9kq.com",
    "xn--w69aq1hk0a.com",
    "xost.us",
    "xoxox.cc",
    "xperiae5.com",
    "xrx.at",
    "xscale.com",
    "xsmega.com",
    "xtc.gov",
    "xv9.org",
    "xxhamsterxx.ga",
    "xxi2.com",
    "xxolane.com",
    "xxqx5200.com",
    "xy9ce.tk",
    "xyzfree.net",
    "xzsok.com",
    "yabai-oppai.xyz",
    "yahmail.top",
    "yamail.win",
    "yannmail.win",
    "yep.it",
    "yhg.biz",
    "ynm.de",
    "yodx.ro",
    "yopmail.com",
    "yopmail.fr",
    "yopmail.net",
    "yopmail.org",
    "yordanmail.cf",
    "you-spam.com",
    "yougotmail.com",
    "youneedmore.info",
    "yourdomain.com",
    "youremail.cf",
    "yourewrong.com",
    "yourlms.biz",
    "yourspamgoeshere.info",
    "yourtube.ml",
    "yspend.com",
    "yugasandrika.com",
    "yui.it",
    "yuki.tech",
    "yundiksa.com",
    "yuurok.com",
    "yx.x10.bz",
    "z-o-o-m.eu",
    "z1p.biz",
    "za.com",
    "zain.site",
    "zainmax.net",
    "zaktouni.fr",
    "ze.tc",
    "zeemail.com",
    "zepp.dk",
    "zetmail.com",
    "zippymail.info",
    "zmail.com",
    "zmail.ru",
    "zoemail.com",
    "zoemail.net",
    "zomg.info",
    "zsero.com",
    "zxcv.com",
    "zxcvbnm.com",
    "zymail.com",
    "zzi.us",
}
"""Minimal embedded fallback list if external fetch fails."""


async def _load_disposable_email_domains() -> None:
    """Load disposable email domains from external source or fallback."""
    global _DISPOSABLE_EMAIL_DOMAINS

    if not _DISPOSABLE_EMAIL_LIST_URL:
        _DISPOSABLE_EMAIL_DOMAINS = set(_EMBEDDED_DISPOSABLE_DOMAINS)
        return

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(_DISPOSABLE_EMAIL_LIST_URL)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    _DISPOSABLE_EMAIL_DOMAINS = {
                        domain.strip().lower()
                        for domain in data
                        if isinstance(domain, str) and domain.strip()
                    }
                    logger.info(
                        "Loaded %d disposable email domains", len(_DISPOSABLE_EMAIL_DOMAINS)
                    )
                    return
    except Exception:
        logger.exception("Failed to load disposable email domains from %s", _DISPOSABLE_EMAIL_LIST_URL)

    _DISPOSABLE_EMAIL_DOMAINS = set(_EMBEDDED_DISPOSABLE_DOMAINS)
    logger.info("Falling back to embedded disposable email list (%d domains)", len(_DISPOSABLE_EMAIL_DOMAINS))


def is_disposable_email(email: str) -> bool:
    """Check if an email address uses a disposable domain.

    Args:
        email: The email address to check.

    Returns:
        ``True`` if the domain is in the disposable list, ``False`` otherwise.
    """
    if not email or "@" not in email:
        return False
    domain = email.split("@")[-1].strip().lower()
    return domain in _DISPOSABLE_EMAIL_DOMAINS


# ---------------------------------------------------------------------------
# Resend email client
# ---------------------------------------------------------------------------
def _get_resend_client() -> Optional[Resend]:
    """Lazily initialize and return the Resend client."""
    global _resend_client
    if _resend_client is None:
        if not settings.RESEND_API_KEY:
            return None
        _resend_client = Resend(api_key=settings.RESEND_API_KEY)
    return _resend_client


# ---------------------------------------------------------------------------
# Email rendering
# ---------------------------------------------------------------------------
def _render_submission_email(
    to: str,
    subject: str,
    payload: dict[str, Any],
    route_name: str,
    reply_to: str = "",
) -> dict[str, Any]:
    """Render a simple HTML email for a new form submission.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        payload: Parsed form payload.
        route_name: Human-readable route name.
        reply_to: Optional reply-to address.

    Returns:
        Resend email payload dict.
    """
    rows = "".join(
        f"<tr><td><strong>{key}</strong></td><td>{value}</td></tr>"
        for key, value in payload.items()
    )

    html = f"""
    <html>
      <body>
        <h2>New submission: {route_name}</h2>
        <table border="1" cellpadding="6" cellspacing="0">
          {rows}
        </table>
      </body>
    </html>
    """

    email: dict[str, Any] = {
        "from": settings.EMAIL_FROM,
        "to": to,
        "subject": subject,
        "html": html,
    }
    if reply_to:
        email["reply_to"] = reply_to

    return email


# ---------------------------------------------------------------------------
# Email delivery with retry
# ---------------------------------------------------------------------------
_EMAIL_RETRY_ATTEMPTS = 3
"""Maximum attempts for email delivery."""

_EMAIL_RETRY_BACKOFF_BASE = 1.0
"""Base backoff in seconds between email retries."""


async def _send_with_retry(email: dict[str, Any]) -> bool:
    """Send an email with exponential backoff retry.

    Args:
        email: Resend email payload dict.

    Returns:
        ``True`` if the email was accepted by Resend, ``False`` otherwise.
    """
    client = _get_resend_client()
    if client is None:
        return False

    for attempt in range(1, _EMAIL_RETRY_ATTEMPTS + 1):
        try:
            result = client.emails.send(email)
            logger.info(
                "Submission email sent",
                extra={"to": email.get("to"), "subject": email.get("subject"), "id": result.get("id"), "attempt": attempt},
            )
            return True
        except Exception as exc:
            if attempt < _EMAIL_RETRY_ATTEMPTS:
                backoff = _EMAIL_RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "Email send attempt %d failed, retrying in %.1fs: %s",
                    attempt,
                    backoff,
                    exc,
                )
                await asyncio.sleep(backoff)
            else:
                logger.exception(
                    "Email send failed after %d attempts to %s", _EMAIL_RETRY_ATTEMPTS, email.get("to")
                )

    return False


async def send_submission_email(
    to: str,
    subject: str,
    payload: dict[str, Any],
    route_name: str,
    reply_to: str = "",
) -> bool:
    """Send a form-submission notification email via Resend.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        payload: Parsed form payload.
        route_name: Human-readable route name.
        reply_to: Optional reply-to address.

    Returns:
        ``True`` if the email was accepted by Resend, ``False`` otherwise.
    """
    if not settings.RESEND_API_KEY:
        return False

    try:
        email = _render_submission_email(to, subject, payload, route_name, reply_to)
        return await _send_with_retry(email)
    except Exception:
        logger.exception("Failed to queue submission email to %s", to)
        return False
