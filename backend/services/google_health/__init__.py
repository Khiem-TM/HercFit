"""Google Health API (v4) integration: OAuth connection, synchronization and mapping.

Google Fit's REST API stopped accepting new developers in 2024 and is retired at
the end of 2026; the Google Health API is its cloud successor. Module layout:

* client.py      HTTP calls to health.googleapis.com and Google's OAuth endpoints
* oauth.py       consent URL, signed state, token exchange/refresh/revocation
* connection.py  connect/callback/status/consent/disconnect for one user
* mappers.py     pure conversions from provider JSON to HercFit rows
* sync.py        leased, idempotent synchronization of one connection
* scheduler.py   the in-process loop and `python -m services.google_health`
"""
