# Thesys Integration Notes

This file documents the full design and debugging history of the Thesys integration in this fork of Dify. It is intentionally more detailed than the README.

## Goal

The target outcome was:

- support Thesys as a first-class model provider inside Dify
- render Thesys C1 / OpenUI responses as generative UI instead of raw markup
- make the fork runnable on plain `http://localhost` from a repo-backed Docker stack
- stop relying on the temporary `localhost:3000` host dev server split
- leave a clean enough repo state for external review and future marketplace publication

## Final outcome

The fork now provides:

- a dedicated `Thesys` provider plugin under `local-plugins/thesys`
- frontend runtime detection between Markdown and C1/OpenUI responses
- repo-backed Docker source images for `api` and `web`
- automatic bundled-plugin bootstrap for new tenants when using the source Docker stack
- a unified local path on plain `http://localhost` when started with the source compose overlay

The command for the forked stack is:

```bash
cd docker
cp .env.example .env
docker compose -f docker-compose.yaml -f docker-compose.source.yaml up -d --build
```

## High-level design decisions

### 1. Use a dedicated Thesys provider instead of teaching every OpenAI-compatible path about Thesys

Reason:

- Thesys is OpenAI-compatible at the request shape level, but its endpoint and behavior are opinionated enough that overloading the generic OpenAI-compatible plugin made the integration brittle.
- A dedicated provider makes the UI and configuration clearer for end users.
- It also avoids having long-term product behavior depend on local runtime patches to a marketplace plugin.

Decision:

- build a dedicated `Thesys` plugin in `local-plugins/thesys`
- keep the generic OpenAI-compatible plugin only as a temporary bring-up bridge

### 2. Detect the response format at runtime from content

Reason:

- existing Dify message models did not have a reliable explicit `response_format` field flowing end-to-end
- waiting for a backend schema change would have slowed the initial integration

Decision:

- detect whether a response is normal Markdown or Thesys C1/OpenUI from the returned content
- use the existing Markdown renderer for normal text
- switch to the Thesys C1 renderer only when the response clearly matches the C1/OpenUI format

### 3. Keep upstream Docker compose intact and add a source overlay instead

Reason:

- the stock Dify repo and image-based compose flow is useful as a comparison baseline
- directly rewriting `docker-compose.yaml` would make the fork harder to compare with upstream and more disruptive to rebase

Decision:

- keep `docker/docker-compose.yaml` as the stock image-based path
- add `docker/docker-compose.source.yaml` as the repo-backed overlay
- document clearly that the fork features require the source overlay

### 4. Auto-install the Thesys plugin from repo source for new tenants

Reason:

- manually uploading a local plugin into every new environment is fragile
- relying on long-lived plugin daemon volumes is not reproducible

Decision:

- add backend support for "bundled local plugin packages"
- install the Thesys plugin from repo source when a tenant is created in the source-backed Docker flow

### 5. Prefer the stable Next.js runtime path in Docker over the experimental Vinext path

Reason:

- the self-hosted Docker entrypoint already defaults to the Next.js standalone target
- the Vinext artifact is only used when `EXPERIMENTAL_ENABLE_VINEXT=true`
- forcing the web image build to succeed on Vinext blocked the unified stack on a dependency-resolution issue that the default runtime did not need

Decision:

- create `web/Dockerfile.source` that builds the real runtime target used in the source stack
- leave Vinext as future work instead of blocking the entire fork on it

## Chronological implementation history

### Phase 1: Explore the repo and identify the real integration points

Initial findings:

- provider credentials were already schema-driven, so custom provider setup was feasible
- answer rendering flowed mainly through:
  - `web/app/components/base/chat/chat/answer/basic-content.tsx`
  - `web/app/components/base/chat/chat/answer/agent-content.tsx`
- those paths were Markdown-oriented and had no native Thesys/OpenUI renderer

Conclusion:

- the first permanent product work belonged in the frontend answer rendering path

### Phase 2: Add frontend C1 rendering

Implemented:

- `web/app/components/base/chat/chat/answer/detect-response-format.ts`
- `web/app/components/base/chat/chat/answer/response-renderer.tsx`
- `web/app/components/base/chat/chat/answer/c1-response.tsx`

Integrated with:

- `web/app/components/base/chat/chat/answer/basic-content.tsx`
- `web/app/components/base/chat/chat/answer/agent-content.tsx`
- `web/app/layout.tsx`

Behavior:

- normal text still renders through the existing Markdown path
- C1/OpenUI payloads render through the Thesys C1 component
- Thesys actions are mapped back into Dify's existing send/action flow
- `open_url` actions are supported

Tests added for:

- response-format detection
- basic content rendering
- agent content rendering
- C1 response behavior

### Phase 3: Fix frontend dependency and build issues

### Roadblock: missing `@base-ui/react/alert-dialog`

Symptom:

- the local frontend failed with `Module not found: Can't resolve '@base-ui/react/alert-dialog'`

Fix:

- update workspace/frontend dependency wiring in:
  - `web/package.json`
  - `pnpm-workspace.yaml`

### Roadblock: `loro-crdt` WebAssembly loader failure

Symptom:

- Webpack/Turbopack failed on `.wasm`
- error referenced `loro-crdt/bundler/loro_wasm_bg.wasm`

Fix:

- update `web/next.config.ts` to enable async WebAssembly and `.wasm` handling
- make the C1 renderer load in a way that avoided dragging the dependency into the wrong build path

### Related cleanup

Also updated:

- local frontend config behavior in `web/next.config.ts`
- dev-only code inspector handling
- Turbopack root handling for the repo layout

### Phase 4: Temporary provider bridge through the marketplace OpenAI-compatible plugin

This phase was a bring-up bridge, not the intended end state.

Reason:

- the dedicated Thesys plugin did not exist yet
- we needed a fast path to verify real Thesys calls against Dify

### Roadblock: credential validation rejected a successful Thesys response

Symptom:

- the `OpenAI-API-compatible` plugin returned validation errors even though Thesys answered successfully
- the plugin treated a `201` response as failure

Fix:

- patch the installed runtime plugin so validation accepted successful `2xx` responses
- add regression tests inside the plugin's test suite

### Roadblock: plugin streaming behavior did not match Thesys behavior

Symptom:

- Thesys sometimes returned a one-shot `chat.completion` body even when the caller requested `stream=true`
- some streamed frames also included SSE metadata such as `id:` and similar lines

Fix:

- patch the installed runtime plugin to:
  - accept one-shot `chat.completion` bodies on the streaming path
  - parse SSE frames more defensively
- add regression tests inside the plugin container

Status:

- this was always intended as temporary scaffolding
- once the dedicated `Thesys` plugin existed, this runtime patch was reverted

### Phase 5: Fix the "blank response" bug stack

The most confusing production issue was that model calls succeeded, but Dify sometimes showed an empty assistant bubble or later persisted an empty message.

This turned out to be multiple bugs at different layers.

### Roadblock: frontend history fetch overwrote a streamed answer with an empty saved answer

Symptom:

- the response streamed in
- then the UI later showed a blank/empty bubble

Cause:

- the frontend merged a history payload whose `answer` was empty over a non-empty in-memory streamed message

Fix:

- patch `web/app/components/base/chat/chat/hooks.ts`
- preserve non-empty streamed content when the fetched history answer is blank
- add frontend regression coverage

### Roadblock: plugin/backend persistence still saved `answer: ""`

Symptom:

- API history still returned messages with empty `answer`
- so the bug was not only in the frontend

Cause:

- the intermediate plugin path was not always handling Thesys response bodies correctly

Fix:

- extend the temporary OpenAI-compatible runtime patch as described above

### Roadblock: backend `message_end` clobbered accumulated streamed content

Symptom:

- even after fixing the frontend merge behavior, saved history could still show `answer: ""`

Cause:

- the backend task pipeline accumulated streamed chunks correctly
- but an empty final `message_end` payload replaced the accumulated result during persistence

Permanent fix:

- patch `api/core/app/task_pipeline/easy_ui_based_generate_task_pipeline.py`
- merge the final payload with the accumulated streamed result instead of blindly replacing it when the final content is empty

This was one of the true root-cause fixes.

### Mistake made during debugging

At one point, a repo backend file was copied directly into the stock Docker API container.

That caused:

- a dependency mismatch
- `ModuleNotFoundError: No module named 'graphon'`
- a broken live API path
- follow-on `502` failures until nginx was restarted against the healthy container topology

Recovery:

- stop forcing repo files directly into the stock image
- patch only version-matched runtime files when necessary
- restart nginx after the API container topology changed

This mistake is important to document because it was real debugging debt during the integration.

### Phase 6: Build the dedicated Thesys provider plugin

Implemented under:

- `local-plugins/thesys/`
- packaging helper in `scripts/package-thesys-plugin.sh`

Plugin design:

- dedicated `Thesys` provider
- fixed Thesys `/v1/embed` behavior
- Thesys-specific validation and response handling
- stripped-down surface compared to a generic provider plugin

### Roadblock: malformed local plugin package

Symptom:

- upload failed with `_assets: is a directory`

Cause:

- the first `.difypkg` archive included directory entries that the plugin daemon did not expect in that shape

Fix:

- update the packaging script so the archive contains the right file layout
- rebuild the plugin package

### Roadblock: signature verification blocked local plugin install

Symptom:

- plugin install failed because unsigned plugin verification was enabled

Fix for local development:

- disable forced signature verification in the local/dev flow
- later encode that behavior in the source compose overlay for the plugin daemon

### Roadblock: local package install hit a backend `500`

Symptom:

- the plugin upload appeared in the UI
- install then failed with internal server error

Cause:

- Dify's local-package install path re-decoded an already-local identifier

Permanent fix:

- patch `api/services/plugin/plugin_service.py`
- add regression coverage for local package installation

Result:

- the dedicated Thesys plugin could be installed normally

### Phase 7: Unify the environment on plain `localhost`

The system worked before this phase, but in a split form:

- `localhost:3000` = host Next dev server from repo source
- `localhost` = Docker frontend + Docker backend

That was enough for development, but not the intended end state.

### Design decision: no shortcuts

The final goal was a serious, reviewable, repo-backed environment. That meant:

- no dependence on the temporary host dev server
- no hidden runtime-only behavior required to understand the fork
- no nginx hack that simply forwarded plain `localhost` to the host dev server

### Implemented source-Docker path

New files:

- `.dockerignore`
- `api/Dockerfile.source`
- `web/Dockerfile.source`
- `docker/docker-compose.source.yaml`

Behavior:

- `api` and `web` build from repo source
- plugin daemon runs with local unsigned plugin installation enabled in the source overlay
- plain `localhost` becomes the real path for the fork when using the source overlay

### Roadblock: Docker build context was too large

Symptom:

- the source build sent an unnecessarily huge context into Docker

Fix:

- add `.dockerignore`
- exclude caches, local volumes, build outputs, and bulky local artifacts
- keep `local-plugins/` included because the source API image needs it

### Roadblock: Vinext failed on `lucide-react/dynamicIconImports`

Symptom:

- the stock web Dockerfile failed during `pnpm build && pnpm build:vinext`
- Vinext/Rolldown could not resolve `lucide-react/dynamicIconImports.mjs` from `@thesysai/genui-sdk`

What was tried first:

- Vite aliasing in `web/vite.config.ts`
- a pre-resolve Vite plugin

Why those were not enough:

- the failure happened early enough in Vinext/Rolldown that the expected app-level alias behavior was not enough to make the source stack dependable

Final design choice:

- do not block the unified source Docker stack on the experimental Vinext artifact
- create `web/Dockerfile.source` that builds the Next standalone target used by the production entrypoint by default
- keep a placeholder `dist/standalone` directory so the entrypoint layout remains satisfied

This was an intentional product/runtime decision, not a shortcut:

- the container entrypoint already runs the Next build unless `EXPERIMENTAL_ENABLE_VINEXT=true`
- therefore the real user-facing runtime path is preserved

### Bundled plugin bootstrap for fresh tenants

Implemented:

- config in `api/configs/feature/__init__.py`
  - `PLUGIN_AUTO_INSTALL_LOCAL_PACKAGES`
  - `PLUGIN_AUTO_INSTALL_TIMEOUT`
  - `PLUGIN_AUTO_INSTALL_STRICT`
- service in `api/services/plugin/bundled_plugin_service.py`
- tenant hook in `api/services/account_service.py`

Behavior:

- repo-local plugin directories or `.difypkg` files can be auto-packaged and installed
- new tenants in the source Docker flow bootstrap the bundled Thesys plugin automatically

Tests:

- `api/tests/unit_tests/services/plugin/test_bundled_plugin_service.py`
- `api/tests/unit_tests/services/test_account_service.py`

### Final environment cleanup

After the unified source stack was verified:

- the old host Next dev server on `127.0.0.1:3000` was stopped
- plain `http://localhost` became the single correct local path for the unified environment

## Permanent repo changes by area

### Frontend

Primary permanent frontend changes include:

- conditional response rendering for Markdown vs C1/OpenUI
- Thesys C1 component integration
- action bridging from generative UI back into Dify
- styling/bootstrap support for the Thesys renderer
- stream/history merge protection to preserve non-empty streamed results
- dependency/config updates for the renderer and build path

Representative files:

- `web/app/components/base/chat/chat/answer/detect-response-format.ts`
- `web/app/components/base/chat/chat/answer/response-renderer.tsx`
- `web/app/components/base/chat/chat/answer/c1-response.tsx`
- `web/app/components/base/chat/chat/answer/basic-content.tsx`
- `web/app/components/base/chat/chat/answer/agent-content.tsx`
- `web/app/components/base/chat/chat/hooks.ts`
- `web/app/layout.tsx`
- `web/next.config.ts`
- `web/package.json`
- `pnpm-workspace.yaml`

### Backend

Primary permanent backend changes include:

- preserving accumulated streamed content during final message persistence
- fixing local package installation in the plugin service
- adding bundled-plugin bootstrap support for source Docker environments

Representative files:

- `api/core/app/task_pipeline/easy_ui_based_generate_task_pipeline.py`
- `api/services/plugin/plugin_service.py`
- `api/configs/feature/__init__.py`
- `api/services/plugin/bundled_plugin_service.py`
- `api/services/account_service.py`

### Plugin

Primary permanent plugin work:

- dedicated `Thesys` provider plugin under `local-plugins/thesys`
- package helper in `scripts/package-thesys-plugin.sh`

Representative files:

- `local-plugins/thesys/manifest.yaml`
- `local-plugins/thesys/provider/thesys.yaml`
- `local-plugins/thesys/models/llm/llm.py`
- `scripts/package-thesys-plugin.sh`

### Docker and environment

Primary permanent Docker changes:

- source-built API image
- source-built web image
- source compose overlay
- trimmed Docker build context

Representative files:

- `.dockerignore`
- `api/Dockerfile.source`
- `web/Dockerfile.source`
- `docker/docker-compose.source.yaml`

## Temporary runtime-only changes made during bring-up

These were useful during debugging but are not the long-term design center:

- temporary runtime patching of the marketplace `OpenAI-API-compatible` plugin
- temporary direct live-container hotpatches during debugging
- temporary local `.env` / plugin-daemon verification changes while getting unsigned local packages working
- temporary host dev server on `localhost:3000`

Important note:

- the OpenAI-compatible runtime patch was later reverted after the dedicated Thesys plugin path became the preferred path

## Console noise that turned out not to be root cause

The following were observed during debugging but were not the main failure:

- provider icon `404` requests
- Base UI button semantics warning
- Lexical `TextNode` warning
- preload warnings in the browser console

These were distracting, but not the reason C1 responses initially failed to render.

## Verification performed

Across the full effort, validation included:

- targeted frontend unit tests for answer rendering and hook behavior
- targeted backend unit tests for plugin bootstrap and account service integration
- plugin tests inside the plugin daemon container
- linting on changed frontend and backend files
- real UI testing against Thesys responses
- source Docker image builds for both `api` and `web`
- live route checks on plain `http://localhost`
- verification that the running containers were `dify-api-source` and `dify-web-source`

## Current caveats

### 1. The fork requires the source compose overlay

`docker compose up -d` by itself still uses stock image-based Dify.

Use:

```bash
docker compose -f docker-compose.yaml -f docker-compose.source.yaml up -d --build
```

### 2. Bundled plugin bootstrap is for the source stack and tenant creation flow

Fresh installs and new tenants in the source-backed stack get the bundled Thesys provider automatically.

Existing environments may already have the plugin installed from earlier manual testing, or may need a manual re-install depending on database state.

### 3. Vinext is still not the supported runtime path for this forked Docker stack

The source Docker path intentionally uses the stable Next.js runtime target.

If someone later wants `EXPERIMENTAL_ENABLE_VINEXT=true`, that needs additional work on the `lucide-react/dynamicIconImports` resolution issue.

### 4. Marketplace publication is not done yet

The plugin is available locally in this fork, but publication to a public marketplace still needs its own packaging, signing, and release process.

## Recommended next step

The next major task after this integration is marketplace publication for the dedicated `Thesys` plugin.

That work should likely cover:

- plugin signing strategy
- release packaging
- versioning policy
- any marketplace metadata or review requirements
- deciding whether the plugin should remain fully local-source-friendly or also ship as a standard marketplace artifact
