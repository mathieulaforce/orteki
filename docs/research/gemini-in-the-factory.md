# Gemini in the software factory

Date: 2026-10-26. Versions checked: `@google/gemini-cli` 0.65.0 (upstream latest; 0.43.0 installed locally), `google-github-actions/run-gemini-cli` v0.1.22 (`@v0`).

Per [ADR-0001](../adr/0001-offline-only-no-cloud-llms.md), `orteki` itself is strictly offline and never calls cloud models at runtime; this note covers using Gemini solely in the **software factory** (issue [#6](https://github.com/mathieulaforce/orteki/issues/6), unblocking [#7](https://github.com/mathieulaforce/orteki/issues/7)) to implement `agent:gemini` tickets and cross-review `agent:claude` pull requests using the owner's Google AI Pro plan.

## Summary / recommendation

- **Google AI Pro funds Gemini CLI in two distinct ways—one interactive, one headless:**
  1. **Interactive local CLI (`Sign in with Google`):** Signing in with the Google AI Pro account gives **1,500 model requests per user per day** (~120 RPM, resetting at midnight PT), pooled across Gemini Pro and Flash models. However, **Gemini CLI has no `setup-token` equivalent** to Claude Code's `claude setup-token`, and `google-github-actions/run-gemini-cli` does not support personal Google OAuth refresh tokens on GitHub-hosted runners.
  2. **Headless GitHub Actions via included Google Developer Program credits (recommended for `#7`):** An active **Google AI Pro** subscription includes **Google Developer Program Premium** at no extra cost, which grants **USD 10/month in Google Cloud credits**. Claiming that benefit at [developers.google.com/program](https://developers.google.com/program) and linking the resulting Cloud Billing account to a GCP project upgrades a Google AI Studio **`GEMINI_API_KEY`** (or Vertex AI) to the paid tier—unlocking Gemini Pro and Flash models in GitHub Actions for ~30–150+ ticket builds and PR reviews per month at zero extra out-of-pocket cost. *(Without billing attached, a free-tier `GEMINI_API_KEY` is capped at 250 requests/day and restricted to Flash models only.)*
- **Run Gemini CLI in GitHub Actions with `google-github-actions/run-gemini-cli@v0`** (pinned to a tag or commit SHA), authenticated with either:
  - **Method A (simplest):** a single `GEMINI_API_KEY` repository secret created in Google AI Studio on the credit-backed GCP project, or
  - **Method B (keyless):** Vertex AI via **Workload Identity Federation** (`gcp_workload_identity_provider`, `gcp_project_id`, `gcp_service_account`, `use_vertex_ai: 'true'`), requiring zero Google secrets.
- **Add a one-line `GEMINI.md` containing `@AGENTS.md`** at the repository root. Verified in `@google/gemini-cli`'s `memoryDiscovery` module: `GEMINI.md` is loaded automatically and resolves `@AGENTS.md` imports identically to [`CLAUDE.md`](../../CLAUDE.md).
- **Use a custom GitHub App token (or fine-grained PAT) instead of the default `GITHUB_TOKEN`** when agents open or review PRs. PRs and comments created with `GITHUB_TOKEN` do not trigger downstream `on: pull_request` workflows (`ci.yml` or cross-model review)—the same constraint noted on `#7` for `release-please`. Keep the App off `trunk`'s branch-protection bypass list so agents still cannot merge.
- **For PR reviews in `#7`, use a `run-gemini-cli` GitHub Actions workflow rather than the Gemini Code Assist GitHub App:**
  - The **Gemini Code Assist GitHub App** is free (≥ 100 PR reviews/day) and **does not use the Google AI Pro plan**, but it reviews *every* opened PR by default (including Gemini's own PRs unless auto-review is disabled and triggered via `/gemini review` comments), **hard-excludes `.github/workflows/`**, and cannot run repo checks.
  - A **`run-gemini-cli` review workflow** gates cleanly on Claude-authored PRs via YAML `if:`, inspects `.github/workflows/`, reads `GEMINI.md` / `AGENTS.md` / [`CONTEXT.md`](../../CONTEXT.md) / `docs/adr/`, and shares the exact same USD 10/month AI Pro Developer Program credit and GitHub App setup as `agent:gemini` builds.

---

## 1. Gemini CLI usage limits on Google AI Pro

### 1.1 Interactive quotas (`Sign in with Google`) vs API keys

When authenticating interactively (`Sign in with Google`, internal auth type `oauth-personal`), Gemini CLI routes requests through Gemini Code Assist and enforces per-user rate limits based on the account's subscription tier:

| Tier / authentication method | RPM | Daily limit (RPD) | Models available | Cost / plan tie-in |
|---|---:|---:|---|---|
| Individual Google account (free — Code Assist for individuals) | 60 | 1,000 / user / day | Gemini Pro & Flash (auto-routed) | Free |
| **Google AI Pro** (`Sign in with Google`) | **120** | **1,500 / user / day** | **Gemini Pro & Flash (auto-routed)** | **Included in Google AI Pro (USD 19.99/mo)** |
| Google AI Ultra (`Sign in with Google`) | 120 | 2,000 / user / day | Gemini Pro & Flash (auto-routed) | Included in Google AI Ultra |
| Gemini Code Assist Standard (Workspace / GCP license) | 120 | 1,500 / user / day | Gemini Pro & Flash | Per-seat GCP / Workspace license |
| Gemini Code Assist Enterprise (Workspace / GCP license) | 120 | 2,000 / user / day | Gemini Pro & Flash | Per-seat GCP / Workspace license |
| Google AI Studio `GEMINI_API_KEY` (unpaid / free tier) | 5–15 | **250 / project / day** | **Flash models only** (no Pro) | Free (prompts may be used by Google per free-tier terms) |
| **Google AI Studio `GEMINI_API_KEY` or Vertex AI (Paid Tier 1)** | **150–2,000+** | **Token-billed (high/no RPD cap)** | **All Pro & Flash models** | **Pay-as-you-go; offset by AI Pro's USD 10/mo Cloud credit** |

Key quota mechanics documented in `google-gemini/gemini-cli` (`docs/resources/quota-and-pricing.md`):

- **Google AI Plus does not raise CLI limits:** Only **Google AI Pro** (1,500 RPD) and **Google AI Ultra** (2,000 RPD) increase consumer `Sign in with Google` Gemini CLI quotas; Google AI Plus remains at the 1,000 RPD individual free tier.
- **One CLI prompt = many model requests:** Gemini CLI runs an agentic ReAct loop (thinking, reading files, editing code, running `ruff` / `lint-imports` / `pytest` / `basedpyright`). A single medium ticket build or thorough PR review typically makes **10–40+ underlying model requests**, so 1,500 RPD equates to roughly **35–100 agent runs per day**.
- **Shared pool across tools and models:** Daily request counts are pooled across all Gemini models (Pro and Flash) and shared between Gemini CLI and IDE Gemini Code Assist agent mode on the same Google account. When Pro capacity is constrained, the CLI may fall back or route lighter sub-calls to Flash.
- **Reset window:** Daily request counters reset at **midnight Pacific Time (PT)**.

### 1.2 Funding headless CI with Google AI Pro's USD 10/month Cloud credit

Because personal Google OAuth is interactive-only (see §2.2), headless GitHub Actions runs should use **Google AI Pro's bundled Google Developer Program Premium benefit**:

1. **Claim the benefit:** Sign in with the Google AI Pro account at [developers.google.com/program](https://developers.google.com/program) and open [me.developers.google.com/benefits](https://me.developers.google.com/benefits) to activate the **USD 10/month Google Cloud credit** (unused monthly grants roll over for up to 12 months while the subscription remains active).
2. **Attach billing to a dedicated GCP project:** Link the credit-backed Cloud Billing account to a project (e.g. `orteki-factory`) and configure a **GCP Billing budget alert at USD 10/month** so usage cannot silently exceed the included credit.
3. **Paid-tier API benefits:** Attaching billing lifts the 250 RPD Flash-only cap on `GEMINI_API_KEY`, unlocks Gemini Pro models, and applies **Paid Services** data-governance terms (prompts and code are **not** used to train Google models).

Representative Paid Tier API token rates (prompts ≤ 200k tokens; model thinking tokens are billed at the output rate):

| Model | Input / 1M tokens | Output (incl. thinking) / 1M tokens | Est. cost per factory run (150k in / 12k out) | Est. runs covered by USD 10/mo credit |
|---|---:|---:|---:|---:|
| `gemini-2.5-pro` | USD 1.25 | USD 10.00 | ~USD 0.31 (less with context caching) | ~30–60 runs |
| `gemini-2.5-flash` | USD 0.30 | USD 2.50 | ~USD 0.08 | ~125+ runs |
| `gemini-3.1-pro-preview` | USD 2.00 | USD 12.00 | ~USD 0.44 | ~22–45 runs |
| `gemini-3.8-flash` *(intro through 2026-12-31)* | USD 0.75 | USD 3.75 | ~USD 0.16 | ~60+ runs |
| `gemini-4-argon` *(through 2026-11-30)* | USD 2.00 | USD 10.00 | ~USD 0.42 | ~25–50 runs |

In practice, Gemini CLI's multi-turn sessions benefit heavily from implicit/cached prefix tokens across turns within one session, bringing typical small-repo ticket builds and PR reviews into the **USD 0.06–0.30** range on Pro models (~35–150 runs/month inside the USD 10 credit).

---

## 2. Running Gemini CLI from GitHub Actions

### 2.1 Official action: `google-github-actions/run-gemini-cli`

Google maintains the official composite action [`google-github-actions/run-gemini-cli`](https://github.com/google-github-actions/run-gemini-cli) (v0.1.22 checked; referenced via `@v0` or a pinned release SHA). Inspection of `action.yml` shows what it does on the runner:

1. **Validates authentication inputs:** Warns if zero or more than one of `gemini_api_key`, `google_api_key`, or `gcp_workload_identity_provider` is set.
2. **Writes `.gemini/settings.json`:** If the `settings` input is provided (JSON string), writes it to `.gemini/settings.json` and installs built-in slash commands into `.gemini/commands/`.
3. **Authenticates to Google Cloud (WIF only):** Runs `google-github-actions/auth@v3` when `gcp_workload_identity_provider` is non-empty.
4. **Installs `@google/gemini-cli`:** Runs `npm install --global @google/gemini-cli@<gemini_cli_version>` (defaults to `latest`; supports `preview`, `nightly`, or an exact semver such as `0.65.0`) and installs any listed Gemini CLI `extensions`.
5. **Executes headless mode:** Runs `gemini --yolo --prompt "${PROMPT}" --output-format json` (`--debug` when `gemini_debug: 'true'`). `--yolo` auto-approves tool calls inside the ephemeral Actions VM; tool access should therefore be scoped via `.gemini/settings.json` (`settings` input).
6. **Publishes outputs & summary:** Parses JSON stdout/stderr via `jq` into step outputs `summary` (`steps.<id>.outputs.summary`) and `error` (`steps.<id>.outputs.error`), writes a Markdown summary to `$GITHUB_STEP_SUMMARY`, and optionally uploads `gemini-artifacts/` (`stdout.log`, `stderr.log`, `telemetry.log`) when `upload_artifacts: 'true'`.

### 2.2 Why personal Google OAuth does not work like `claude setup-token`

Issue `#7` pairs Claude Code (`claude setup-token`) with Gemini CLI. Direct inspection of `@google/gemini-cli` (`oauth2.js` and `contentGenerator.js`) and `run-gemini-cli/action.yml` confirms that **personal Google OAuth cannot be used cleanly on GitHub-hosted runners**:

- **No `setup-token` subcommand:** Running `gemini` non-interactively without `GEMINI_API_KEY` or Google Cloud credentials raises `FatalAuthenticationError: Manual authorization is required but the current session is non-interactive`.
- **`use_gemini_code_assist: 'true'` is for GCP organizational licenses, not consumer AI Pro:** In `action.yml`, `use_gemini_code_assist: 'true'` requires `gcp_workload_identity_provider` and `gcp_project_id`, passing `GOOGLE_GENAI_USE_GCA=true` and `GOOGLE_CLOUD_ACCESS_TOKEN` from a GCP service account. That service account requires an enterprise/standard **Gemini Code Assist IAM license** (`roles/cloudaicompanion.user`) on GCP—consumer Google AI Pro subscriptions are tied to a personal Google user account and cannot be granted to a service account.
- **Copying `~/.gemini/oauth_creds.json` into a GitHub Secret is unsupported and fragile:** While `initOauthClient()` in `oauth2.js` refreshes a cached `~/.gemini/oauth_creds.json` file when `GOOGLE_GENAI_USE_GCA=true`, `run-gemini-cli` flags the run as missing authentication, the cached refresh token carries a broad personal `https://www.googleapis.com/auth/cloud-platform` scope, and token rotation or revocation silently breaks CI.
- **Self-hosted runner note:** If the owner ever runs a local self-hosted runner on the desktop already signed in via `gemini`, local runs *would* use the 1,500 RPD interactive pool directly—but for GitHub-hosted runners in `#7`, the USD 10/month-credited API key or Vertex AI WIF is the clean, supported path.

### 2.3 Supported Google authentication methods & required secrets

| Method | Action inputs | Required GitHub Secrets | Required GitHub Variables | Job permissions | Pros / trade-offs |
|---|---|---|---|---|---|
| **A. Billing-linked Google AI Studio key (Recommended start)** | `gemini_api_key: ${{ secrets.GEMINI_API_KEY }}` | `GEMINI_API_KEY` | *(none)* | `contents: write`, `pull-requests: write`, `issues: write` | 2-minute setup; 1 secret; billed against AI Pro's USD 10/mo GCP credit |
| **B. Vertex AI via Workload Identity Federation (Keyless)** | `gcp_workload_identity_provider`, `gcp_project_id`, `gcp_service_account`, `gcp_location`, `use_vertex_ai: 'true'` | *(none for Google)* | `GCP_WIF_PROVIDER`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `SERVICE_ACCOUNT_EMAIL` | Same + `id-token: write` | Zero static Google keys; requires one-time OIDC pool + IAM setup (`scripts/setup_workload_identity.sh`) |
| C. Vertex AI API key | `google_api_key: ${{ secrets.GOOGLE_API_KEY }}`, `use_vertex_ai: 'true'` | `GOOGLE_API_KEY` | *(none)* | Same as A | Static key without WIF's security benefit; no advantage over Method A |

### 2.4 GitHub token, `GEMINI.md` context, and `#7` workflow pattern

1. **GitHub token (`GITHUB_TOKEN` will not trigger `ci.yml` or cross-review):**
   - GitHub suppresses `on: pull_request` and `on: pull_request_review` workflow runs when an event is created using the built-in `GITHUB_TOKEN` (to prevent accidental recursive loops).
   - Consequently, if Gemini opens a PR with `GITHUB_TOKEN`, **neither `ci.yml` nor Claude's automatic cross-model review workflow will start**—and once branch protection on `trunk` requires `ci.yml`, the PR cannot become mergeable.
   - **Fix:** Create a private GitHub App owned by `mathieulaforce` (permissions: `Contents: Read and write`, `Pull requests: Read and write`, `Issues: Read and write`; installed only on `mathieulaforce/orteki`), store `APP_ID` as a repository variable and `APP_PRIVATE_KEY` as a repository secret, and mint a short-lived token with `actions/create-github-app-token@v2`, passing it as `GH_TOKEN` (and to `actions/checkout`). Keep this App **out** of `trunk`'s branch-protection bypass list so only the human owner can approve and merge.
2. **Project instructions (`GEMINI.md` → `@AGENTS.md`):**
   - Verified in `@google/gemini-cli`'s `memoryTool.ts` and `memoryDiscovery`: Gemini CLI looks for `GEMINI.md` up to `.git` and expands `@<file>` imports via `processImports()`.
   - Adding a one-line `GEMINI.md` containing `@AGENTS.md` (mirroring [`CLAUDE.md`](../../CLAUDE.md)) ensures Gemini CLI automatically loads `AGENTS.md` (and follows its links to [`CONTEXT.md`](../../CONTEXT.md) and `docs/adr/`). Alternatively, `"context": { "fileName": ["AGENTS.md", "GEMINI.md"] }` can be passed in `settings`.
3. **Untrusted-input & owner-only guardrails for `#7`:**
   - Gate `issues: [labeled]` on `github.event.label.name == 'ready-for-agent' && github.event.sender.login == github.repository_owner && contains(github.event.issue.labels.*.name, 'agent:gemini')`.
   - Pass `${{ github.event.issue.title }}` and `${{ github.event.issue.body }}` via step `env:` variables (or a temporary file), **never** interpolated directly into shell scripts, and **do not fetch issue comments** (`gh issue view` without `--comments`, or read directly from `ISSUE_TITLE` / `ISSUE_BODY` env vars).

Illustrative build job skeleton for `#7` (Method A + GitHub App token):

```yaml
name: Agent build (Gemini)

on:
  issues:
    types: [labeled]

jobs:
  build:
    if: >-
      github.event.label.name == 'ready-for-agent' &&
      github.event.sender.login == github.repository_owner &&
      contains(github.event.issue.labels.*.name, 'agent:gemini')
    runs-on: ubuntu-latest
    timeout-minutes: 30
    permissions:
      contents: write
      pull-requests: write
      issues: write
    steps:
      - name: Mint GitHub App token
        id: app_token
        uses: actions/create-github-app-token@v2
        with:
          app-id: ${{ vars.APP_ID }}
          private-key: ${{ secrets.APP_PRIVATE_KEY }}

      - uses: actions/checkout@v4
        with:
          token: ${{ steps.app_token.outputs.token }}

      - uses: astral-sh/setup-uv@v7

      - name: Install headless Qt system libraries
        run: sudo apt-get update && sudo apt-get install -y --no-install-recommends libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3

      - name: Run Gemini CLI on ticket
        uses: google-github-actions/run-gemini-cli@v0
        env:
          GH_TOKEN: ${{ steps.app_token.outputs.token }}
          ISSUE_NUMBER: ${{ github.event.issue.number }}
          ISSUE_TITLE: ${{ github.event.issue.title }}
          ISSUE_BODY: ${{ github.event.issue.body }}
        with:
          gemini_api_key: ${{ secrets.GEMINI_API_KEY }}
          gemini_cli_version: '0.65.0'
          upload_artifacts: 'true'
          settings: |
            {
              "model": { "maxSessionTurns": 50 },
              "context": { "fileName": ["AGENTS.md", "GEMINI.md"] }
            }
          prompt: |
            Implement GitHub issue from the environment variables ISSUE_NUMBER, ISSUE_TITLE, and ISSUE_BODY.
            Security rule: read ONLY ISSUE_TITLE and ISSUE_BODY already in your environment; do NOT fetch issue comments.
            Follow AGENTS.md, CONTEXT.md, and docs/adr/.
            Create branch feat/<number>-<slug> (or fix/docs/chore as appropriate) from origin/trunk, run the full CI check command from AGENTS.md, commit using Conventional Commits, push the branch, and open a pull request against trunk referencing Closes #<number>.
```

---

## 3. Pull request review: GitHub App vs GitHub Action

Gemini supports two official ways to review pull requests on GitHub:

| Dimension | Option 1: Gemini Code Assist GitHub App | Option 2: `run-gemini-cli` PR Review Workflow (Recommended) |
|---|---|---|
| **Install / mechanism** | GitHub Marketplace App ([`gemini-code-assist`](https://github.com/apps/gemini-code-assist)), linked via [gemini-code-assist.google](https://gemini-code-assist.google/) | GitHub Actions workflow using `google-github-actions/run-gemini-cli@v0` |
| **Uses Google AI Pro plan?** | **No.** Uses a separate **free** GitHub App quota (**≥ 100 PR reviews/day** per installation); neither uses the 1,500 RPD CLI pool nor bills Cloud credits | **Indirectly, yes.** Uses the same `GEMINI_API_KEY` or Vertex AI project backed by AI Pro's **USD 10/month Google Developer Program credit** |
| **Cross-model gating (`#7`: review Claude PRs only)** | **Awkward.** Auto-reviews *every* PR by default (including Gemini's own PRs and `release-please`). Requires disabling `pull_request_opened` in `.gemini/config.yaml` and using a separate Action (with App/PAT token) to comment `/gemini review` on Claude PRs | **Native.** Standard workflow `if:` condition runs only on Claude-authored PRs (by bot identity, label, or branch convention) |
| **Reviews `.github/workflows/`?** | **No.** Hard-excludes `.github/workflows/` from summaries and reviews | **Yes.** Full read access to all tracked files, including `.github/workflows/` |
| **Project context & verification** | Reads `.gemini/config.yaml` and `.gemini/styleguide.md`; static diff analysis only (cannot run `pytest` or `lint-imports`) | Automatically reads `GEMINI.md` (`@AGENTS.md`), [`CONTEXT.md`](../../CONTEXT.md), and `docs/adr/`; can inspect callers and run checks |
| **Runner / maintenance cost** | Zero Actions minutes; zero secrets | ~1–3 Actions minutes per review; reuses `GEMINI_API_KEY` (or WIF) + GitHub App token already set up for builds |

### 3.1 Details on Option 1 (Gemini Code Assist GitHub App)

- **Setup & customisation:** Installed from GitHub Marketplace without GCP billing on the consumer tier; behaviour is tuned via `.gemini/config.yaml` (`code_review.disable`, `code_review.comment_severity_threshold`, `code_review.max_review_comments`, `code_review.pull_request_opened`, `ignore_patterns`) and `.gemini/styleguide.md`. Supports manual re-reviews via `/gemini review` PR comments.
- **Why it is a poor primary fit for `#7`:**
  1. `#7` requires *"A PR from one model is automatically reviewed by the other model"*. Out of the box, the GitHub App reviews Gemini's own PRs too. Suppressing auto-review in `.gemini/config.yaml` and writing a GitHub Actions workflow to post `/gemini review` on Claude PRs still requires a workflow + GitHub App/PAT token—eliminating the App's "no workflow needed" advantage.
  2. Its hard exclusion of `.github/workflows/` means factory workflow changes cannot be reviewed by it.
  3. Maintaining a separate `.gemini/styleguide.md` duplicates `AGENTS.md`, `CONTEXT.md`, and `docs/adr/`.

### 3.2 Details on Option 2 (`run-gemini-cli` PR Review Workflow — Recommended)

- **How it runs:** Triggered on `pull_request: [opened, synchronize, ready_for_review]` with an `if:` guard ensuring:
  1. `github.event.pull_request.head.repo.full_name == github.repository` (never expose secrets to external fork PRs), and
  2. The PR was opened by the Claude factory workflow (e.g. matching a dedicated Claude GitHub App actor, an `agent:claude` label applied by the Claude build workflow, or branch prefix).
- **Posting the review:** `run-gemini-cli` ships both an official PR review example (`examples/workflows/pr-review/gemini-review.yml`) and an optional [`gemini-cli-extensions/code-review`](https://github.com/gemini-cli-extensions/code-review) extension, or Gemini CLI can inspect `gh pr diff` and submit a formal review with `gh pr review --comment` (never `--approve`, keeping merge approval strictly human-only on `trunk`).
- **Plan usage:** Each review consumes ~USD 0.05–0.20 from the **USD 10/month Google Developer Program Cloud credit** included with Google AI Pro.

---

## Open questions

1. **`GEMINI_API_KEY` vs keyless Workload Identity Federation in `#7`.** Both spend the same USD 10/month Google Developer Program credit. Starting with `GEMINI_API_KEY` requires a single GitHub Secret and no IAM/OIDC plumbing; WIF removes long-lived secrets altogether via `scripts/setup_workload_identity.sh`. Which setup friction does the owner prefer?
2. **Model pinning (`gemini_model`) vs CLI default routing.** Should `#7` leave `gemini_model` unset (letting Gemini CLI auto-route Pro and Flash) or pin e.g. `gemini-2.5-pro` for builds and reviews so cost and reasoning depth stay predictable against the USD 10/month credit?
3. **GitHub App identity topology for `#7`.** `release-please`, `agent:claude`, and `agent:gemini` all need non-`GITHUB_TOKEN` credentials so their PRs trigger `ci.yml` and cross-model reviews. Using two lightweight GitHub Apps (`orteki-claude` and `orteki-gemini`, or one `orteki-factory` App plus `agent:claude` / `agent:gemini` PR labels; plus `release-please` on its own token or App) makes cross-model `if:` conditions unambiguous and audit logs clean.

## Sources

- `google-gemini/gemini-cli` (v0.65.0 upstream, 0.43.0 local):
  - [Quota and pricing (`docs/resources/quota-and-pricing.md`)](https://github.com/google-gemini/gemini-cli/blob/main/docs/resources/quota-and-pricing.md) and [geminicli.com quota docs](https://geminicli.com/docs/resources/quota-and-pricing/)
  - [Authentication setup (`docs/get-started/authentication.mdx`)](https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/authentication.mdx) and [Plans overview](https://geminicli.com/plans/)
  - [Configuration & `GEMINI.md` context files (`docs/get-started/configuration.md`)](https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/configuration.md)
  - Local bundle inspection (`/usr/local/lib/node_modules/@google/gemini-cli/bundle/`): `packages/core/src/code_assist/oauth2.js` (`initOauthClient`, `FatalAuthenticationError`), `packages/core/src/core/contentGenerator.js` (`AuthType`, `getAuthTypeFromEnv`), and `packages/core/src/tools/memoryTool.ts` / `memoryDiscovery` (`DEFAULT_CONTEXT_FILENAME = "GEMINI.md"`, `processImports`)
- Google AI Pro & Google Cloud / AI Studio pricing:
  - [Google Developer Program benefits (USD 10/month Cloud credit with Google AI Pro)](https://developers.google.com/program) and [benefits dashboard](https://me.developers.google.com/benefits)
  - [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing) and [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- `google-github-actions/run-gemini-cli` (v0.1.22):
  - [`README.md`](https://github.com/google-github-actions/run-gemini-cli/blob/main/README.md) and [`action.yml`](https://github.com/google-github-actions/run-gemini-cli/blob/main/action.yml)
  - [`docs/authentication.md`](https://github.com/google-github-actions/run-gemini-cli/blob/main/docs/authentication.md) and [`docs/best-practices.md`](https://github.com/google-github-actions/run-gemini-cli/blob/main/docs/best-practices.md)
  - [`examples/workflows/pr-review/gemini-review.yml`](https://github.com/google-github-actions/run-gemini-cli/blob/main/examples/workflows/pr-review/gemini-review.yml)
- Gemini Code Assist for GitHub (GitHub App):
  - [Set up Gemini Code Assist on GitHub](https://developers.google.com/gemini-code-assist/docs/set-up-gemini-github)
  - [Review GitHub code using Gemini Code Assist](https://developers.google.com/gemini-code-assist/docs/review-github-code)
  - [Customise Gemini Code Assist on GitHub (`.gemini/config.yaml`, `.gemini/styleguide.md`)](https://developers.google.com/gemini-code-assist/docs/customize-gemini-behavior-github)
  - [Gemini Code Assist quotas and limits (≥ 100 PR reviews/day)](https://developers.google.com/gemini-code-assist/resources/quotas)
  - [GitHub Marketplace: `gemini-code-assist`](https://github.com/apps/gemini-code-assist)
- GitHub Actions workflow triggering:
  - [Triggering a workflow from a workflow (`GITHUB_TOKEN` limitation)](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/triggering-a-workflow#triggering-a-workflow-from-a-workflow)
