#!/usr/bin/env python3
"""Site monitor for sxm-massage-onsite.com.

Compares the live site against the copy in this GitHub repo and checks the
rules in monitor/rules.json. Writes a Markdown report and exits with code 1
if any rule fails. Standard library only, so nothing needs installing.

Usage:
    python monitor/check_site.py [--site URL] [--report FILE]
"""
import argparse
import datetime as dt
import difflib
import hashlib
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = json.load(open(os.path.join(ROOT, "monitor", "rules.json"), encoding="utf-8"))
UA = "Mozilla/5.0 (compatible; SXM-Site-Monitor/1.0; +https://github.com/wetdiver/spaPage)"
TEXT_EXT = {".html", ".css", ".txt", ".xml", ".webmanifest", ".json", ".js", ".svg"}

RULE_NAMES = [
    "Site is up",
    "No surprise changes",
    "Your phone number",
    "Prices",
    "Nothing broken",
    "Google can see you",
    "Security lock (SSL)",
    "Redirects",
    "Private files hidden",
]


class Report:
    def __init__(self):
        self.items = []  # (level, rule, message)
        self.passed_notes = {}

    def fail(self, rule, msg):
        self.items.append(("FAIL", rule, msg))

    def warn(self, rule, msg):
        self.items.append(("WARN", rule, msg))

    def note(self, rule, msg):
        self.passed_notes[rule] = msg

    def failed(self):
        return any(i[0] == "FAIL" for i in self.items)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def fetch(url, method="GET", follow=True, timeout=30):
    """Return dict(status, headers, body, seconds, error, url)."""
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    start = time.time()
    try:
        with opener.open(req, timeout=timeout) as r:
            body = r.read() if method == "GET" else b""
            return dict(status=r.status, headers=r.headers, body=body,
                        seconds=time.time() - start, error=None, url=r.geturl())
    except urllib.error.HTTPError as e:
        return dict(status=e.code, headers=e.headers, body=b"",
                    seconds=time.time() - start, error=None, url=url)
    except Exception as e:  # DNS, timeout, TLS, connection refused...
        return dict(status=None, headers={}, body=b"",
                    seconds=time.time() - start, error=str(e)[:200], url=url)


def site_files():
    """Every file in the repo that is part of the website, as URL paths."""
    skip_dirs = set(RULES["not_site_folders"])
    skip_files = set(RULES["not_site_files"]) | set(RULES["must_be_hidden"])
    files = {}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in filenames:
            if name in skip_files:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
            files["/" + rel] = full
    return files


def page_path(file_path):
    """/faq/index.html -> /faq/ ; /index.html -> /"""
    return file_path[: -len("index.html")]


# GoDaddy adds its own "performance monitoring" script to every page it serves.
# It isn't part of the site, so it is ignored when comparing.
GODADDY_INJECT = re.compile(
    r"<script>\s*'undefined'\s*===\s*typeof _trfq.*?</script>"
    r"|<script[^>]+wsimg\.com/traffic-assets/[^>]*>\s*</script>", re.S)


def norm_text(b):
    t = b.decode("utf-8", "replace").replace("\r\n", "\n")
    return GODADDY_INJECT.sub("", t).rstrip()


def short_diff(old, new, limit=16):
    lines = list(difflib.unified_diff(old.split("\n"), new.split("\n"),
                                      "GitHub copy", "live site", n=0, lineterm=""))
    lines = [l if len(l) <= 180 else l[:180] + " …" for l in lines[2:]]
    more = len(lines) - limit
    out = "\n".join(lines[:limit])
    if more > 0:
        out += f"\n… and {more} more changed lines"
    return out


def phones_in(html):
    found = []
    for m in re.finditer(r"(?:tel:|wa\.me/|phone=)\+?([0-9][0-9\-\s().%]{6,20})", html):
        found.append(re.sub(r"\D", "", m.group(1).replace("%20", "")))
    text = re.sub(r"<[^>]+>", " ", html)
    for m in re.finditer(r"(?<![\d$])(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}(?!\d)", text):
        found.append(re.sub(r"\D", "", m.group(0)))
    out = set()
    for d in found:
        if len(d) == 10:
            d = "1" + d
        out.add(d)
    return out


def count_contact_links(html, phone):
    return (len(re.findall(r"wa\.me/" + phone, html)),
            len(re.findall(r"tel:\+?" + phone, html)))


def prices_in(html):
    return set(re.findall(r"\$\s?(\d{2,4})(?!\d)", html))


def title_of(html):
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    return m.group(1).strip() if m else None


def canonical_of(html):
    m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)', html, re.I)
    return m.group(1) if m else None


def has_noindex(html, headers):
    meta = re.search(r'<meta[^>]+name=["\']robots["\'][^>]*content=["\'][^"\']*noindex', html, re.I)
    header = "noindex" in (headers.get("X-Robots-Tag", "") or "").lower() if headers else False
    return bool(meta or header)


def links_in(html, base):
    urls = set()
    for m in re.finditer(r'(?:href|src|poster|srcset)=["\']([^"\']+)["\']', html, re.I):
        raw = m.group(1).split(",")[0].strip().split(" ")[0]
        if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        urls.add(urllib.parse.urljoin(base, raw).split("#")[0])
    return urls


def ssl_days_left(host):
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=20) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as s:
            cert = s.getpeercert()
    expires = dt.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
    return (expires - dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)).days, expires.date()


def run(site):
    rep = Report()
    site = site.rstrip("/")
    host = urllib.parse.urlparse(site).hostname
    phone = RULES["phone_digits"]
    files = site_files()
    pages = sorted(p for p in files if p.endswith("/index.html"))
    live_pages = {}

    # 1-4, 6: every page
    slowest = (0, "")
    for f in pages:
        path = page_path(f)
        url = site + path
        r = fetch(url)
        if r["status"] != 200:
            why = r["error"] or f"HTTP {r['status']}"
            rep.fail("Site is up", f"`{path}` did not load ({why})")
            continue
        if r["seconds"] > slowest[0]:
            slowest = (r["seconds"], path)
        if r["seconds"] > RULES["max_page_seconds"]:
            rep.warn("Site is up", f"`{path}` was slow: {r['seconds']:.1f}s")
        live = norm_text(r["body"])
        repo = norm_text(open(files[f], "rb").read())
        live_pages[path] = (live, r["headers"])

        if live != repo:
            rep.fail("No surprise changes",
                     f"`{path}` is different from the GitHub copy:\n```diff\n{short_diff(repo, live)}\n```")

        bad = phones_in(live) - {phone} - set(RULES.get("also_allowed_numbers", {}))
        if bad:
            rep.fail("Your phone number",
                     f"`{path}` shows a number that isn't yours: " + ", ".join("+" + b for b in sorted(bad)))
        live_wa, live_tel = count_contact_links(live, phone)
        repo_wa, repo_tel = count_contact_links(repo, phone)
        if live_wa < repo_wa:
            rep.fail("Your phone number", f"`{path}`: WhatsApp buttons missing ({live_wa} live, should be {repo_wa})")
        if live_tel < repo_tel:
            rep.fail("Your phone number", f"`{path}`: call buttons missing ({live_tel} live, should be {repo_tel})")

        lp, rp = prices_in(live), prices_in(repo)
        if lp != rp:
            parts = []
            if lp - rp:
                parts.append("new: " + ", ".join("$" + p for p in sorted(lp - rp, key=int)))
            if rp - lp:
                parts.append("gone: " + ", ".join("$" + p for p in sorted(rp - lp, key=int)))
            rep.fail("Prices", f"`{path}` prices changed ({'; '.join(parts)})")

        if title_of(live) != title_of(repo):
            rep.fail("Google can see you", f"`{path}` page title changed to: {title_of(live)!r}")
        if canonical_of(live) != canonical_of(repo):
            rep.fail("Google can see you", f"`{path}` canonical address changed to: {canonical_of(live)!r}")
        if has_noindex(live, r["headers"]):
            rep.fail("Google can see you", f"`{path}` is telling Google NOT to list it (noindex)")

    up = len(live_pages)
    if up:
        rep.note("Site is up", f"{up}/{len(pages)} pages loaded, slowest `{slowest[1]}` {slowest[0]:.1f}s")
        rep.note("Your phone number", f"+{phone} on every WhatsApp and call button, no strange numbers")
        rep.note("Prices", "same prices as the GitHub copy on every page")
        rep.note("No surprise changes", "every page and file matches the GitHub copy")

    # 2 + 5: every other file (photos, video, css, pdf, icons...)
    checked = 0
    for path, full in sorted(files.items()):
        if path.endswith("/index.html"):
            continue
        ext = os.path.splitext(path)[1].lower()
        url = site + urllib.parse.quote(path)
        checked += 1
        if ext in TEXT_EXT:
            r = fetch(url)
            if r["status"] != 200:
                rep.fail("Nothing broken", f"`{path}` missing ({r['error'] or 'HTTP ' + str(r['status'])})")
            elif norm_text(r["body"]) != norm_text(open(full, "rb").read()):
                rep.fail("No surprise changes", f"`{path}` is different from the GitHub copy:\n```diff\n"
                         f"{short_diff(norm_text(open(full, 'rb').read()), norm_text(r['body']))}\n```")
        else:
            r = fetch(url, method="HEAD")
            if r["status"] in (405, 501):
                r = fetch(url)
            if r["status"] != 200:
                rep.fail("Nothing broken", f"`{path}` missing ({r['error'] or 'HTTP ' + str(r['status'])})")
                continue
            size = len(r["body"]) if r["body"] else (r["headers"] or {}).get("Content-Length")
            local = os.path.getsize(full)
            if size is not None and str(size).isdigit() and int(size) != local:
                rep.fail("No surprise changes", f"`{path}` was replaced (live {int(size):,} bytes, GitHub {local:,} bytes)")

    # links inside the live pages: local ones not in the repo, and outside sites
    local_extra, outside = set(), set()
    for path, (html, _) in live_pages.items():
        for u in links_in(html, site + path):
            if u.startswith(RULES["site"].rstrip("/") + "/"):
                u = site + u[len(RULES["site"].rstrip("/")):]
            p = urllib.parse.urlparse(u)
            if p.hostname == host:
                lp = urllib.parse.unquote(p.path) or "/"
                if lp not in files and lp + "index.html" not in files and lp not in (page_path(x) for x in pages):
                    local_extra.add(u)
            elif p.scheme in ("http", "https") and p.hostname not in RULES["skip_link_hosts"]:
                outside.add(u)
    for u in sorted(local_extra):
        r = fetch(u, method="HEAD")
        if r["status"] != 200:
            rep.fail("Nothing broken", f"link to `{u}` is broken ({r['error'] or 'HTTP ' + str(r['status'])})")
    for u in sorted(outside):
        r = fetch(u)
        if r["status"] is None or r["status"] == 404 or r["status"] >= 500:
            rep.fail("Nothing broken", f"outside link `{u}` is broken ({r['error'] or 'HTTP ' + str(r['status'])})")
        elif r["status"] >= 400:
            rep.warn("Nothing broken", f"outside link `{u}` answered HTTP {r['status']}")
    rep.note("Nothing broken", f"{checked} files and {len(outside)} outside links checked")

    # 6: robots + sitemap
    r = fetch(site + "/robots.txt")
    if r["status"] == 200 and re.search(r"^\s*Disallow:\s*/\s*$", norm_text(r["body"]), re.M):
        rep.fail("Google can see you", "robots.txt is blocking the whole site from Google")
    r = fetch(site + "/sitemap.xml")
    if r["status"] != 200:
        rep.fail("Google can see you", f"sitemap.xml missing ({r['error'] or 'HTTP ' + str(r['status'])})")
    else:
        sm = r["body"].decode("utf-8", "replace")
        for f in pages:
            loc = RULES["site"].rstrip("/") + page_path(f)
            if f"<loc>{loc}</loc>" not in sm:
                rep.warn("Google can see you", f"`{page_path(f)}` is not listed in sitemap.xml")
    rep.note("Google can see you", "titles, canonicals, robots.txt and sitemap OK")

    # 9: private files must not be readable
    for name in RULES["must_be_hidden"]:
        r = fetch(site + "/" + name)
        if r["status"] == 200:
            rep.fail("Private files hidden", f"`/{name}` can be read by anyone")

    # 7 + 8: only for the real https site
    if site.startswith("https://"):
        try:
            days, date = ssl_days_left(host)
            if days < 0:
                rep.fail("Security lock (SSL)", f"certificate EXPIRED on {date}")
            elif days < RULES["ssl_warn_days"]:
                rep.warn("Security lock (SSL)", f"certificate expires in {days} days ({date})")
            else:
                rep.note("Security lock (SSL)", f"valid until {date} ({days} days)")
        except Exception as e:
            rep.fail("Security lock (SSL)", f"could not check certificate ({str(e)[:150]})")

        for start in (f"http://{host}/", f"https://www.{host}/", f"http://www.{host}/"):
            r = fetch(start, follow=False)
            loc = (r["headers"] or {}).get("Location", "") if r["status"] else ""
            if r["status"] in (301, 302, 307, 308) and loc.startswith(f"https://{host}"):
                continue
            if r["status"] is None and "www." in start:
                rep.warn("Redirects", f"`{start}` did not answer ({r['error']})")
            else:
                rep.fail("Redirects", f"`{start}` should send visitors to https://{host}/ "
                         f"(got {r['error'] or 'HTTP ' + str(r['status'])} {loc})")
        rep.note("Redirects", "http:// and www. both go to https://" + host)
    return rep, len(pages)


def render(rep, site, n_pages):
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M UTC")
    fails = [i for i in rep.items if i[0] == "FAIL"]
    warns = [i for i in rep.items if i[0] == "WARN"]
    key = hashlib.sha1("\n".join(sorted(f"{r}|{m}" for _, r, m in fails)).encode()).hexdigest()[:12]
    out = [f"# Site check: {urllib.parse.urlparse(site).hostname}", f"Checked {now}, {n_pages} pages", ""]
    if fails:
        out.append(f"## ❌ Problems ({len(fails)})")
        out += [f"- **{r}**: {m}" for _, r, m in fails]
        out.append("")
    if warns:
        out.append(f"## ⚠️ Warnings ({len(warns)})")
        out += [f"- **{r}**: {m}" for _, r, m in warns]
        out.append("")
    bad_rules = {r for lvl, r, _ in rep.items if lvl == "FAIL"}
    ok = [r for r in RULE_NAMES if r not in bad_rules and (r in rep.passed_notes)]
    if ok:
        out.append("## ✅ Passed")
        out += [f"- **{r}**: {rep.passed_notes[r]}" for r in ok]
        out.append("")
    out.append(f"<!-- alert-key: {key} -->")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=RULES["site"])
    ap.add_argument("--report", default="monitor-report.md")
    a = ap.parse_args()
    rep, n = run(a.site)
    text = render(rep, a.site, n)
    open(a.report, "w", encoding="utf-8").write(text + "\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        open(summary, "a", encoding="utf-8").write(text + "\n")
    print(text)
    sys.exit(1 if rep.failed() else 0)


if __name__ == "__main__":
    main()
