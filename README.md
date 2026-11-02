# SignalScope

SignalScope is a Django market-intelligence dashboard. Authenticated users can
create market reports, review sentiment and SWOT analysis, and download a
plain-text report with external research reference links.

## Requirements

- Python 3.13 or a Python version supported by Django 6.1
- A Groq API key for live AI analysis
- A persistent PostgreSQL database for Vercel deployments

## Local setup

From the project directory, create and activate a virtual environment, then
install dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env`. Replace `DJANGO_SECRET_KEY` with a new,
uncommitted random value, and set `GROQ_API_KEY` to a valid Groq API key.
The `.env` file is ignored by Git.

Apply migrations and create an administrator account:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/` to log in or register. Registration requires
confirming that the user is at least 18 years old. Reports are scoped to their
authenticated owner. Reports created before ownership was introduced remain
unassigned and are not exposed in user dashboards.

## Tests

```powershell
python manage.py check
python manage.py test analyzer
python manage.py makemigrations --check --dry-run
```

## Notes

- SQLite is configured for local development.
- Report processing currently uses a daemon thread in the Django process.
  Production deployments should use a durable task queue so work survives
  process restarts.
- SWOT reports include media metadata, but the downloadable document contains
  only report text and search/reference URLs. SignalScope does not download,
  host, or hotlink external media.
- Tailwind is loaded from its CDN in the templates for convenient development.
  A production deployment should build and serve static CSS locally.

## Vercel deployment

Vercel runs Django as a serverless Python function. The project detects the
Vercel environment, disables Django debug mode, trusts Vercel HTTPS proxy
headers, enables secure cookies, and processes report requests inline rather
than starting a daemon thread that would be terminated after the function
returns.

SQLite is intentionally rejected on Vercel because serverless function
filesystems are not a persistent database. Before deploying:

1. Connect the GitHub repository `irzanahmad/MarketResearcher` to a Vercel
   project and use the repository root as the project root.
2. Provision a persistent PostgreSQL database (for example, a Vercel
   Marketplace PostgreSQL provider) and set `DATABASE_URL` in the Vercel
   project environment variables. Do not commit this URL.
3. Set `DJANGO_SECRET_KEY` to a newly generated secret and set
   `DJANGO_ALLOWED_HOSTS` to the production hostname if it is not a
   `*.vercel.app` hostname.
4. Set a newly rotated `GROQ_API_KEY` and, if needed, `GROQ_MODEL`.
5. Add the production domain to `DJANGO_CSRF_TRUSTED_ORIGINS` with its
   `https://` scheme.
6. Deploy, then run `python manage.py migrate` against the configured
   production `DATABASE_URL` before accepting traffic.

The in-process report worker is retained for local development. Vercel runs
report processing synchronously in the request, with a bounded API timeout;
this avoids silently losing tasks when serverless functions shut down. For
higher traffic, move processing to a durable queue and worker.
