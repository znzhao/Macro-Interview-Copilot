# Deployment & Setup Guide

Step-by-step: create the Supabase backend, run it locally, and deploy to Streamlit Community Cloud — without ever committing a secret.

← [PROJECT_SPEC.md](../PROJECT_SPEC.md) · [DATA_SPEC.md](DATA_SPEC.md) · [PHASE_TRACKER.md](../PHASE_TRACKER.md)

---

# 0. The secrets model (read this first)

Your concern is the right one, and it's already handled. Three separate things:

| Where | What lives there | Committed to Git? |
|---|---|---|
| `.streamlit/secrets.toml.example` | Placeholder values, documentation | **Yes** — it's a template, contains nothing real |
| `.streamlit/secrets.toml` | Your real local credentials | **No** — [`.gitignore:10`](../.gitignore) excludes it |
| Streamlit Cloud → Settings → Secrets | Your real production credentials | **No** — stored encrypted by Streamlit, never touches the repo |

**You never push credentials.** Locally you keep a gitignored file; in production you paste the same TOML into a box in the Streamlit Cloud dashboard, and Streamlit injects it as `st.secrets` at runtime. Same code, same `st.secrets` API, two different sources.

## The one key that matters

Supabase gives you two kinds of API key. Getting this wrong is the actual security risk — bigger than committing the file.

| Key | Also called | Safe to expose? | Use here? |
|---|---|---|---|
| `anon` / `publishable` | public key, `eyJ...` or `sb_publishable_...` | **Yes** | ✅ This is the one |
| `service_role` / `secret` | `eyJ...` or `sb_secret_...` | **No — total database access** | ❌ Never, not even in secrets.toml |

The `anon` key is *designed* to sit in a browser-facing app. It's harmless on its own because [Row Level Security](DATA_SPEC.md#62-row-level-security) constrains what any request carrying it can actually read or write. The `service_role` key **bypasses RLS entirely** — anyone holding it can read every user's data. It is never used by this app. `core/db/client.py` only ever reads `supabase.anon_key`.

> If you ever paste a `service_role` key into Streamlit Cloud secrets, treat it as compromised and rotate it in the Supabase dashboard immediately.

---

# 1. Create the Supabase project

1. Sign up at [supabase.com](https://supabase.com) and create a **New project**.
2. Fill in:
   - **Name** — e.g. `macro-interview-copilot`
   - **Database Password** — generate a strong one and **save it in a password manager**. You need it in step 3 and it is not recoverable, only resettable.
   - **Region** — pick one near you.
3. Wait ~2 minutes for provisioning.

> **If a menu path below doesn't match what you see:** Supabase redesigns its dashboard fairly often. The `Search…` box at the top-right of the Supabase page (shortcut `Ctrl-K` in the browser) searches every settings page and beats hunting through the sidebar. Connection strings in particular now live behind the top-bar **Connect** button rather than in Project Settings.
>
> Throughout this guide, all menu paths refer to the **Supabase dashboard in your web browser** unless a step explicitly says otherwise.

> **Free tier note:** the project pauses after ~7 days of inactivity. The app handles this with a "waking the database" message rather than a crash ([ARCHITECTURE §5](ARCHITECTURE.md#5-error-handling--failure-modes)), but first load after a pause takes ~30 seconds.

---

# 2. Create the schema

Easiest path — no connection string needed.

1. In your project, open **SQL Editor** in the left sidebar.
2. Click **New query**.
3. Open [`core/db/migrations/0001_init.sql`](../core/db/migrations/0001_init.sql), copy the **entire file**, paste it in, and click **Run**.
4. Supabase will warn: *"This query creates tables without enabling Row Level Security."* → choose **Run and enable RLS**. See the note below.
5. New query again. Copy **all** of [`core/db/migrations/0002_rls.sql`](../core/db/migrations/0002_rls.sql), paste, **Run**.

Order matters — `0002` creates policies on tables `0001` defines.

> **About that RLS warning.** It's correct: `0001` creates tables, and `0002` is what enables RLS and adds policies. Both buttons work, but **Run and enable RLS** is strictly better — it closes the window between the two files where tables would accept anon-key reads. Supabase just appends `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`, leaving RLS on with no policies yet, which Postgres treats as deny-everything. `0002`'s own identical `ALTER TABLE` lines are then harmless no-ops.
>
> Your admin scripts are unaffected either way: `seed_db.py` and `apply_migrations.py` connect directly as the `postgres` role, which owns these tables and therefore bypasses RLS.

## If a migration fails partway

`0001_init.sql` has no wrapping transaction, so a failure can leave some objects created and others not — and re-running then trips over `type ... already exists`. On a fresh project with no data, reset to a clean slate and start §2 over:

```sql
-- Destroys everything in the public schema. Safe ONLY before you have real data.
drop trigger if exists on_auth_user_created on auth.users;
drop schema public cascade;
create schema public;

-- Restore Supabase's default grants on the recreated schema.
grant usage on schema public to postgres, anon, authenticated, service_role;
grant all   on schema public to postgres, service_role;
alter default privileges in schema public
  grant all on tables    to postgres, anon, authenticated, service_role;
alter default privileges in schema public
  grant all on functions to postgres, anon, authenticated, service_role;
alter default privileges in schema public
  grant all on sequences to postgres, anon, authenticated, service_role;
```

The `drop trigger` line matters: `on_auth_user_created` lives on `auth.users`, outside the `public` schema, so `drop schema public cascade` won't remove it on its own.

**Verify it worked.** Run this in the SQL Editor:

```sql
select tablename, rowsecurity
from pg_tables
where schemaname = 'public'
order by tablename;
```

You should see **11 tables**. Ten of them — `profiles`, `questions`, `question_votes`, `question_reports`, `interview_sessions`, `interview_turns`, `evaluations`, `topic_mastery`, `notes`, `favorites` — must show `rowsecurity = true`. If any of those ten says `false`, `0002_rls.sql` didn't fully apply: re-run it and read the error.

The eleventh, `schema_migrations`, is an internal migration ledger touched only by direct-connection admin scripts, so `0002` deliberately doesn't cover it. It will read `true` if you chose "Run and enable RLS" and `false` otherwise — both are fine.

> **Why not `scripts/apply_migrations.py`?** It works and records checksums in `schema_migrations`, which is the right tool for *later* migrations. But it needs the direct Postgres connection string and psycopg working locally, which is more moving parts for a first run. The SQL Editor is fine for the initial two. If you use the SQL Editor, record them manually so the script doesn't try to re-apply them later — but the checksum has to be the file's **real** SHA-256, not a placeholder string: the script hard-fails (by design — it's what stops someone from silently editing an applied migration) if a recorded checksum doesn't match the file on disk. Compute the real ones and generate the exact `insert` to run:
>
> ```bash
> ./.venv/Scripts/python.exe -c "
> import hashlib
> from pathlib import Path
> for name in ['0001_init', '0002_rls']:
>     p = Path('core/db/migrations') / f'{name}.sql'
>     print(f\"insert into schema_migrations (version, checksum) values ('{name}', '{hashlib.sha256(p.read_text(encoding='utf-8').encode('utf-8')).hexdigest()}') on conflict (version) do nothing;\")
> "
> ```
>
> Paste the two `insert` statements this prints into the SQL Editor and run them.

---

# 3. Seed the question bank

Seeding writes verified-tier questions, which RLS deliberately restricts to admins. So it runs over a **direct database connection** rather than through the app's anon key — this is exactly why the app itself never needs elevated credentials.

1. In Supabase, click the green **Connect** button in the top bar (next to the branch selector). Connection strings live here — *not* in the Project Settings sidebar. In the modal, choose the **Direct** tab (subtitled "Connection string"); despite the name it contains every variant, poolers included. Ignore the **Framework** tab — that's JS scaffolding.
2. Copy the **Session pooler** URI. It looks like:
   ```
   postgresql://postgres.<project-id>:[YOUR-PASSWORD]@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```
3. Replace `[YOUR-PASSWORD]` with the database password from step 1. (Forgot it? The Connect modal links to a reset — safe to do, nothing depends on it yet.)

> **Use Session pooler, not Transaction pooler.** The transaction pooler (port 6543) doesn't support prepared statements, and psycopg3 begins preparing a statement automatically after a few executions — seeding runs the same UPSERT 40 times, so it would fail partway. Session pooler (port 5432) behaves like a direct connection. The raw direct connection (`db.<project-id>.supabase.co`) also works but now requires IPv6 unless you've bought the IPv4 add-on.

Then put it in a `.env` file at the repo root — no shell variables needed:

4. Copy [`.env.example`](../.env.example) to `.env`.
5. Paste your connection string as the `DATABASE_URL` value, password substituted in. One line, no quotes:
   ```
   DATABASE_URL=postgresql://postgres.xxxx:YOURPASSWORD@aws-0-us-west-2.pooler.supabase.com:5432/postgres
   ```
6. Run the seed script. Any of these work — the scripts bootstrap their own import path and read `.env` automatically:
   - **In VS Code:** open `scripts/seed_db.py` and click the ▷ Run button.
   - **Terminal:** `./.venv/Scripts/python.exe scripts/seed_db.py`

Expect: `Seeded 40 question(s) from ...`.

Verify in the Supabase SQL Editor:

```sql
select count(*), tier from questions group by tier;
```

Should return 40, all `verified`.

> **`.env` is not app configuration.** It holds your database password and grants unrestricted access, bypassing RLS. It is gitignored, used only by the local admin scripts (`seed_db.py`, `apply_migrations.py`, `export_questions.py`), and **never** goes into `.streamlit/secrets.toml` or Streamlit Cloud. The deployed app has no use for it — it reaches Supabase through the anon key and RLS instead.
>
> Two separate files, two separate purposes:
> | File | Holds | Used by |
> |---|---|---|
> | `.env` | Postgres URI + DB password | local admin scripts only |
> | `.streamlit/secrets.toml` | project URL + **anon** key | the app, locally |
> | Streamlit Cloud secrets | project URL + **anon** key | the app, in production |

---

# 4. Configure authentication

## 4.1 What this step is for

Signing in with a magic link works like this:

1. You enter your email → the app asks Supabase to *"email this person a login link, and send their browser back to `http://localhost:8501` afterwards."*
2. **Supabase checks that return URL against an allow-list.** If it isn't on the list, Supabase refuses and sends them to the Site URL instead.
3. You click the link → Supabase verifies you → your browser lands back on the app with `?code=...` in the URL.
4. The app exchanges that code for a session (`_handle_oauth_callback` in [`streamlit_app.py`](../streamlit_app.py)).

The allow-list exists so nobody can craft a link that delivers *your* login token to *their* server. It is not optional.

**Symptom if you skip this:** the email arrives, you click it, and you land on the app still signed out — with no error shown.

## 4.2 Set the URLs

Two ways to get there, both **in the Supabase dashboard in your browser** (not in your code editor):

- **By clicking:** far-left icon rail → **Authentication** (person/shield icon) → under the *Configuration* heading, **URL Configuration**.
- **By search:** click the `Search…` box in the top-right of the Supabase page (or press `Ctrl-K` with that browser tab focused) → type `URL Configuration` → Enter. This is worth knowing generally, since Supabase relocates menu items fairly often.

Set two fields:

| Field | Value now | Why |
|---|---|---|
| **Site URL** | `http://localhost:8501` | Fallback destination when no explicit redirect is given |
| **Redirect URLs** | `http://localhost:8501` | The allow-list. Click *Add URL* |

`8501` is Streamlit's default local port. This must match `app.app_url` in your secrets **character for character** — `http` vs `https`, and no trailing slash.

**You do not have a production URL yet** — you choose that subdomain in §7. Come back to this page afterwards and:

- **Add** `https://your-app-name.streamlit.app` to Redirect URLs, keeping `http://localhost:8501` so local development still works.
- **Change** Site URL to the production URL.

The end state is one Supabase project serving both environments: Site URL pointing at production, and both URLs on the allow-list.

## 4.3 Disable "Confirm email" — REQUIRED

The app signs in with **email + password**, which needs no email round-trip. One setting must be turned off for that to work end to end.

Go to **Authentication → Providers → Email** and switch **"Confirm email" OFF**, then save.

With it on, Supabase creates the account but withholds the session until the user clicks a confirmation email — and that email uses Supabase's default template, which is unusable here for the reason in §4.3.1 below. The app detects this state and raises `EmailConfirmationRequired` with a message pointing back at this setting, rather than failing mysteriously.

**Trade-off, stated plainly:** email addresses are then unverified, so someone could register with an address they don't own. For a personal study tool whose data is per-user and RLS-isolated, that's an acceptable trade. If you later want verified emails, set up custom SMTP and switch to the magic-link path (§4.3.2).

### 4.3.1 Why not magic links (yet)

Magic links look like the nicer option, but two things block them on the free tier:

**First, the fragment problem.** Supabase's default email link returns the session in the URL *fragment*:

```
http://localhost:8501/#access_token=eyJ...&refresh_token=...
```

Browsers never transmit anything after `#` to the server. Streamlit renders server-side, so `st.query_params` cannot see it — the tokens are visible to the browser and invisible to your Python code. Sign-in silently fails: you click the link, land back on the app, and are still signed out. This affects every server-rendered framework, not just Streamlit.

The fix is Supabase's `token_hash` flow, which puts a single-use token in the query string. That requires editing the email templates — and **template editing is locked behind custom SMTP or a Pro plan.**

**Second, the rate limit.** Supabase's built-in mailer allows only a handful of messages per hour. That's survivable while testing alone, but it breaks a publicly shared app regardless of the template issue.

So custom SMTP is required either way before magic links are viable. Password auth avoids all of it.

### 4.3.2 Enabling magic links later

Once you want them, in order:

1. Configure custom SMTP under **Authentication → Emails → SMTP Settings** (Resend, SendGrid, and Postmark all have free tiers). This also unlocks template editing.
2. Edit **both** templates under **Authentication → Emails → Templates**. Both matter — a brand-new account receives "Confirm signup", so editing only "Magic Link" leaves first-time sign-in broken.

   **Confirm signup:**
   ```html
   <h2>Confirm your email</h2>
   <p><a href="{{ .RedirectTo }}?token_hash={{ .TokenHash }}&type=signup">Confirm and sign in</a></p>
   ```

   **Magic Link:**
   ```html
   <h2>Sign in to Macro Interview Copilot</h2>
   <p><a href="{{ .RedirectTo }}?token_hash={{ .TokenHash }}&type=magiclink">Sign in</a></p>
   ```

   `{{ .RedirectTo }}` resolves to whatever the app passed as its redirect — `app_url` from your secrets — so the same templates serve both localhost and production. (`{{ .SiteURL }}` would hard-code one environment.)

3. Surface `sign_in_with_magic_link` in the landing page UI. The callback side is already built: `_handle_auth_callback` ([`streamlit_app.py`](../streamlit_app.py)) reads `?token_hash=` and `complete_session_from_token_hash` ([`core/auth.py`](../core/auth.py)) verifies it.

## 4.5 Google OAuth (optional — skip for now)

Magic link alone is enough to complete Phase 1. The "Continue with Google" button will simply error until this is configured, which is harmless.

When you do want it: **Authentication → Providers → Google**. It requires creating an OAuth client in Google Cloud Console and pasting the callback URL Supabase displays into it. Leaving it off does not block anything else in this guide.

---

# 5. Create your local secrets file

In your editor, duplicate `.streamlit/secrets.toml.example` and name the copy `.streamlit/secrets.toml` (in VS Code: right-click the file → Copy, then right-click the `.streamlit` folder → Paste, then rename). No terminal needed.

Then fill in two values from the Supabase dashboard → **Project Settings → API Keys**:

- **Project URL** → `url`
- **Publishable** key (a.k.a. *anon* / *public*) → `anon_key`

The finished file:

```toml
[supabase]
url = "https://xxxxxxxxxxxxxxxx.supabase.co"
anon_key = "sb_publishable_xxxxxxxx"   # the PUBLIC key — see note below

[app]
environment = "development"
app_url = "http://localhost:8501"
admin_emails = ["you@example.com"]
```

> **Two key formats exist.** Newer projects issue `sb_publishable_...`; older ones issue a legacy `anon` JWT starting `eyJ...`. Either works with `supabase-py` and both go in the same `anon_key` field. If your project offers both, prefer the newer `sb_publishable_` one. What matters is that it's the *publishable/anon* key and never the `sb_secret_...` / `service_role` one.

**Confirm Git is ignoring it.** In VS Code's Source Control panel, `secrets.toml` must **not** appear in the Changes list — only `secrets.toml.example` and `config.toml` should. If `secrets.toml` ever shows up there, stop and check [`.gitignore`](../.gitignore) before committing anything.

---

# 6. Run it locally

```bash
./.venv/Scripts/python.exe -m streamlit run streamlit_app.py
```

Leave the terminal running — a server occupies it by design. Open **http://localhost:8501** in your browser.

On the landing page, use the **Create account** tab: enter your email and a password (6+ characters) → **Create account**. You should be signed in immediately, with Dashboard / Question Bank / Settings in the sidebar. On later visits use the **Sign in** tab.

If you instead see a warning about email confirmation, "Confirm email" is still enabled in Supabase — see §4.3.

## Make yourself an admin

Signing up creates your `profiles` row via trigger, but `is_admin` defaults to `false`. After your first sign-in, run in the SQL Editor:

```sql
update profiles
set is_admin = true
where id = (select id from auth.users where email = 'you@example.com');
```

Refresh the app — the Admin page appears. (`admin_emails` in secrets is a bootstrap hint only; [the database column is the real authority](DATA_SPEC.md#62-row-level-security).)

---

# 7. Deploy to Streamlit Community Cloud

1. Push the repo to GitHub. Verify one last time that no secret went with it:
   ```bash
   git ls-files | grep -i secret     # should show ONLY secrets.toml.example
   ```
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. **Create app → Deploy a public app from a repo**:
   - **Repository:** your repo
   - **Branch:** `main`
   - **Main file path:** `streamlit_app.py`
   - **App URL:** choose your subdomain — note it, you need it in the next two steps
4. Before clicking Deploy, open **Advanced settings → Secrets** and paste your TOML — the same shape as your local file, with two values changed:

   ```toml
   [supabase]
   url = "https://xxxxxxxxxxxxxxxx.supabase.co"
   anon_key = "eyJhbGciOi..."

   [app]
   environment = "production"
   app_url = "https://your-app-name.streamlit.app"
   admin_emails = ["you@example.com"]
   ```

5. **Deploy.**

You can edit these later at any time via **⋮ → Settings → Secrets**. Saving restarts the app. Streamlit stores them encrypted and they are never exposed to the repo or to page source.

## Then close the loop on auth

Back in Supabase → **Authentication → URL Configuration**:
- Set **Site URL** to `https://your-app-name.streamlit.app`
- Confirm that URL is in **Redirect URLs**

Sign-in will not work in production until this matches `app_url`.

---

# 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Long traceback ending `AttributeError: 'Server' object has no attribute 'servers'` after pressing Ctrl-C | **Not a crash.** Cosmetic bug in Streamlit's shutdown path with newer uvicorn — look for `raise KeyboardInterrupt()` in the middle of the trace, which is you stopping the server | Ignore it. Nothing is wrong; the app ran fine. Irrelevant on Streamlit Cloud, where the container is simply killed |
| Terminal appears frozen after `streamlit run` | Working as intended — a server occupies the terminal while it runs | Leave it running and open `http://localhost:8501` in your browser |
| `RuntimeError: Invalid or missing configuration` on startup | Secrets missing or malformed | Check TOML section names are exactly `[supabase]` and `[app]`; `core/config.py` fails loudly by design |
| `operator class "gin_trgm_ops" does not exist` while running `0001_init.sql` | `pg_trgm` installed in the `extensions` schema, not on the search path | Run `create extension if not exists pg_trgm with schema extensions;` then `set search_path to public, extensions;` and re-run the migration |
| `42P17: generation expression is not immutable` | A `GENERATED ... STORED` column used a non-IMMUTABLE expression | Fixed — `search_tsv` now generates from the IMMUTABLE `questions_search_document()` wrapper. Pull the latest `0001_init.sql`, reset with the snippet in §2, and re-run |
| `type "question_tier" already exists` on re-run | A previous run failed partway through | Reset with the snippet in §2, then re-run from the top |
| Creating an account shows a warning about email confirmation | "Confirm email" is still enabled in Supabase | Turn it off — §4.3 |
| `Sign-in failed: Invalid login credentials` | Wrong password, or the account doesn't exist | Use the **Create account** tab first. Note Supabase's default minimum password length is 6 |
| **Magic link only:** click the link, land back signed out, no error | The email templates still use the default `{{ .ConfirmationURL }}`, returning tokens in a URL fragment a server-rendered app cannot read. A `#access_token=...` in the address bar confirms it | Apply the template edits in §4.3.2. If the address bar already shows `?token_hash=...`, the templates are fine — then check `app_url` matches a Supabase Redirect URL character for character |
| **Magic link only:** `the sign-in link was invalid or has already been used` | These tokens are single-use and expire after ~1 hour. Reloading the callback URL also triggers it | Request a fresh link |
| No email arrives at all | Free-tier SMTP rate limit | Wait an hour, or configure custom SMTP |
| "Waking the database" on first load | Free-tier project paused after ~7 days idle | Expected. Wait ~30s and refresh |
| Question Bank empty after sign-in | Seed step didn't run, or ran against a different project | Re-check `DATABASE_URL` pointed at this project; verify with `select count(*) from questions;` |
| Admin page missing | `is_admin` still false | Run the `update profiles` statement in §6, then refresh |
| `permission denied for table ...` | RLS working as intended, but a policy is too strict for what the page tried | Check the policy in [`0002_rls.sql`](../core/db/migrations/0002_rls.sql) against [DATA_SPEC §6.2](DATA_SPEC.md#62-row-level-security) |

---

# 9. If you ever do leak a key

Rotating is fast and worth doing without hesitation:

- **anon key leaked** — low severity (RLS protects you), but rotate anyway: **Project Settings → API Keys**. Update both your local `secrets.toml` and Streamlit Cloud secrets.
- **service_role key leaked** — treat as a full breach. Rotate immediately from the same page, then audit `auth.users` and your tables for unexpected rows.
- **Database password leaked** — reset it from the **Connect** modal's database-settings link.

Note that rotating does not remove the key from Git history if it was ever committed. If that happens, rotate first, then clean history (or, for a young personal project, delete and recreate the repo — usually faster than a filter-branch).

---

# 10. Where this leaves you

Once §1–§7 are done, [Phase 1's acceptance criteria](IMPLEMENTATION_GUIDE.md#phase-1--foundation) are testable end-to-end: sign up, browse and filter the bank, favorite and annotate, sign out, sign in from another device, and see your data. That is the point at which Phase 1 stops being "code complete" and becomes actually verified — see the Caveats in [PHASE_TRACKER.md](../PHASE_TRACKER.md).

**Moving this deployment to Phase 2?** See [IMPLEMENTATION_GUIDE §8 — Deploying Phase 2](IMPLEMENTATION_GUIDE.md#8-deploying-phase-2): three new migrations, no new secrets, and a step-by-step smoke test covering the whole author → submit → review → notify loop.
