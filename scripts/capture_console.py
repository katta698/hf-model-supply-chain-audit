"""Screenshot AWS console pages from the current CLI credentials.

Lab evidence usually ends up as terminal output, which is reproducible but
unconvincing to anyone who wants to see the console. This bridges that: it
exchanges the current temporary credentials for a console sign-in token via
the AWS federation endpoint, drives headless Chromium to each page, and saves
a screenshot. No interactive SSO, no stored browser profile, no passwords.

Requires temporary credentials (assume-role or SSO), which is what you have
when `aws sts get-caller-identity` shows an assumed-role ARN. Long-lived IAM
user keys will not work -- the federation endpoint rejects them.

Usage:
    python scripts/capture_console.py --out docs/screenshots \
        vpc:vpcs s3:buckets lambda:functions

    python scripts/capture_console.py --url \
        "https://console.aws.amazon.com/ec2/home?region=us-east-1#RouteTables:" \
        --name route-tables
"""

import argparse
import json
import pathlib
import sys
import urllib.parse
import urllib.request

import boto3

# Short names for pages worth capturing in a lab write-up.
SHORTCUTS = {
    "vpc:vpcs": "https://console.aws.amazon.com/vpcconsole/home?region={region}#vpcs:",
    "vpc:routes": "https://console.aws.amazon.com/vpcconsole/home?region={region}#RouteTables:",
    "vpc:endpoints": "https://console.aws.amazon.com/vpcconsole/home?region={region}#Endpoints:",
    "vpc:subnets": "https://console.aws.amazon.com/vpcconsole/home?region={region}#subnets:",
    "s3:buckets": "https://console.aws.amazon.com/s3/home?region={region}",
    "lambda:functions": "https://console.aws.amazon.com/lambda/home?region={region}#/functions",
    "iam:roles": "https://console.aws.amazon.com/iam/home#/roles",
    "cost:explorer": "https://console.aws.amazon.com/costmanagement/home#/cost-explorer",
    "billing:budgets": "https://console.aws.amazon.com/billing/home#/budgets",
}

FEDERATION = "https://signin.aws.amazon.com/federation"
CONSOLE_HOME = "https://console.aws.amazon.com/"


def signin_url(destination, duration=3600):
    """Build a console URL that logs in and lands on `destination`."""
    creds = boto3.Session().get_credentials()
    if creds is None:
        raise SystemExit("no AWS credentials found")
    frozen = creds.get_frozen_credentials()
    if not frozen.token:
        raise SystemExit(
            "federation needs temporary credentials (assume-role or SSO); "
            "long-lived IAM user keys are rejected by the endpoint"
        )

    session = json.dumps(
        {
            "sessionId": frozen.access_key,
            "sessionKey": frozen.secret_key,
            "sessionToken": frozen.token,
        }
    )
    token_url = f"{FEDERATION}?" + urllib.parse.urlencode(
        {"Action": "getSigninToken", "SessionDuration": duration, "Session": session}
    )
    with urllib.request.urlopen(token_url, timeout=30) as response:
        token = json.load(response)["SigninToken"]

    return f"{FEDERATION}?" + urllib.parse.urlencode(
        {
            "Action": "login",
            "Issuer": "lab-capture",
            "Destination": destination,
            "SigninToken": token,
        }
    )


def resolve(target, region):
    if target in SHORTCUTS:
        return SHORTCUTS[target].format(region=region), target.replace(":", "-")
    if target.startswith("http"):
        return target, "page"
    raise SystemExit(
        f"unknown target {target!r}. Known: {', '.join(sorted(SHORTCUTS))}"
    )


# Redaction draws opaque boxes over the offending elements rather than editing
# their text.
#
# Editing text does not survive: the console is a React app, so it re-renders
# and restores the original. A MutationObserver that re-applies only makes the
# page flap between states, and the screenshot lands on whichever frame it
# lands on -- while a check run a moment later sees it clean. That produced a
# PNG containing the account id while verification reported success, which is
# worse than no verification at all.
#
# Overlays are appended to documentElement, outside the React root, so nothing
# re-renders them away and nothing we do triggers a re-render in the first
# place. Verification is then geometric: every element whose text matches must
# be covered by an overlay.
REDACT_JS = """
({patterns, selectors}) => {
  const MARK = 'data-redact-overlay';
  document.querySelectorAll('[' + MARK + ']').forEach(e => e.remove());

  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TITLE']);

  // Walk text nodes, not elements. Matching only childless elements misses
  // the common console pattern of a container holding both a copy-button and
  // a bare text node -- which is exactly where the account id lives.
  const matches = () => {
    const res = patterns.map(p => new RegExp(p, 'gi'));
    const hit = new Set();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const text = (node.nodeValue || '').trim();
      if (!text) continue;
      const parent = node.parentElement;
      if (!parent || SKIP.has(parent.tagName)) continue;
      if (res.some(r => { r.lastIndex = 0; return r.test(text); })) hit.add(parent);
    }
    for (const sel of selectors) {
      for (const el of document.querySelectorAll(sel)) hit.add(el);
    }
    return [...hit];
  };

  window.__redactTargets = matches;

  let drawn = 0;
  for (const el of matches()) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;        // not rendered
    const box = document.createElement('div');
    box.setAttribute(MARK, '');
    Object.assign(box.style, {
      position: 'fixed',
      left: (r.left - 1) + 'px', top: (r.top - 1) + 'px',
      width: (r.width + 2) + 'px', height: (r.height + 2) + 'px',
      background: '#000', zIndex: '2147483647', pointerEvents: 'none',
    });
    document.documentElement.appendChild(box);
    drawn++;
  }
  return drawn;
}
"""

# Geometric check: anything still showing a sensitive value must sit under an
# overlay. Text-based checking cannot work here, because the text is
# deliberately left in place and only covered.
VERIFY_JS = """
() => {
  const boxes = [...document.querySelectorAll('[data-redact-overlay]')]
    .map(o => o.getBoundingClientRect());
  const covered = (r) => boxes.some(b =>
    b.left <= r.left + 1 && b.top <= r.top + 1 &&
    b.right >= r.right - 1 && b.bottom >= r.bottom - 1);

  const uncovered = [];
  for (const el of (window.__redactTargets ? window.__redactTargets() : [])) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    // Only the visible viewport reaches the screenshot.
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
    if (!covered(r)) uncovered.push((el.textContent || '').trim().slice(0, 60));
  }
  return uncovered;
}
"""


# Console elements that carry identity but whose contents cannot be predicted
# from credentials -- notably the SSO display name, which is neither the ARN
# principal nor a full email address.
REDACT_SELECTORS = [
    '[data-testid="account-label"]',
    '[data-testid="awsc-nav-account-menu-button"]',
    "#nav-usernameMenu",
]


def redaction_patterns(identity, extra):
    """Regexes for values that must never appear in a published screenshot."""
    account = identity["Account"]
    # arn:aws:sts::123:assumed-role/<PermissionSet>/<user>
    arn_tail = identity["Arn"].rsplit("/", 1)[-1]

    patterns = [
        re_escape(account),  # this account, wherever it appears
        r"\b\d{12}\b",  # any other account id on the page
        re_escape(arn_tail),  # the signed-in principal
        r"[\w.+-]+@[\w-]+\.[\w.-]+",  # email addresses
        r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",  # access key ids
        r"AWSReservedSSO_[\w-]+",  # permission set names
    ]
    return patterns + list(extra)


def re_escape(value):
    import re

    return re.escape(value)


def each_frame(page, js, arg=None):
    """Run js in every frame. Console pages render panels inside iframes, so
    touching only the main frame silently misses whatever is in them.

    Returns (results, inaccessible) -- cross-origin frames cannot be scripted
    and are reported rather than ignored.
    """
    results, inaccessible = [], 0
    for frame in page.frames:
        try:
            results.append(frame.evaluate(js, arg) if arg is not None else frame.evaluate(js))
        except Exception:
            inaccessible += 1
    return results, inaccessible


def uncovered(page):
    """Anything still showing a sensitive value, across every frame."""
    results, _ = each_frame(page, VERIFY_JS)
    return [item for frame_result in results for item in frame_result]


def capture(page, url, path, settle_ms, patterns, literals):
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    # Console pages render asynchronously well after domcontentloaded; a fixed
    # settle beats guessing at a selector that differs per service.
    page.wait_for_timeout(settle_ms)

    redacted = 0
    if patterns:
        payload = {"patterns": patterns, "selectors": REDACT_SELECTORS}
        each_frame(page, REDACT_JS, payload)

        # Late-arriving content would land uncovered, so settle and redraw.
        page.wait_for_timeout(1500)
        counts, blocked = each_frame(page, REDACT_JS, payload)
        redacted = sum(counts)
        if blocked:
            print(f"       note: {blocked} frame(s) not scriptable (cross-origin)")

        missed = uncovered(page)
        if missed:
            raise RuntimeError(
                "redaction incomplete, refusing to screenshot: " + "; ".join(missed[:5])
            )

    page.screenshot(path=str(path), full_page=False)

    # Check again after the capture. The first check only proves the page was
    # covered at that instant; anything that moved or re-rendered in between
    # would be in the PNG regardless.
    if patterns:
        missed = uncovered(page)
        if missed:
            path.unlink(missing_ok=True)
            raise RuntimeError(
                "page changed during capture, screenshot discarded: "
                + "; ".join(missed[:5])
            )

    return path.stat().st_size, redacted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="*", help=f"any of: {', '.join(sorted(SHORTCUTS))}")
    ap.add_argument("--url", help="capture an arbitrary console URL instead")
    ap.add_argument("--name", default="page", help="filename stem when using --url")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--out", default="docs/screenshots")
    ap.add_argument("--width", type=int, default=1680)
    ap.add_argument("--height", type=int, default=1050)
    ap.add_argument("--settle-ms", type=int, default=6000)
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument(
        "--redact-extra",
        action="append",
        default=[],
        metavar="REGEX",
        help="additional pattern to mask; repeatable",
    )
    ap.add_argument(
        "--no-redact",
        action="store_true",
        help="capture raw. Only for screenshots that stay private.",
    )
    args = ap.parse_args()

    jobs = []
    if args.url:
        jobs.append((args.url, args.name))
    for target in args.targets:
        jobs.append(resolve(target, args.region))
    if not jobs:
        raise SystemExit("nothing to capture; pass targets or --url")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("pip install playwright && playwright install chromium")

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    identity = boto3.client("sts").get_caller_identity()
    print(f"account {identity['Account']}  region {args.region}")
    print(f"as      {identity['Arn']}\n")

    patterns = [] if args.no_redact else redaction_patterns(identity, args.redact_extra)
    if patterns:
        print(f"redacting {len(patterns)} pattern(s) in-page before capture")
    else:
        print("WARNING: --no-redact; the account id and principal will be visible")

    # Exact strings checked for after redaction. Patterns can be wrong;
    # these are known-sensitive literals that must not survive.
    literals = (
        []
        if args.no_redact
        else [identity["Account"], identity["Arn"].rsplit("/", 1)[-1]]
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(
            viewport={"width": args.width, "height": args.height},
            device_scale_factor=2,  # legible when embedded in a document
        )
        page = context.new_page()

        # One federated login, reused for every page in this run.
        page.goto(signin_url(CONSOLE_HOME), wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(3000)
        print(f"signed in: {page.url[:60]}\n")

        failures = 0
        for url, name in jobs:
            path = out / f"{name}.png"
            try:
                size, hits = capture(
                    page, url, path, args.settle_ms, patterns, literals
                )
                note = f"{hits} redactions" if patterns else "NOT REDACTED"
                print(f"  {name:<20} {path}  ({size / 1024:.0f} KB, {note})")
            except Exception as exc:
                failures += 1
                print(f"  {name:<20} FAILED: {type(exc).__name__}: {str(exc)[:90]}")

        browser.close()

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
