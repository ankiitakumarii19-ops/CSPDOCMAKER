# CSP Document Generation & Email Automation Platform

> Internal EKO enterprise application for automated CSP document generation, validation, and delivery.

## Architecture

| Layer | Technology |
|---|---|
| Frontend | Next.js + TypeScript + Tailwind CSS |
| Backend API | Python + FastAPI |
| Database | PostgreSQL 16 |
| Job Queue | Redis + Celery |
| Auth Source | Google Sheets API |
| Email | Gmail / Google Workspace API |
| SMS | Provider-independent abstraction |
| AI Validation | Controlled AI agent |

## Project Structure

```
CSPDOCMAKER/
├── frontend/          → Next.js web application
├── backend/           → FastAPI REST API + workers
├── agents/            → AI validation agent
├── templates/         → DOCX & email templates
├── database/          → Alembic migrations & seeds
├── tests/             → All test suites
├── scripts/           → Sync & maintenance scripts
├── docs/              → Project documentation
└── docker-compose.yml → Local dev orchestration
```

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- PostgreSQL 16 (via Docker)
- Redis 7 (via Docker)

### 1. Clone and configure
```bash
cp .env.example backend/.env
# Edit backend/.env with your actual configuration values
# Put the Google service-account JSON in backend/credentials/ (git-ignored)
```

### 2. Start infrastructure
```bash
docker-compose up -d
```

### 3. Backend setup
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
alembic upgrade head          # Run database migrations
uvicorn app.main:app --reload --port 8000
```

### 4. Start Celery worker and scheduler
```bash
cd backend
celery -A app.celery_app worker --loglevel=info   # executes tasks
celery -A app.celery_app beat --loglevel=info     # schedules the 1-minute CSP sync
```

### 5. Frontend setup
```bash
cd frontend
npm install
npm run dev
```

### 6. Access
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

## User Roles

| Role | Access |
|---|---|
| **RM** | CSP search, document generation, email sending |
| **Admin** | Dashboard, metrics, monitoring, audit logs |
| **System Owner** | Google Sheet authorization management |

## Key Workflows

1. **RM Workflow**: Login → Search CSP → Select documents → Generate → Validate → Confirm → Send email → SMS notification
2. **New CSP Automation**: Excel row detected → Validate → Generate docs → Validate docs → Send email → SMS → Complete

## Security

- HTTPS required in production
- `@eko.co.in` email domain enforcement
- Server-side role-based access control
- OTP two-factor authentication
- Google Sheet as authorization source of truth
- AI agent constrained — cannot override security controls

## License

Internal — EKO proprietary
