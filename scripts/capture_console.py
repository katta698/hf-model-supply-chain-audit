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


def capture(page, url, path, settle_ms):
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    # Console pages render asynchronously well after domcontentloaded; a fixed
    # settle beats guessing at a selector that differs per service.
    page.wait_for_timeout(settle_ms)
    page.screenshot(path=str(path), full_page=False)
    return path.stat().st_size


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
                size = capture(page, url, path, args.settle_ms)
                print(f"  {name:<20} {path}  ({size / 1024:.0f} KB)")
            except Exception as exc:
                failures += 1
                print(f"  {name:<20} FAILED: {type(exc).__name__}: {str(exc)[:90]}")

        browser.close()

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
