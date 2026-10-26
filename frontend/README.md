# Mythic — Olympus Kinetic

Vue 3 + TypeScript landing page adapted from the supplied Stitch screen.

Quick start from the repository root (no Docker or backend required):

```sh
./dev_up.sh --frontend-only
# Open http://localhost:5173; Ctrl+C stops the server.

./dev_up.sh --frontend-only -d
./dev_up.sh status --frontend-only
./dev_up.sh logs --frontend-only
./dev_up.sh down --frontend-only
```

Set `FRONTEND_PORT=5174` to use another port. The launcher installs dependencies
with `npm ci` when Vite is missing and writes output to `frontend.log`.
The existing `./dev_up.sh up` command also starts this landing page with the backend.

Alternatively, run these commands inside `frontend`:

```sh
npm install
npm run dev
npm run build
```

The page includes responsive navigation, selectable agent protocols, expandable
knowledge rows and an accessible email form. The form stores a request locally
under `mythic.access-request`; it does not send emails or register an account.
The saved request can be removed directly in the form.

Original HTML, screenshot and asset provenance are in
`../design/stitch/10314870271573147429/`. All three artwork files are served locally
from `public/images/`. Fonts are loaded from Google Fonts. Tailwind compiles at
build time; no Tailwind CDN script is required.

The previous dashboard, views, router, stores, API service and related
application dependencies have been removed. Backend work is separate.

## Onboarding

New authenticated users (`is_onboarding=false`) are routed to `/onboarding`.
The four steps collect profile/activity notes, optional initial measurements,
optional goal, and explicit confirmation. Completed users (`is_onboarding=true`)
are routed to `/chat`, including when visiting `/onboarding` directly.

The screen submits one `POST /api/profile/onboarding` using the existing atomic
backend contract. Omitted measurement/goal sections are left out of the payload.
Activity and user-provided notes use `personal_info.activity` and
`personal_info.preferences`; other fields in those groups are preserved.
Measurements use backend precision, and numeric goal targets use the `eq`
discriminator with `kg` units. An existing active goal is kept.

Drafts stay in component memory; nothing is saved before final confirmation.
Uncertain network outcomes retain the same request and idempotency key for retry.
Editing is unlocked after a definitive validation failure. A successful save
refreshes profile data and enters the chat workspace.

