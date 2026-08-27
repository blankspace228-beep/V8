# Purple Paper V8 — Network

Purple Paper V8 is a fake-money stock + crypto trading game with server-backed user accounts, Owner/Admin/Moderator/Coach/Player roles, trader tiers, achievements, live Alpaca market data, journals, and Purple Coach.

## What changed in V8

- Per-user server accounts: each login has isolated cash, positions, orders, fills, journal, coach history, tier volume, and reviews.
- First-account Owner setup is fixed and forced by the login shell when a database is fresh.
- Hosted Owner protection: when `HOSTED_MODE=1`, set `OWNER_SETUP_CODE` before making the server public. The first signup must enter that code before it can become Owner.
- Owner-only shared market-data configuration. Players use the server's market feed without receiving the Owner's Alpaca secret.
- Authenticated WebSockets: live account updates are scoped to the signed-in user instead of broadcasting one player's portfolio to everybody.
- Purple Coach carries a persistent notice that it can make mistakes or miss context and that the player makes the final trade decision.
- V8 PWA cache is network-first so older V7 pages do not hide a fresh Owner setup screen.
- Progress celebration state is scoped by user ID on each browser.

## Windows local play

Run `PLAY_PURPLE_PAPER.bat`. This starts a private local server and opens Purple Paper in its desktop window.

On a brand-new V8 database, the login panel should immediately say **OWNER SETUP**. Create the first account and it becomes the protected Owner.

## Run as a LAN server

Run `HOST_PURPLE_PAPER_NETWORK.bat`. Other devices on your Wi-Fi can open:

`http://YOUR-PC-IP:8787`

This is server-backed and multi-user, but it is only reachable where your network/firewall allows it.

## Public hosted mode

V8 includes a `Dockerfile`, so it can be deployed to a Docker-compatible cloud host. For public hosting, set environment variables like:

- `HOSTED_MODE=1`
- `COOKIE_SECURE=1`
- `DATABASE_PATH=/data/purple_paper_network.db` (use a persistent disk/volume)
- `OWNER_SETUP_CODE=<a long random code only you know>`
- `ALPACA_API_KEY=<server market-data key>`
- `ALPACA_SECRET_KEY=<server market-data secret>`
- `ALPACA_FEED=iex`

Then open the HTTPS URL from Windows or iPhone. The first account requires the Owner setup code and becomes Owner. Every later signup becomes Player unless promoted.

### Important hosting note

The included hosted database is SQLite on the server. That is appropriate for a single Purple Paper server instance and multiple users/devices. If you later want multiple application servers running in parallel, move persistence to PostgreSQL before horizontal scaling.

## Purple Coach notice

Purple Coach analyzes simulated behavior and can help compare risk, concentration, execution, and trading process. It can make mistakes, miss context, and should not be treated as certainty. Purple Paper never gives the coach authority to submit an order; the player makes the final trade decision.

## Fake-money boundary

All Purple Paper trades remain simulated. Alpaca is used only as a market-data source in this build. Practice credits are non-redeemable and no cash-out system is connected.
