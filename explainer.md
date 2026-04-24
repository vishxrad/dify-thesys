# Thesys integration — architecture explainer

This document explains how a conversation using a Thesys model flows through the fork, what each layer is responsible for, and where the interesting decisions live. It is intended as the first file a new contributor reads. For the chronological history of *how* the integration was built, see `changes.md`.

---

## The 30-second mental model

A Thesys conversation is an otherwise-normal Dify chat where the model response happens to be generative-UI markup instead of prose. The model emits an XML envelope that wraps either a JSON component tree (v1) or an openui-lang DSL (v2). The Dify backend stores the raw envelope as the answer. The frontend detects the envelope and hands it to `@thesysai/genui-sdk`, which parses it and renders React components.

```
User prompt
  ↓
Dify backend (API worker)
  ↓ LLM invocation dispatched to the plugin daemon
Plugin daemon spawns the Thesys plugin
  ↓
Thesys plugin POSTs to https://api.thesys.dev/v1/embed/chat/completions
  ↓ streams SSE frames back
Plugin yields LLM chunks → task pipeline → Redis queue → SSE out to the browser
  ↓
Frontend accumulates chunks in BasicContent / AgentContent
  ↓ once the content is stable, detectResponseFormat → 'c1'
<C1Component> from @thesysai/genui-sdk parses the wrapper and renders
```

Every piece above exists upstream in Dify except the Thesys plugin, the frontend C1 renderer, and a few small task-pipeline patches.

---

## The Thesys response protocol (their design, not ours)

Thesys models respond with an XML-ish wrapper. The wrapper is the model's own multiplexing format — it can contain multiple typed message parts in one stream.

```
<content thesys="true" version="1">  {"component":{"component":"Card", ...}}  </content>
<content thesys="true" version="2">  ```openui-lang\nroot = Card(...)\n```      </content>
```

The SDK parses the wrapper with `htmlparser2` in `xmlMode`. On `onopentag("content", attrs)` it reads `attrs.version`:

- `version=1` → inner text is JSON, fed to the v1 component-tree renderer
- `version=2` → inner text is openui-lang, fed to `Renderer` from `@openuidev/react-lang`

Other tag types exist in the protocol (`<artifact>`, `<custommarkdown>`, `<thinking>`, `<context>`) but the fork only exercises `<content>` today.

### openui-lang

openui-lang is the v0.5 DSL by OpenUI / Thesys. One statement per line, form `name = Component(args…)`. Strings are always `"..."`. Variables can reference earlier statements. Example:

```
root = Card([header, body, followUp])
header = Header("Hello!", "How can I help you today?")
body = TextContent("I can plan trips, build dashboards, summarise data, and more.")
followUp = FollowUpBlock(["Plan a trip", "Build a form", "Summarise a doc"])
```

Official spec: https://openui.com/docs/openui-lang/specification-v05.

### Important: the wrapper is HTML-entity-encoded at the text-node boundary

Thesys serialises the inner payload as XML text, so `"` becomes `&quot;`, `<` becomes `&lt;`, etc. SDK 0.9.x handles this itself (`htmlparser2 { decodeEntities: true }` + `lodash/unescape`). We do not pre-decode on our side — if we did, we would corrupt payloads that legitimately contain `&lt;` / `&gt;` inside string literals.

---

## Frontend

### Entry points

The chat bubble is either:

- `web/app/components/base/chat/chat/answer/basic-content.tsx` — standard assistant message
- `web/app/components/base/chat/chat/answer/agent-content.tsx` — agent-mode message

Both hand the message content to a shared `ResponseRenderer`.

### `detect-response-format.ts`

A tiny detector with one job: decide whether a given string is a C1 response or plain Markdown. It matches the opening tag of `<thinking>`, `<content>`, `<artifact>`, or `<custom_markdown>`. Critically, it takes a `{ stable }` option:

- during streaming (`responding === true`), the detector only flips to C1 once the matching closing tag is already present in the content
- once the stream ends (`stable: true`), the detector flips to C1 on the opening tag alone

This is the gate that prevents the SDK from trying to parse a half-open payload mid-stream.

### `response-renderer.tsx`

The mux that sits between the chat bubble and the renderers. On each render:

1. Calls `detectResponseFormat(content, { stable: !responding })`
2. If 'c1', renders `<ErrorBoundary><C1Response /></ErrorBoundary>` — the error boundary is insurance against SDK render throws
3. If 'markdown', renders `<Markdown />` wrapped in a `<div>` that carries the `data-testid`

It also preloads the `C1Response` chunk at module init so the first Markdown-to-C1 transition never has to round-trip for the lazy bundle.

### `c1-response.tsx`

The thin adapter between Dify's chat context and `@thesysai/genui-sdk`. Responsibilities:

- pass the raw content through unchanged (the SDK decodes entities itself)
- translate SDK actions back into Dify's send flow:
  - `open_url` → `window.open` — but only if the URL is absolute `http:` / `https:` (URLs from the LLM are untrusted; `new URL(raw)` without a base rejects relative/no-scheme inputs)
  - `readonly === true` → drop conversation actions
  - otherwise → call the chat context's `onSend` with the LLM-friendly or human-friendly message
- latch `isStreaming={true}` for ~400ms after `responding` flips to false (`useSettledIsStreaming`) so the SDK's `u || o` render gate doesn't momentarily paint its "Error while generating response" fallback during the `validatedProps` settle

### `hooks.ts` (useChat)

Two interactions with the Thesys flow beyond the normal chat protocol:

- when the stream completes and the frontend fetches the saved history, if `historyAnswer` is empty it preserves the in-memory streamed content. This prevents an empty `message_end` payload from wiping the visible response.
- the chat action plumbing (`onSend`, `readonly`) is consumed by `c1-response.tsx` via `useChatContext`

### Styling

`web/app/layout.tsx` imports `@thesysai/genui-sdk/dist/genui-sdk.css`, which contains the `--openui-*` CSS variables and component styles. SDK 0.9.2's `package.json` does not expose that CSS path via `exports`; we add it with a pnpm patch (`patches/@thesysai__genui-sdk@0.9.2.patch`).

---

## Backend

### The provider plugin (`local-plugins/thesys/`)

A dedicated Dify plugin, not a fork of the generic OpenAI-compatible plugin. Structure:

- `manifest.yaml` — plugin manifest, registers one LLM model family
- `provider/thesys.yaml` — provider-level credential schema, supported model types, predefined models
- `provider/thesys.py` — `validate_provider_credentials`, thin wrapper around the LLM class
- `models/llm/llm.py` — `ThesysLargeLanguageModel`, subclass of `OAICompatLargeLanguageModel`. Hardcodes `endpoint_url = https://api.thesys.dev/v1/embed`. Handles streaming, tool calls, JSON-schema response format, reasoning parameter mapping
- `models/llm/_position.yaml` — ordering for predefined models
- `models/llm/c1-anthropic-claude-sonnet-4.6-v-20260331.yaml` — the predefined default model config
- `tests/` — unit tests for credential validation and stream response handling
- `main.py` — standard Dify plugin entrypoint

### Plugin defaults

`_apply_model_defaults` forces:

- `endpoint_url = https://api.thesys.dev/v1/embed`
- `mode = chat`
- `stream_mode_delimiter = "\n\n"`
- `token_param_name = "auto"` (falls back to `max_completion_tokens` for OpenAI reasoning models)
- `compatibility_mode = "strict"`
- `function_calling_type = "no_call"` (Thesys emits UI, not tool calls)
- `vision_support = "no_support"`
- `structured_output_support = "supported"`
- `agent_thought_support = "supported"`

### Plugin streaming semantics

`_handle_generate_stream_response` supports both the delta SSE format and the "one-shot chat.completion" reply. The filter strips reasoning/think blocks when thinking is disabled, with a 64 KB flush cap to prevent unbounded buffering if the model opens `<think>` without closing it.

### Task pipeline

`api/core/app/task_pipeline/easy_ui_based_generate_task_pipeline.py` owns the conversion from plugin-emitted LLM chunks into the Dify stream response protocol. The only fork-specific patch is `_merge_message_end_llm_result`: some providers send a terminal `QueueMessageEndEvent` with an empty content payload. Without this patch, that empty final payload would overwrite the accumulated streamed content. We deep-copy the final payload and keep the accumulated content whenever the final payload is empty.

### Bundled plugin bootstrap

New tenants (via `TenantService.create_tenant`) trigger `BundledPluginService.install_for_tenant`. The service:

1. reads `PLUGIN_AUTO_INSTALL_LOCAL_PACKAGES` (comma-separated absolute paths) from config
2. for each configured path, zips the plugin directory in memory
3. calls `PluginService.upload_pkg` (which does scope checks) then `PluginService.install_from_local_pkg(skip_redecode=True)`
4. polls the plugin-daemon install task until success, failure, or timeout

Policy:

- `PLUGIN_AUTO_INSTALL_STRICT = true` (set in `docker/docker-compose.source.yaml`) → a failure aborts tenant creation and rolls back the partially-committed tenant rows
- `PLUGIN_AUTO_INSTALL_STRICT = false` → failures are logged and the loop continues for the remaining packages
- Relative paths raise a clear configuration error (they used to silently resolve against the worker's CWD)

### Scope-check boundary

`PluginService.install_from_local_pkg` takes an explicit `skip_redecode: bool = False` kwarg. `BundledPluginService` passes `skip_redecode=True` because `upload_pkg` already ran the scope check on the just-uploaded package. Any other caller gets the scope check by default — no silent bypass based on identifier prefixes.

---

## Docker & runtime

### Two overlays

- `docker/docker-compose.yaml` — upstream Dify, image-based, unchanged from upstream
- `docker/docker-compose.source.yaml` — source-build overlay:
  - `api` / `worker` / `worker_beat` all use `dify-api-source` built from `api/Dockerfile.source`
  - `web` uses `dify-web-source` built from `web/Dockerfile.source`
  - `plugin_daemon` sets `FORCE_VERIFYING_SIGNATURE: "false"` (dev only — the overlay has a top-of-file warning)
  - `api` sets `PLUGIN_AUTO_INSTALL_LOCAL_PACKAGES` and `PLUGIN_AUTO_INSTALL_STRICT`

Command:

```bash
cd docker
cp .env.example .env
docker compose -f docker-compose.yaml -f docker-compose.source.yaml up -d --build
```

### Source Dockerfiles

`api/Dockerfile.source`:

- build context is the repo root (not `api/`), so `local-plugins/thesys/` can be copied into the image
- pinned Node.js version (for plugin-daemon JS execution)

`web/Dockerfile.source`:

- single stage builds the Next.js standalone target (not Vinext)
- `EXPERIMENTAL_ENABLE_VINEXT=false` hardcoded
- **must copy `patches/` before `pnpm install --frozen-lockfile`** because the SDK CSS patch lives there

---

## Database persistence

A Thesys conversation lives in the standard Dify tables:

- `messages` — one row per turn. Relevant columns:
  - `answer` — raw `<content thesys="true" version="…">…</content>` wrapper, as emitted by the model
  - `message_metadata` — JSON, token usage, retriever resources, annotation metadata
- `conversations` — conversation header
- `apps` — app config, model selection

**Nothing special about the storage layout today.** The full wrapper lands in `message.answer` unchanged. This preserves structural context for Thesys-to-Thesys multi-turn — the model sees its own prior openui-lang when building a new turn.

A planned follow-up will expose a pure `extract_plaintext(content)` helper, called on demand at the specific consumers that actually want prose (TTS, workflow chaining into non-Thesys nodes, conversation title generation, copy-to-clipboard). `message.answer` stays as the raw wrapper. See the "Phase 11" section in `changes.md` for the design.

---

## What breaks cleanly, what breaks messily

The integration is currently scoped to **single-model, single-provider chat conversations**. It works cleanly there. Outside that scope:

| Scenario | Status |
|---|---|
| Single-turn chat with Thesys | ✅ works |
| Multi-turn chat on the same Thesys model | ✅ works (model sees its own openui-lang as context) |
| Multi-turn chat switching providers mid-conversation | ⚠️ next provider sees raw XML in history; model quality degrades |
| Workflow LLM node → another LLM node, both Thesys | ⚠️ the chained node receives raw XML; needs a plaintext extractor |
| Workflow LLM node → Code/HTTP/Send-Email node | ⚠️ same |
| Conversation title generation | ⚠️ Dify's title summariser sees XML |
| TTS | ⚠️ would read markup aloud |
| RAG retrieval | ✅ retrieval itself is unaffected (uses the user query, not the LLM output) |
| Agent / function calling | ❌ incompatible by design (`function_calling_type: no_call`) |
| Structured output via JSON schema | ❌ incompatible by design (Thesys emits UI, not JSON schemas) |
| Copy-to-clipboard | ⚠️ copies the raw XML |

The ⚠️ cases all get fixed by the planned `extract_plaintext` pass. The ❌ cases are fundamental to the Thesys "UI instead of prose" design and won't be resolved by any amount of plumbing on our side.

---

## Key files, short list

Frontend:

- `web/app/components/base/chat/chat/answer/detect-response-format.ts`
- `web/app/components/base/chat/chat/answer/response-renderer.tsx`
- `web/app/components/base/chat/chat/answer/c1-response.tsx`
- `web/app/components/base/chat/chat/answer/basic-content.tsx`
- `web/app/components/base/chat/chat/answer/agent-content.tsx`
- `web/app/components/base/chat/chat/hooks.ts`
- `web/app/layout.tsx`

Backend:

- `api/core/app/task_pipeline/easy_ui_based_generate_task_pipeline.py`
- `api/services/plugin/plugin_service.py`
- `api/services/plugin/bundled_plugin_service.py`
- `api/services/account_service.py`
- `api/configs/feature/__init__.py`

Plugin:

- `local-plugins/thesys/manifest.yaml`
- `local-plugins/thesys/provider/thesys.yaml`
- `local-plugins/thesys/provider/thesys.py`
- `local-plugins/thesys/models/llm/llm.py`
- `local-plugins/thesys/models/llm/c1-anthropic-claude-sonnet-4.6-v-20260331.yaml`
- `local-plugins/thesys/models/llm/_position.yaml`

Docker & packaging:

- `api/Dockerfile.source`
- `web/Dockerfile.source`
- `docker/docker-compose.source.yaml`
- `.dockerignore`
- `patches/@thesysai__genui-sdk@0.9.2.patch`
- `pnpm-workspace.yaml` (SDK version pin + `patchedDependencies`)

Docs:

- `README.md` — quick start
- `changes.md` — chronological history
- `explainer.md` — this file
