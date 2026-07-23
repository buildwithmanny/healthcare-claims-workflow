# Healthcare Claims Workflow

A Python and PostgreSQL project that simulates a stateful healthcare claims processing workflow with validation, eligibility checks, duplicate detection, pricing, review logic, retries, manual intervention, audit history, and operational reporting.

> This project uses entirely synthetic data and simplified business rules for educational and portfolio purposes. It does not reproduce proprietary healthcare systems, healthcare data, reimbursement methodology, fraud models, or adjudication logic.

## Project Status

**Current Phase:** Day 2 — Workflow Design and Initial Database Schema

Completed:

- Project structure created
- Python virtual environment configured
- Environment variables configured
- PostgreSQL database created
- Synthetic source datasets created
- CSV and JSON loading verified
- PostgreSQL connection verified
- Workflow stages defined
- Claim states defined
- Valid state transitions defined
- Initial PostgreSQL schema created

Next:

- Claim intake and validation

---

## Project Goal

Build a realistic healthcare claims processing workflow that moves synthetic claims through multiple operational stages while handling exceptions, temporary failures, retries, and manual intervention.

The project focuses on a central systems-design question:

> How does work move through a system when everything does not follow the happy path?

The goal is not simply to process claims.

The goal is to ensure that every claim has:

- A known current state
- A defined next action
- Controlled exception handling
- A complete processing history
- A final outcome

---

## Business Problem

Operational systems rarely follow a perfect linear path.

A claim or transaction may encounter:

- Missing information
- Invalid reference data
- Eligibility failures
- Duplicate submissions
- Missing pricing rules
- Temporary system failures
- Retry exhaustion
- High-risk conditions
- Manual review requirements

A reliable workflow must determine what should happen next in each situation.

The application therefore models both:

```text
Happy Path
```

and:

```text
Exception Paths
```

---

## Core Workflow

```text
RECEIVED
    ↓
VALIDATING
    ├── VALIDATION_FAILED
    ↓
ELIGIBILITY_CHECK
    ├── INELIGIBLE
    │       ↓
    │     DENIED
    ↓
DUPLICATE_CHECK
    ├── DUPLICATE
    ↓
PRICING
    ├── PRICING_RETRY
    │       ↓
    │     PRICING
    │       │
    │       └── MANUAL_REVIEW / FAILED
    │
    ├── MANUAL_REVIEW
    ↓
FRAUD_REVIEW
    ├── MANUAL_REVIEW
    ├── DENIED
    ↓
APPROVED
```

---

## Workflow Stages

The main automated processing stages are:

1. Claim Intake
2. Validation
3. Eligibility Check
4. Duplicate Check
5. Pricing
6. Fraud / Rules Review
7. Approval or Denial
8. Reporting

Exception processing may introduce:

- Validation failure
- Ineligibility
- Duplicate detection
- Pricing retries
- Manual review
- System failure

---

## Claim States

Every claim has one current workflow state.

### Intake State

```text
RECEIVED
```

The claim has entered the workflow but processing has not started.

### Validation States

```text
VALIDATING
VALIDATION_FAILED
```

`VALIDATING` indicates that required claim fields and reference values are being checked.

`VALIDATION_FAILED` indicates that the claim cannot continue because required information is missing or invalid.

### Eligibility States

```text
ELIGIBILITY_CHECK
INELIGIBLE
```

`ELIGIBILITY_CHECK` indicates that member coverage is being evaluated.

`INELIGIBLE` records that the member did not meet eligibility requirements for the service date.

An ineligible claim then transitions to:

```text
DENIED
```

### Duplicate States

```text
DUPLICATE_CHECK
DUPLICATE
```

`DUPLICATE_CHECK` indicates that the claim is being compared against previously processed claims.

`DUPLICATE` indicates that the claim matched the project's duplicate criteria and will not continue through automated processing.

### Pricing States

```text
PRICING
PRICING_RETRY
```

`PRICING` indicates that the application is attempting to assign a synthetic allowed amount.

`PRICING_RETRY` indicates that a temporary pricing failure occurred and another attempt may be made.

### Review States

```text
FRAUD_REVIEW
MANUAL_REVIEW
```

`FRAUD_REVIEW` represents automated evaluation against simplified synthetic review rules.

`MANUAL_REVIEW` indicates that automated processing has stopped and human intervention is required.

### Final States

```text
VALIDATION_FAILED
DUPLICATE
APPROVED
DENIED
FAILED
```

These states represent completed workflow outcomes.

A claim in a final state cannot continue automatically to another state.

---

## Valid State Transitions

Claims cannot move arbitrarily between workflow states.

Valid transitions are explicitly defined.

### Intake

```text
RECEIVED
    ↓
VALIDATING
```

An unexpected processing failure may also result in:

```text
RECEIVED
    ↓
FAILED
```

### Validation

```text
VALIDATING
    ├── ELIGIBILITY_CHECK
    ├── VALIDATION_FAILED
    └── FAILED
```

A claim cannot move directly from:

```text
VALIDATING
```

to:

```text
APPROVED
```

### Eligibility

```text
ELIGIBILITY_CHECK
    ├── DUPLICATE_CHECK
    ├── INELIGIBLE
    └── FAILED
```

An ineligible determination leads to:

```text
INELIGIBLE
    ↓
DENIED
```

### Duplicate Detection

```text
DUPLICATE_CHECK
    ├── DUPLICATE
    ├── PRICING
    └── FAILED
```

### Pricing

```text
PRICING
    ├── FRAUD_REVIEW
    ├── PRICING_RETRY
    ├── MANUAL_REVIEW
    └── FAILED
```

### Retry Processing

```text
PRICING_RETRY
    ├── PRICING
    ├── MANUAL_REVIEW
    └── FAILED
```

A successful retry returns the claim to pricing.

An unresolved failure may eventually require manual review or end in a failed state.

### Fraud / Rules Review

```text
FRAUD_REVIEW
    ├── APPROVED
    ├── DENIED
    ├── MANUAL_REVIEW
    └── FAILED
```

### Manual Review

```text
MANUAL_REVIEW
    ├── APPROVED
    ├── DENIED
    └── FAILED
```

---

## Workflow Rules

### Rule 1 — Claims Must Follow Valid State Transitions

Claims cannot skip required processing stages.

For example:

```text
RECEIVED → APPROVED
```

is invalid.

A valid happy-path sequence is:

```text
RECEIVED
    ↓
VALIDATING
    ↓
ELIGIBILITY_CHECK
    ↓
DUPLICATE_CHECK
    ↓
PRICING
    ↓
FRAUD_REVIEW
    ↓
APPROVED
```

---

### Rule 2 — Validation Failures Stop Processing

A claim cannot continue if required information is missing or invalid.

Examples may eventually include:

- Missing member ID
- Missing diagnosis code
- Invalid diagnosis code
- Missing procedure code
- Invalid billed amount

The claim transitions to:

```text
VALIDATION_FAILED
```

---

### Rule 3 — Eligibility Must Be Confirmed Before Further Processing

A member must:

- Exist in the member dataset
- Have active member status
- Have coverage on the date of service

An ineligible claim transitions:

```text
ELIGIBILITY_CHECK
    ↓
INELIGIBLE
    ↓
DENIED
```

---

### Rule 4 — Duplicate Claims Do Not Continue to Pricing

The initial duplicate rule will compare claims using:

- Member ID
- Provider ID
- Procedure code
- Service date

A matching claim may transition:

```text
DUPLICATE_CHECK
    ↓
DUPLICATE
```

---

### Rule 5 — Pricing Failures Are Classified

Pricing failures are divided into two categories.

#### Temporary Failure

Examples:

- Simulated timeout
- Temporary service failure

The claim transitions:

```text
PRICING
    ↓
PRICING_RETRY
```

#### Permanent or Unresolved Failure

Examples:

- Missing pricing configuration
- Retry exhaustion
- Condition requiring investigation

The claim may transition:

```text
PRICING
    ↓
MANUAL_REVIEW
```

or:

```text
PRICING_RETRY
    ↓
MANUAL_REVIEW
```

---

### Rule 6 — Retries Must Have Limits

Temporary failures cannot retry indefinitely.

The initial project policy is:

```text
Maximum retries = 3
```

A retry record tracks:

- Failed processing step
- Current retry count
- Maximum retry count
- Next retry time
- Retry status
- Last error

Possible retry statuses are:

```text
PENDING
PROCESSING
SUCCEEDED
EXHAUSTED
CANCELLED
```

---

### Rule 7 — Some Claims Require Manual Review

Automated processing may intentionally stop when a claim requires human intervention.

Examples may include:

- High billed amount
- Repeated claim activity
- Certain procedure codes
- Unresolved pricing failures
- Retry exhaustion

Manual review statuses include:

```text
PENDING
IN_REVIEW
APPROVED
DENIED
RESOLVED
```

---

### Rule 8 — Every Major State Change Must Be Auditable

The system will maintain two different views of claim state.

The `claims` table stores:

```text
Current State
```

The `claim_events` table stores:

```text
State History
```

Example:

```text
Claim CLM001

RECEIVED
    ↓
VALIDATING
    ↓
ELIGIBILITY_CHECK
    ↓
DUPLICATE_CHECK
    ↓
PRICING
```

The current claim record may only show:

```text
PRICING
```

The event history preserves every prior transition.

Each workflow event may record:

- Claim ID
- Previous status
- New status
- Processing step
- Event reason
- Retry attempt
- Timestamp

---

## Database Design

The project currently uses four core PostgreSQL tables.

### `claims`

Stores the current state and core information for each claim.

Important fields include:

- claim_id
- member_id
- provider_id
- diagnosis_code
- procedure_code
- service_date
- billed_amount
- allowed_amount
- submitted_date
- current_status
- created_at
- updated_at

---

### `claim_events`

Stores the workflow history for every claim.

Important fields include:

- event_id
- claim_id
- previous_status
- new_status
- processing_step
- event_reason
- retry_attempt
- created_at

This table provides the workflow audit trail.

---

### `retry_queue`

Stores temporary processing failures that may be attempted again.

Important fields include:

- retry_id
- claim_id
- failed_step
- retry_count
- max_retries
- next_retry_time
- retry_status
- last_error
- created_at
- updated_at

---

### `manual_review_queue`

Stores claims requiring human intervention.

Important fields include:

- review_id
- claim_id
- review_reason
- review_status
- reviewer_notes
- created_at
- resolved_at

---

## Current Architecture

```text
Synthetic Data Sources
        │
        ▼
    Claim Loader
        │
        ▼
   Workflow Engine
        │
        ├── Validation
        │
        ├── Eligibility
        │
        ├── Duplicate Check
        │
        ├── Pricing
        │       │
        │       └── Retry Queue
        │
        ├── Fraud / Rules Review
        │       │
        │       └── Manual Review Queue
        │
        ▼
     PostgreSQL
        │
        ├── claims
        ├── claim_events
        ├── retry_queue
        └── manual_review_queue
        │
        ▼
      Reports
```

The workflow-processing modules will be implemented incrementally during later project phases.

---

## Technology Stack

- Python
- PostgreSQL
- Psycopg
- python-dotenv
- Pytest
- CSV
- JSON
- Git
- GitHub

---

## Project Structure

```text
healthcare-claims-workflow/
│
├── data/
│   ├── claims.csv
│   ├── members.csv
│   ├── diagnosis_codes.csv
│   ├── pricing_rules.json
│   └── review_rules.json
│
├── database/
│   ├── schema.sql
│   └── seed_data.py
│
├── logs/
│   └── .gitkeep
│
├── reports/
│   ├── claim_summary.csv
│   ├── exception_report.json
│   └── workflow_summary.json
│
├── src/
│   ├── audit_logger.py
│   ├── claim_loader.py
│   ├── config.py
│   ├── database.py
│   ├── duplicate_checker.py
│   ├── eligibility.py
│   ├── fraud_review.py
│   ├── main.py
│   ├── pricing.py
│   ├── retry_manager.py
│   ├── state_manager.py
│   ├── validator.py
│   └── workflow_engine.py
│
├── tests/
│
├── .env
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt
```

---

## Synthetic Data Sources

The project uses five synthetic data sources.

### Claims

`data/claims.csv`

Contains incoming synthetic claims.

### Members

`data/members.csv`

Contains synthetic member and coverage information.

### Diagnosis Codes

`data/diagnosis_codes.csv`

Contains synthetic reference codes used for validation.

### Pricing Rules

`data/pricing_rules.json`

Contains simplified synthetic pricing rules.

### Review Rules

`data/review_rules.json`

Contains simplified synthetic rules used to determine when claims require additional review.

---

## Environment Setup

Create a Python virtual environment:

```bash
python3 -m venv .venv
```

Activate the environment:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Environment Variables

Create a local `.env` file based on `.env.example`.

Required variables:

```text
DB_HOST
DB_PORT
DB_NAME
DB_USER
DB_PASSWORD
```

The `.env` file contains local credentials and must never be committed to GitHub.

---

## PostgreSQL Database

The project uses a local PostgreSQL database named:

```text
claims_workflow
```

Create the schema with:

```bash
psql -U postgres -d claims_workflow -f database/schema.sql
```

The database currently contains four core tables:

```text
claims
claim_events
retry_queue
manual_review_queue
```

---

## Running the Application

From the project root:

```bash
python -m src.main
```

The current application verifies:

1. Synthetic project data can be loaded.
2. CSV files can be read.
3. JSON files can be read.
4. PostgreSQL can be reached successfully.

Claim-processing logic will be added incrementally.

---

## Testing

Automated tests will be added as workflow components are implemented.

Planned testing will cover:

- Validation
- Eligibility
- Duplicate detection
- Pricing
- Retry behavior
- Manual review routing
- Valid state transitions
- Invalid state transitions

---

## Operational Reports

Operational reporting will be implemented after the core workflow is complete.

Planned reports include:

- Claim summary
- Exception report
- Workflow summary

---

## Lessons Learned

### Day 1 — Project Setup

The project established a clean separation between:

- Local environment configuration
- Application source code
- Synthetic input data
- Database infrastructure

Environment variables are stored locally in `.env`, while `.env.example` documents the required configuration without exposing credentials.

The application also verified that all synthetic data sources could be read successfully before implementing business logic.

### Day 2 — Workflow Design

The workflow was designed before implementing claim-processing logic.

The most important architectural distinction is between:

```text
Current State
```

and:

```text
State History
```

The `claims` table stores where a claim is now.

The `claim_events` table stores how the claim reached that state.

Retry processing and manual review are modeled as separate operational queues rather than being hidden inside the primary claims table.

Valid state transitions are explicitly defined in Python so the application can eventually prevent claims from skipping required workflow stages.