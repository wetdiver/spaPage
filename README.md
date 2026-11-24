# sxm-massage-onsite.com

The website files for **SXM Massage Onsite Service**, plus a monitor that watches the live site.

GitHub is the master copy. Change a file here and it is uploaded to GoDaddy automatically.
Change a file directly in GoDaddy and the monitor will flag it, and the next upload will put the GitHub version back.

## What the monitor checks (every hour)

| Rule | What it means |
|---|---|
| Site is up | All 9 pages load, each in under 5 seconds |
| No surprise changes | Every live page, photo, video and file matches this GitHub copy |
| Your phone number | +1 721 554 0065 is on every WhatsApp and call button, and no other number appears |
| Prices | Every price on every page is the same as the GitHub copy |
| Nothing broken | All photos, videos, the host card PDF and outside links work |
| Google can see you | Titles and canonicals unchanged, no hidden "noindex", robots.txt and sitemap OK |
| Security lock (SSL) | Warns 14 days before the https certificate expires |
| Redirects | http:// and www. both send visitors to https://sxm-massage-onsite.com |
| Private files hidden | `.htaccess` can't be read by visitors |

## How you hear about problems

When something fails, the monitor opens an **issue** in this repo titled "⚠️ Problem on sxm-massage-onsite.com", and GitHub emails it to you.
It won't email you again every hour for the same problem. It only writes again if the problem changes, and it closes the issue with an "all clear" once everything passes.

Make sure email is on: GitHub → your picture → Settings → Notifications → "Email" ticked for Issues/Watching.

## Run a check right now

Actions tab → **Site monitor** → **Run workflow**.

## Change the rules

Edit `monitor/rules.json`, for example a new phone number, another allowed number, the speed limit or the SSL warning days.
Prices and page content need no editing: the monitor compares against whatever is in GitHub, so update the page here and the monitor follows.

## Uploading to GoDaddy

`.github/workflows/deploy.yml` uploads changed site files over FTP using three repo secrets: `FTP_SERVER`, `FTP_USERNAME` and `FTP_PASSWORD`.
The monitor code, `.github` and this README are never uploaded. To force a full upload: Actions → **Deploy to GoDaddy** → **Run workflow**.

## Good to know

GitHub pauses scheduled checks on a repo that has had no commits for 60 days, and emails you first. Any small commit, or clicking "Enable workflow" in the Actions tab, turns them back on.
