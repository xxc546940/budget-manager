#!/usr/bin/env python3
"""Email the latest budget report to yourself via Gmail.

You run this; it is never invoked automatically. The app password is read from
a file rather than an argument, so it does not land in shell history or in the
process list where anyone on the machine can read it.

    python3 scripts/send_report.py --password-file ~/.budget-gmail-app-password

Create the app password at https://myaccount.google.com/apppasswords (requires
2-Step Verification). Then:

    printf '%s' 'abcdefghijklmnop' > ~/.budget-gmail-app-password
    chmod 600 ~/.budget-gmail-app-password

Gmail needs the 16-character app password, not your account password.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import ssl
import stat
import sys
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, parseaddr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT = ROOT / "reports" / "latest-dashboard.html"
CONFIG = ROOT / "config" / "budget.json"


def read_password(path: Path) -> str:
    if not path.exists():
        sys.exit(f"No password file at {path}\n"
                 f"Create one:  printf '%s' 'your-16-char-app-password' > {path}\n"
                 f"             chmod 600 {path}")
    mode = path.stat().st_mode
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        print(f"warning: {path} is readable by other users. chmod 600 it.", file=sys.stderr)
    # Strip whitespace: Google displays app passwords in groups of four.
    pw = re.sub(r"\s+", "", path.read_text())
    if not pw:
        sys.exit(f"{path} is empty.")
    if len(pw) != 16:
        print(f"warning: expected a 16-character app password, got {len(pw)} characters. "
              "An ordinary account password will be rejected by Gmail.", file=sys.stderr)
    return pw


def ssl_context() -> ssl.SSLContext:
    """A context with a working CA bundle.

    Python installed from python.org ships without one: its expected bundle at
    .../etc/openssl/cert.pem only appears once "Install Certificates.command" has
    been run, and until then every TLS connection fails with
    CERTIFICATE_VERIFY_FAILED. certifi carries the same Mozilla bundle, so fall
    back to it rather than making the user debug an opaque SSL error.
    """
    ctx = ssl.create_default_context()
    paths = ssl.get_default_verify_paths()
    have_default = any(p and os.path.exists(p) for p in
                       (paths.cafile, paths.capath, paths.openssl_cafile, paths.openssl_capath))
    if have_default:
        return ctx
    try:
        import certifi
    except ImportError:
        return ctx          # let the connection fail; the handler explains it
    bundle = certifi.where()
    if os.path.exists(bundle):
        print(f"  certs  : using certifi ({bundle})")
        return ssl.create_default_context(cafile=bundle)
    return ctx


def cert_help() -> str:
    exe = Path(sys.executable).resolve()
    hint = ""
    for parent in exe.parents:
        cmd = parent / "Install Certificates.command"
        if cmd.exists():
            hint = f'\n  Permanent fix:  open "{cmd}"'
            break
    if not hint:
        for d in Path("/Applications").glob("Python 3.*/Install Certificates.command"):
            hint = f'\n  Permanent fix:  open "{d}"'
            break
    return ("Gmail's certificate could not be verified: this Python has no CA bundle.\n"
            "  This is the usual state of a python.org install until its certificate\n"
            "  step has been run - it is not a problem with Gmail or your password."
            + hint +
            f"\n  Or install the bundle certifi provides:  {sys.executable} -m pip install certifi")


ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def collect_addresses(values, label: str) -> list[str]:
    """Parse recipients from repeated flags, commas, or a config list.

    Accepts "a@b.com", "a@b.com, c@d.com", repeated --to, a JSON list in
    config, and display-name forms like "Jun <jun@example.com>". Duplicates are
    dropped while keeping the order given, so a name appearing in both the flag
    and the config does not get two copies.
    """
    raw: list[str] = []
    for v in values:
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            raw.extend(str(x) for x in v)
        else:
            raw.append(str(v))
    if not raw:
        return []

    out, seen, bad = [], set(), []
    for _, addr in getaddresses(raw):
        addr = addr.strip()
        if not addr:
            continue
        if not ADDRESS.match(addr):
            bad.append(addr)
            continue
        key = addr.lower()
        if key not in seen:
            seen.add(key)
            out.append(addr)
    if bad:
        sys.exit(f"These {label} addresses do not look like email addresses:\n  "
                 + "\n  ".join(bad))
    return out


def settings() -> dict:
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text()).get("settings", {}) or {}
        except json.JSONDecodeError:
            pass
    return {}


def plain_text_fallback(html: str) -> str:
    """A readable body for clients that refuse HTML."""
    text = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html, flags=re.I)
    text = re.sub(r"</(div|p|tr|h1|h2|section)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    import html as h
    text = h.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return text.strip()[:20000]


def subject_from(html: str, fallback: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if not m:
        return fallback
    import html as h
    return h.unescape(re.sub(r"\s+", " ", m.group(1))).strip() or fallback


def main() -> int:
    s = settings()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--password-file", required=True, type=Path,
                    help="path to a file containing the Gmail app password")
    ap.add_argument("--from", dest="sender", default=s.get("email_from"),
                    help="your Gmail address (or settings.email_from)")
    ap.add_argument("--to", dest="to", action="append", default=None,
                    help="recipient; repeat the flag or comma-separate for several "
                         "(falls back to settings.email_to)")
    ap.add_argument("--cc", action="append", default=None, help="copy; repeatable")
    ap.add_argument("--bcc", action="append", default=None,
                    help="blind copy; repeatable, not shown in the message")
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT,
                    help=f"HTML file to send (default: {DEFAULT_REPORT.relative_to(ROOT)})")
    ap.add_argument("--subject", help="override the subject line")
    ap.add_argument("--attach", action="store_true",
                    help="also attach the HTML file, not just inline it")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be sent and exit without connecting")
    args = ap.parse_args()

    if not args.sender:
        sys.exit("Need --from (your Gmail address), or set settings.email_from "
                 "in config/budget.json")
    sender = parseaddr(args.sender)[1] or args.sender
    if not ADDRESS.match(sender):
        sys.exit(f"--from does not look like an email address: {args.sender!r}")

    to = collect_addresses(args.to if args.to is not None else [s.get("email_to")], "--to")
    cc = collect_addresses(args.cc if args.cc is not None else [s.get("email_cc")], "--cc")
    bcc = collect_addresses(args.bcc if args.bcc is not None else [s.get("email_bcc")], "--bcc")
    if not to:
        to = [sender]          # default to mailing it to yourself
    # A name in both To and Cc would otherwise receive two copies.
    cc = [a for a in cc if a.lower() not in {x.lower() for x in to}]
    bcc = [a for a in bcc if a.lower() not in {x.lower() for x in to + cc}]
    recipients = to + cc + bcc

    report = args.report.expanduser()
    if not report.exists():
        sys.exit(f"No report at {report}\nGenerate one first:  python3 -m budget dashboard")
    html = report.read_text()
    subject = args.subject or subject_from(html, "Budget report")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(plain_text_fallback(html))
    msg.add_alternative(html, subtype="html")
    if args.attach:
        msg.add_attachment(html.encode(), maintype="text", subtype="html",
                           filename=report.name)

    size_kb = len(html) / 1024
    print(f"  report : {report}  ({size_kb:.1f} KB)")
    print(f"  subject: {subject}")
    print(f"  from   : {sender}")
    print(f"  to     : {', '.join(to)}")
    if cc:
        print(f"  cc     : {', '.join(cc)}")
    if bcc:
        print(f"  bcc    : {', '.join(bcc)}  (hidden from recipients)")
    if size_kb > 100:
        print("  note   : Gmail clips messages over ~102 KB; the reader gets a "
              "'View entire message' link.", file=sys.stderr)

    if args.dry_run:
        print("\n  --dry-run: nothing sent.")
        return 0

    password = read_password(args.password_file.expanduser())
    context = ssl_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as smtp:
            smtp.login(sender, password)
            # to_addrs explicitly: Bcc must not appear in the headers.
            smtp.send_message(msg, from_addr=sender, to_addrs=recipients)
    except smtplib.SMTPAuthenticationError:
        sys.exit("Gmail rejected the login.\n"
                 "  - The password must be a 16-character APP password, not your\n"
                 "    account password: https://myaccount.google.com/apppasswords\n"
                 "  - App passwords require 2-Step Verification to be enabled.\n"
                 "  - --from must be the same account the app password belongs to.")
    except ssl.SSLCertVerificationError:
        sys.exit(cert_help())
    except (smtplib.SMTPException, OSError) as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            sys.exit(cert_help())
        sys.exit(f"Could not send: {exc}")

    print(f"\n  sent to {len(recipients)} recipient(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
