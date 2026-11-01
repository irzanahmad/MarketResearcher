# SignalScope

SignalScope is a Django market-intelligence dashboard. Authenticated users can
create market reports, review sentiment and SWOT analysis, and download a
plain-text report with external research reference links.

## Requirements

- Python 3.13 or a Python version supported by Django 6.1
- A Groq API key for live AI analysis

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
