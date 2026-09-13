# Django Agentic AI — Build Plan

**Status:** Day 4 complete (2026-09-13). HTMX fragment-swap chat flow verified end-to-end — sending a message no longer reloads the page; server log shows `POST /chat/send/ 200` (a direct fragment response, no redirect), and 6 real `chat_message` rows confirmed in Postgres across the session. Day 5 (first real LLM call) not started.
**Purpose of this file:** this is the single source of truth for the project. Every future session starts by reading this file — it must always reflect the current, real state of the build (update it as we go, don't let it drift).

---

## 1. Vision

Rebuild the idea behind `~/Desktop/agentic-ai` (a reference project you found on GitHub) as your own, from scratch, with Django — to actually learn how a multi-agent chat system works internally, not just use one.

**What "it" is:** a chat app where a "supervisor" component reads the user's message and decides which specialist should handle it — answer a greeting, summarize something, search your uploaded documents, or do search+summarize together and produce a grounded, cited answer. You upload PDFs/CSVs, ask questions, and the system routes and answers intelligently instead of just piping everything through one LLM call.

**Non-goals for now:** production deployment, horizontal scaling, multi-tenant hosting. This is a learning build — correctness and understanding first, hardening later (there's a curriculum step for that too).

---

## 2. Decisions already locked in (2026-09-08)

These were deliberately chosen over alternatives — recorded here so we never re-litigate them:

| Decision | Chosen | Rejected alternatives | Why |
|---|---|---|---|
| Backend framework | **Django** | (given — your ask) | Batteries-included: ORM, auth, admin, forms, migrations — you learn the "real" way things are usually done in Python web dev, not a minimal-framework reinvention. |
| Frontend | **Django templates + HTMX** | Next.js/React (what the reference project used), plain forms, vanilla JS fetch | Server-rendered HTML stays in Django's world — one language, one mental model. HTMX gives you dynamic, no-full-reload chat UX without ever leaving Python/HTML, and it's how a lot of real Django shops build interactive UIs today. |
| LLM provider | **Ollama** (local) | HuggingFace Router (what the reference used), OpenAI API | Free, local, no API key, fully inspectable — you already have it installed with `llama3.2` pulled. Ties directly into your LLM Engineering course. |
| Search/retrieval | **PostgreSQL full-text search** | Elasticsearch (what the reference used), SQLite FTS5 | One database serves as both your app's data store *and* your search index. One fewer service to install, run, and reason about while you're still learning the fundamentals. |
| Auth | **Django's built-in session auth** (`django.contrib.auth`) | JWT + Redis-as-user-store (what the reference project did) | This is a deliberate *improvement* over the reference project, not just a port. JWT-in-localStorage exists to solve a problem Django's server-rendered pages don't have (a stateless API talking to a separate SPA). With Django templates, sessions + CSRF cookies are the idiomatic, more secure choice — and Django gives you a real `User` model, password reset, admin integration, all for free. This is a good example of *why* professional Django doesn't reach for JWT by default. |
| Conversation storage | **PostgreSQL is the source of truth; Redis is a cache**, not the store of record | Redis-as-only-store (what the reference did) | Mirrors a genuinely common production pattern: durable data in Postgres, hot/repeated reads sped up by Redis. The reference project used Redis for everything (messages, cache, *and* users) because it had no real database — you will have one, so each store does the job it's actually good at. |
| Views: sync or async | **Synchronous Django views** to start | Async Django views | Async Django is a real, useful thing — but layering "async Python" on top of "Django" on top of "HTMX" on top of "agent orchestration" all in week one is too much at once. We build the synchronous version first, understand it completely, then Day 11+ can revisit async as a deliberate upgrade once the fundamentals are solid. |
| Redis (Day 1–10) | **Homebrew (`brew install redis`)** | podman-compose (what the reference project used) | Redis here is a single local service, not a multi-container stack — a container runtime is overhead with no payoff at this stage. Same reasoning that ruled out Elasticsearch: don't add a service (or a whole runtime) you can avoid while still learning fundamentals. |
| Container runtime (Day 11+, deployment only) | **Docker**, not Podman | Podman (what the reference project used) | If/when we containerize the full stack for deployment, Docker is the far more standard choice — most tutorials, most Stack Overflow answers, what most companies actually run — so the skill transfers better. Podman was the reference project's choice, not a constraint on ours. |

---

## 3. High-level architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ Browser                                                              │
│   Django templates (server-rendered HTML) + HTMX                     │
│   - full page load: GET /chat/<id>/                                  │
│   - message send: HTMX POST -> receives an HTML FRAGMENT back        │
│     (not JSON) -> swaps it into the page. No client-side JS state.   │
└───────────────────────────────┬───────────────────────────────────────┘
                                 │ HTTP (session cookie + CSRF token)
┌────────────────────────────────▼──────────────────────────────────────┐
│ Django (WSGI, sync views)                                             │
│                                                                        │
│  accounts app          chat app             documents app             │
│  ─────────────         ──────────           ──────────────            │
│  login/register/logout  chat views (HTMX)    upload views              │
│  django.contrib.auth    Conversation model   Document/DocumentChunk    │
│                         Message model         models                  │
│                              │                     │                  │
│                              ▼                     ▼                  │
│                     ┌──────────────────────────────────────┐          │
│                     │   agents app  (the orchestration      │          │
│                     │   layer — no HTTP, no Django-specific │          │
│                     │   code, pure Python services)         │          │
│                     │                                        │          │
│                     │  ChatWorkflow.run()                    │          │
│                     │    ├─ cache check (Redis)               │         │
│                     │    ├─ SupervisorAgent.decide_route()    │         │
│                     │    │     -> Ollama call, classify        │         │
│                     │    │        greeting|search|summary|     │         │
│                     │    │        parallel (keyword fallback)  │         │
│                     │    ├─ SearchAgent.run()                  │         │
│                     │    │     -> Postgres full-text search     │         │
│                     │    │        over DocumentChunk             │         │
│                     │    ├─ SummaryAgent.run()                  │         │
│                     │    │     -> Ollama call                    │         │
│                     │    ├─ grounded_answer()  (parallel route)  │         │
│                     │    │     -> Ollama call w/ retrieved chunks │         │
│                     │    │        + draft summary as context      │         │
│                     │    └─ persist Message rows, cache answer    │         │
│                     └──────────────────────────────────────┘          │
└──────────────┬───────────────────────────────┬────────────────────────┘
               │                                │
        ┌──────▼──────┐                 ┌───────▼────────┐
        │ PostgreSQL   │                 │ Redis           │
        │ - users      │                 │ - response cache│
        │ - conversations/messages       │ - rate limiting │
        │ - documents/chunks + tsvector  │   counters       │
        └──────────────┘                 └─────────────────┘
                                                  │
                                          ┌───────▼────────┐
                                          │ Ollama          │
                                          │ (localhost:11434)│
                                          │ llama3.2         │
                                          └──────────────────┘
```

**The key architectural idea to internalize:** the `agents` app is deliberately framework-agnostic. `ChatWorkflow`, `SupervisorAgent`, `SearchAgent`, `SummaryAgent` don't know they're running inside Django — they take plain Python objects in, return plain Python objects out. Django's job (in the `chat` app's views) is just to translate an HTTP request into a call to `ChatWorkflow.run()`, and translate the result back into an HTML fragment. This separation is *the* reason the reference project's code was portable-looking despite being FastAPI — and it's the single most important lesson this rebuild should teach you: **business logic should not know what web framework is calling it.**

---

## 4. Django project layout

```
django-agentic-ai/
├── manage.py
├── pyproject.toml            # uv-managed, per your established workflow
├── .env                      # real secrets, gitignored
├── .env.example               # committed template
├── config/                    # the Django "project" (settings, not an app)
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── accounts/                  # app: users, login, register, logout
│   ├── views.py
│   ├── urls.py
│   └── templates/accounts/
├── chat/                      # app: conversations, messages, the chat UI
│   ├── models.py               # Conversation, Message
│   ├── views.py                 # thin: parse request -> call ChatWorkflow -> render fragment
│   ├── urls.py
│   └── templates/chat/
│       ├── chat.html             # full page
│       └── partials/
│           └── message_pair.html # HTMX swap target (user bubble + assistant bubble)
├── documents/                 # app: upload, ingest, chunk, index
│   ├── models.py               # Document, DocumentChunk (with SearchVectorField)
│   ├── ingest.py                 # PDF/CSV -> text -> chunks (ported from reference's data_ingest/)
│   ├── views.py
│   ├── urls.py
│   └── templates/documents/
├── agents/                    # the orchestration layer — see section 3
│   ├── llm_service.py           # wraps the Ollama client
│   ├── supervisor.py             # routing decision
│   ├── search_agent.py
│   ├── summary_agent.py
│   ├── workflow.py                # ChatWorkflow: the orchestrator
│   ├── state.py                   # GraphState dataclass
│   └── prompts.py                 # prompt templates, ported from reference's prompts/
└── templates/
    └── base.html               # shared layout, nav, HTMX script tag
```

This mirrors the reference project's separation (`agents/`, `services/`, `state/`, `prompts/`, `data_ingest/`) almost 1:1 — you're not learning a totally different shape, you're learning *why* that shape exists, then re-deriving it in Django's idiom (apps instead of routers, models instead of a Redis-only store).

---

## 5. Data models (PostgreSQL via Django ORM)

```python
# accounts — uses Django's built-in User model. No custom model needed at first.

# chat/models.py
class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

class Message(models.Model):
    conversation = models.ForeignKey(Conversation, related_name="messages", on_delete=models.CASCADE)
    role = models.CharField(choices=[("user", "user"), ("assistant", "assistant")])
    content = models.TextField()
    route = models.CharField(blank=True)       # which route produced this (assistant messages only)
    created_at = models.DateTimeField(auto_now_add=True)

# documents/models.py
class Document(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    file_name = models.CharField(max_length=255)
    source_type = models.CharField(choices=[("pdf", "pdf"), ("csv", "csv")])
    uploaded_at = models.DateTimeField(auto_now_add=True)

class DocumentChunk(models.Model):
    document = models.ForeignKey(Document, related_name="chunks", on_delete=models.CASCADE)
    chunk_text = models.TextField()
    page_number = models.IntegerField(null=True)
    search_vector = SearchVectorField(null=True)   # Postgres full-text index

    class Meta:
        indexes = [GinIndex(fields=["search_vector"])]
```

`search_vector` gets kept up to date via a Django signal (`post_save` on `DocumentChunk`) or a `SearchVectorField` trigger — this is a Day 7 topic, not something to worry about now.

---

## 6. The orchestration layer, in detail (`agents/`)

This is a direct, deliberate adaptation of the reference project's `workflows/chat_workflow.py` + `agents/*.py` + `services/llm_service.py` — same responsibilities, Django/Postgres/Ollama underneath instead of FastAPI/Redis-only/HuggingFace Router.

**`GraphState`** (`agents/state.py`) — a plain dataclass carrying state through one request's pipeline: `conversation_id`, `user_message`, `history`, `route`, `search_results`, `summary_output`, `final_answer`. Nothing Django-specific lives here.

**`LLMService`** (`agents/llm_service.py`) — wraps calls to Ollama (`http://localhost:11434`, using the `ollama` Python package or raw `httpx`). Methods: `generate(prompt, ...)`, `summarize(text, context)`, `grounded_answer(question, retrieved_documents, conversation_history)`. This is the *only* place that talks to the LLM — every agent calls through here, never directly.

**`SupervisorAgent.decide_route(message)`** (`agents/supervisor.py`) — asks the LLM to classify the message into `greeting | search | summary | parallel`, with a keyword-based fallback if the LLM call fails or returns garbage (exact same resilience pattern as the reference project — this is a good lesson in graceful degradation).

**`SearchAgent.run(state)`** (`agents/search_agent.py`) — runs a Postgres full-text query (`SearchQuery` + `SearchRank`, ordered by rank) over `DocumentChunk`, formats results.

**`SummaryAgent.run(state)`** (`agents/summary_agent.py`) — calls `LLMService.summarize()`.

**`ChatWorkflow.run(message, conversation)`** (`agents/workflow.py`) — the orchestrator, called by `chat/views.py`:
1. Check Redis cache for an identical recent question in this conversation.
2. If miss: call `SupervisorAgent.decide_route()`.
3. Branch on route:
   - `greeting` → canned reply.
   - `summary` → `SummaryAgent.run()`.
   - `search` → `SearchAgent.run()`.
   - `parallel` (default) → run search + summary, then if search found anything, call `LLMService.grounded_answer()` to produce a final cited answer; otherwise fall back to the summary.
4. Persist both the user's `Message` and the assistant's `Message` to Postgres.
5. Cache the answer in Redis.
6. Return the result to the view, which renders `partials/message_pair.html`.

Each branch is wrapped in `try/except` with a fallback message on failure — same resilience pattern as the reference project, so one flaky agent never 500s the whole chat.

---

## 7. Request/data flow, walked through end to end

**Sending a chat message:**
1. Browser: HTMX-enabled `<form>` in `chat.html` fires `hx-post="/chat/{id}/message/"` on submit.
2. Django `chat/views.py::send_message`: validates the form, loads the `Conversation` (checking `request.user` owns it — Django session auth handles *who* you are; the view still must check *authorization*, i.e. that this conversation belongs to this user).
3. View calls `ChatWorkflow.run(message=..., conversation=...)`.
4. Workflow does its thing (section 6), returns a result object.
5. View renders `partials/message_pair.html` with that result — **returns HTML, not JSON**.
6. HTMX swaps that fragment into the message list (`hx-target`, `hx-swap="beforeend"`). No page reload, no client-side JS state to manage.

**Uploading a document:**
1. Browser: file `<form>` in `documents` app, `hx-post="/documents/upload/"`, `hx-encoding="multipart/form-data"`.
2. View saves the upload, calls `documents/ingest.py` (ported from the reference's `pdf_ingest.py`/`csv_ingest.py`): extract text, split into chunks, create `Document` + `DocumentChunk` rows.
3. Saving a `DocumentChunk` triggers the `search_vector` update (Day 7 detail).
4. View returns an updated document-list fragment.

---

## 8. Environment / infrastructure

| Piece | How it runs | Already have it? |
|---|---|---|
| Python + Django | `uv`-managed venv, per your established workflow (`uv init && uv sync`) | uv ✅, need to add Django |
| PostgreSQL | Homebrew (`brew install postgresql@17`), one local database | ❌ not installed yet — Day 1 |
| Redis | Homebrew (`brew install redis`, `brew services start redis`) — no container runtime needed for a single local service | ❌ not installed yet — Day 1 |
| Ollama | already running locally | ✅ `llama3.2` already pulled |
| Docker | **not needed for Day 1–10.** Introduced deliberately at Day 11+ if/when we containerize the stack for deployment. | — |

---

## 9. Curriculum — one session at a time

No-water, hands-on, one day builds directly on the last. Each day ends with something *running* that you can see, not just files written.

- ~~**Day 1 — Foundations.**~~ **DONE 2026-09-09.** `uv init` (with `package = false` — this is an application, not a distributable library), Django + `psycopg[binary]` + `django-environ` + `redis` + `ollama` added as dependencies. `postgresql@17` and `redis` installed via Homebrew (no container runtime — see section 2/8), both running as `brew services`. Database `django_agentic_ai` created. `django-admin startproject config .`; apps `accounts`, `chat`, `documents` created via `startapp` and registered in `INSTALLED_APPS` using the **explicit AppConfig path** (`"accounts.apps.AccountsConfig"`, etc. — deliberate, not the short `"accounts"` form, because Day 7's search-index signal will live in `DocumentsConfig.ready()`); `agents/` created as a plain Python package (`__init__.py` only) — **not** registered in `INSTALLED_APPS`, since it has no models/admin/signals, just plain orchestration code. `settings.py` reads `SECRET_KEY`/`DEBUG`/`ALLOWED_HOSTS`/`DATABASE_URL`/`REDIS_URL`/`OLLAMA_BASE_URL`/`OLLAMA_MODEL` from `.env` via `django-environ`. `manage.py migrate` ran successfully against real Postgres (verified via `psql \dt`, not just "no errors"). `manage.py runserver` verified with an actual `curl` returning HTTP 200 and the default Django success page. Ollama connectivity verified from Python directly via the `ollama` client (same one `agents/llm_service.py` will use later). *You learned:* project vs. app, settings module, migrations, what `uv sync`/`package = false` means for a Django project, and the real mechanism behind `INSTALLED_APPS` string vs. explicit `AppConfig` path.
- ~~**Day 2 — Accounts.**~~ **DONE 2026-09-10.** Built `accounts/forms.py` (`RegisterForm`, extending `UserCreationForm` with an email field), `accounts/views.py` (`register`, `home`), `accounts/urls.py` (wired to `LoginView`/`LogoutView` + our own two views), `config/urls.py` (`include("accounts.urls")` at root), `config/settings.py` (`LOGIN_URL`/`LOGIN_REDIRECT_URL`/`LOGOUT_REDIRECT_URL`), and four templates (`base.html`, `register.html`, `login.html`, `home.html` — these four were written directly rather than typed line-by-line, per [[feedback_hands_on_typing]]'s HTML exception). Verified for real: 3 rows in `auth_user` (`gurudev` superuser via `createsuperuser`, `Mahadev`/`Solver` self-registered, correctly `is_staff=f`/`is_superuser=f`), a live `django_session` row, and the full register→login→home→logout loop clicked through in a real browser. Bugs caught and fixed along the way (real learning moments, not just typing): `=` vs `==` in an `if`, an `else` indented to the wrong `if` (silently discarding form validation errors), `LoginView` pasted instead of `LogoutView` in the logout route. Also hit — and now understand — Django's CSRF-token-rotates-on-login behavior, which 403s a stale already-loaded tab's form after logging into `/admin/` elsewhere; not a bug, just needs a page reload. *You learned:* Django's auth system, sessions vs. JWT (and why we chose sessions), CSRF (both the protection itself and its token-rotation-on-login edge case), template inheritance, class-based vs. function-based views.
- ~~**Day 3 — Chat models & static shell.**~~ **DONE 2026-09-13.** Built `chat/models.py` (`Conversation` with a UUID primary key + `user` FK; `Message` with a `conversation` FK using `related_name="messages"`, `role`/`content`/`route`/`created_at`), ran `makemigrations chat` + `migrate chat` against real Postgres, registered both models in `chat/admin.py`, `chat/forms.py` (`MessageForm`, a `ModelForm` restricted to `fields = ["content"]` only — role/conversation/timestamp are set server-side, never trusted from the client), `chat/views.py` (`chat_view`: `get_or_create`s one implicit `Conversation` per user, POST saves a real `Message` plus a canned `"Echo: ..."` assistant reply tagged `route="echo"` as an explicit Day-3 placeholder, POST-redirect-GET back to `"chat"`, GET renders `chat_messages` ordered by `created_at`), `chat/urls.py` + `config/urls.py` wiring (`/chat/`), and `chat/templates/chat/chat.html` + a "Chat" nav link added to `base.html` (these two HTML pieces written directly per [[feedback_hands_on_typing]]'s exception). Verified for real: a `chat_conversation` row for `gurudev` and two `chat_message` rows (user + echoed assistant, correct chronological order) confirmed via `psql`, full browser round-trip (type message → Send → page reloads showing both bubbles) confirmed live. One real bug caught and fixed along the way: a missing colon on `if request.method == "POST"`. *You learned:* one-to-many relationships and which side a `ForeignKey` belongs on (the "many" side, pointing at the "one" side) and what `related_name` buys you (`conversation.messages.all()`/`.create()` instead of the generic `message_set`); `ModelForm` + restricting `fields` as a security boundary, not just convenience; `get_or_create()`'s 2-tuple return and the `_` "I'm ignoring this" convention; why `QuerySet`s need an explicit `.order_by()` (Postgres doesn't guarantee insertion order); a real context-processor naming collision (`chat_messages` instead of `messages`, to avoid shadowing `django.contrib.messages`' auto-injected `messages` context variable used by `base.html`'s flash-message block).
- ~~**Day 4 — HTMX wiring.**~~ **DONE 2026-09-13.** Loaded HTMX via CDN script tag in `base.html`. Split `chat/views.py`'s single `chat_view` into two: `chat_view` (GET-only now, just renders the full page) and a new `send_message` (`@login_required` + `@require_POST`, no manual `if request.method` check needed since `require_POST` enforces it) that saves the user+echoed-assistant `Message` pair and returns a rendered fragment instead of a redirect — falling back to `HttpResponse(status=400)` on an invalid submission (real inline error display deliberately deferred to Day 10, per plan). Added `chat/urls.py`'s `"send/"` route (`name="chat_send"`) and `chat/templates/chat/partials/message_pair.html` (a bare fragment, no `{% extends %}`) written directly per [[feedback_hands_on_typing]]'s HTML exception. `chat.html`'s form gained `hx-post`/`hx-target="#chat-messages"`/`hx-swap="beforeend"`/`hx-on::after-request="this.reset()"` — CSRF token needed no special handling since HTMX auto-serializes all fields (including hidden ones) inside an `hx-post` form. Verified for real: server log showed `POST /chat/send/ 200` (fragment, not redirect) on each send, page visibly didn't reload, and `psql` confirmed all 6 real `chat_message` rows across the session (2 from Day 3's redirect flow, 4 from today's HTMX flow) with correct role/route/content/timestamps. Two real bugs caught and fixed along the way: `MessageForm(require_POST)` (wrong name — autocomplete grabbed the decorator instead of `request.POST`) and a follow-up `MessageForm(require.POST)` typo (nonexistent `require` name) before landing on the correct `request.POST`. **Known deliberate rough edge:** `chat.html`'s `{% empty %}` "No messages yet" placeholder isn't removed by an HTMX append, so a very first message sent via HTMX (empty-conversation case) would leave that text visibly stale above the new real message — cosmetic only, not fixed today, scope explicitly deferred. *You learned:* `hx-post`/`hx-target`/`hx-swap` and how CSRF still works with HTMX with zero extra config; Django partial/fragment templates (no `{% extends %}`); `require_POST` as a cleaner alternative to a manual method check; decorator stacking order (`@login_required` above `@require_POST` — outermost decorator runs first); why POST-redirect-GET becomes unnecessary once the response is a fragment, not a full page.
- **Day 5 — First real LLM call.** `LLMService` wraps Ollama; wire one endpoint that sends a message straight to the LLM and shows the answer. *You learn:* calling a local LLM API from Python, prompt construction, synchronous client usage inside a Django view.
- **Day 6 — Supervisor & simple routing.** LLM-based route classification + keyword fallback; wire `greeting` and `summary` routes into the real chat flow. *You learn:* the agent pattern, single-responsibility classes, `try/except` graceful degradation.
- **Day 7 — Documents & ingestion.** Upload PDF/CSV, extract text (PyPDF2/pandas — same libraries the reference project used), chunk it, store `DocumentChunk` rows with a working `search_vector`. *You learn:* Postgres full-text search, file upload handling, Django signals.
- **Day 8 — Search agent, parallel route, grounded answers.** Wire full-text search into the chat flow; implement the `parallel` route (search + summary + a final grounded, cited answer) — the most complex path, matching the reference project's centerpiece feature. *You learn:* combining retrieval + generation (this *is* what "RAG" means), source citation formatting.
- **Day 9 — Redis caching.** Add the cache-aside layer: Postgres stays source of truth, Redis speeds up repeats. *You learn:* cache-aside pattern, TTLs, when caching helps vs. when it just adds complexity.
- **Day 10 — Hardening.** Rate limiting middleware, structured logging, consistent error handling across all four routes, a first pass at tests for the `agents` app (since it's plain Python, it's the easiest part to unit test). *You learn:* production-readiness concerns, Django middleware, testing business logic independent of the web layer.
- **Day 11+ (optional, later) —** streaming LLM responses, async Django views, Celery for background ingestion, and **Docker** as its own dedicated lesson (containerizing the full stack for deployment — the first time a container runtime enters this project at all). Not part of the core curriculum — only if you want to keep going after Day 10.

---

## 10. Open items to resolve when we actually start

- Exact Ollama model to standardize on for each capability (routing needs to be fast/cheap; summarization/grounded-answer can afford something slower). `llama3.2` (3B) confirmed reachable from Python on Day 1 — good enough to start Day 1-6 with; we can evaluate pulling a second, larger model once Day 8's grounded-answer quality is something to judge.
- ~~Whether podman/podman-compose is installed for Redis~~ — resolved 2026-09-08: no container runtime for Day 1–10, Redis runs via `brew install redis`. See the decisions table (section 2) and section 8.
- Project git remote: local-only for now; tell me if/when you want a GitHub repo for this one, same pattern as your dotfiles.

---

## 11. Verification cheat-sheet — checking real Postgres state

Always run these from the project directory. The `export PATH=...` line puts Homebrew's `psql` (17) ahead of any other `psql` on your system — needed once per terminal session (skip it if `psql` already works without it).

```bash
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
```

**Connect to the project database (interactive shell):**
```bash
psql -d django_agentic_ai
```
Once inside, `\q` quits. Everything below also works as a one-off `psql -d django_agentic_ai -c "..."` without entering the interactive shell.

**List all tables** (confirms a migration actually created something):
```bash
psql -d django_agentic_ai -c "\dt"
```

**Show one table's columns, types, indexes, and foreign keys** (confirms a model's fields match what's really in the database):
```bash
psql -d django_agentic_ai -c "\d chat_conversation"
psql -d django_agentic_ai -c "\d chat_message"
```

**See actual rows** — swap the table/columns for whatever you're checking:
```bash
psql -d django_agentic_ai -c "SELECT id, username, email, is_staff, is_superuser FROM auth_user ORDER BY id;"
psql -d django_agentic_ai -c "SELECT id, user_id, created_at FROM chat_conversation ORDER BY created_at;"
psql -d django_agentic_ai -c "SELECT id, conversation_id, role, route, content, created_at FROM chat_message ORDER BY created_at;"
```

**Count rows** (quick sanity check without printing everything):
```bash
psql -d django_agentic_ai -c "SELECT count(*) FROM chat_message;"
```

**Check which migrations Django has actually applied** (matches migration *files* against what's really been run against this database — useful if `makemigrations` and `migrate` ever seem out of sync):
```bash
uv run manage.py showmigrations chat
```

**Live session table** (same one auth uses — confirms a login really created a session row):
```bash
psql -d django_agentic_ai -c "SELECT session_key, expire_date FROM django_session ORDER BY expire_date DESC LIMIT 5;"
```

---

*Next step: Day 1, whenever you're ready. Just say "let's start Day 1" in a new session and I'll read this file and pick up exactly here.*
