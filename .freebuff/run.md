# Run doc — LeetPulse preview worktree

Monorepo: Turborepo + pnpm. The viewable app is the Next.js frontend at `apps/frontend`
(dev server, port 3001). The Express backend (`apps/backend`, port 3000) needs Postgres +
Redis + Gemini keys; it is NOT required to view the UI, but the frontend proxies `/api/*`
to it via `BACKEND_URL` (default `http://localhost:3000`), so data pages show empty/error
states when the backend is down.

## Reproduce the uncommitted artifacts

A fresh worktree lacks the gitignored env files. Copy them from the main checkout
(`/Users/tajbaba/Developer/LeetPulse`) — values are machine/user-specific, so copy, don't
symlink:

```bash
cp /Users/tajbaba/Developer/LeetPulse/apps/frontend/.env apps/frontend/.env
cp /Users/tajbaba/Developer/LeetPulse/apps/backend/.env  apps/backend/.env
```

Then install dependencies (pnpm 9.15.0, per `packageManager` in root package.json):

```bash
pnpm install --frozen-lockfile
```

`packages/db` postinstall runs `prisma generate` automatically.

## Run the dev server

```bash
cd apps/frontend && pnpm dev   # Next.js 16 dev server on http://localhost:3001
```

- Default port is 3001 (hardcoded in `apps/frontend/package.json`); check it's free first
  (`lsof -nP -iTCP:3001 -sTCP:LISTEN`) and pick another port if not.
- This worktree is nested inside the main checkout, so Next.js warns that it detected
  multiple `pnpm-workspace.yaml` files and picked the outer root. Harmless — Turbopack still
  compiles the worktree's own `apps/frontend/src` (visible in chunk URLs).

### Detached launch (survives the terminal)

A plain `nohup ... &` background job gets reaped when the shell exits. Run it under launchd
instead (this also needs the full PATH — launchd does not inherit the shell's; node/pnpm live
at `/Users/tajbaba/.nvm/versions/node/v24.9.0/bin`):

```bash
launchctl submit -l leetpulse-preview-0d7a00fd -- /bin/sh -c \
  "export PATH=/Users/tajbaba/.nvm/versions/node/v24.9.0/bin:\$PATH; \
   cd /Users/tajbaba/Developer/LeetPulse/.freebuff/worktrees/0d7a00fd-4bdb-4929-aea2-43b6ec111fa5/apps/frontend && \
   exec pnpm dev > /Users/tajbaba/Developer/LeetPulse/.freebuff/preview-0d7a00fd-4bdb-4929-aea2-43b6ec111fa5.log 2>&1"
```

Check it's up: `launchctl print gui/$(id -u)/leetpulse-preview-0d7a00fd | grep 'pid ='`, then
`curl -s -o /dev/null -w '%{http_code}' http://localhost:3001` (expect 200). Teardown when
done: `launchctl remove leetpulse-preview-0d7a00fd`.
