"""Email notification utilities for SafeRoute API.

Uses Resend for transactional email delivery. Supports notifications for:
- New form submissions
- Failed deliveries
- Daily digests
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from resend import Resend

from app.config import settings

logger = logging.getLogger(__name__)

_resend_client = None


def _get_resend_client() -> Optional[Resend]:
    global _resend_client
    if _resend_client is None:
        if not settings.RESEND_API_KEY:
            return None
        _resend_client = Resend(api_key=settings.RESEND_API_KEY)
    return _resend_client


_DISPOSABLE_EMAIL_DOMAINS = {
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
"""Common disposable email domains.

Updated periodically. For production use, consider fetching from
https://raw.githubusercontent.com/ivolo/disposable-email-domains/master/index.json
"""


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
        client = _get_resend_client()
        if client is None:
            return False
        email = _render_submission_email(to, subject, payload, route_name, reply_to)
        result = client.emails.send(email)
        logger.info(
            "Submission email sent",
            extra={"to": to, "subject": subject, "id": result.get("id")},
        )
        return True
    except Exception:
        logger.exception("Failed to send submission email to %s", to)
        return False
