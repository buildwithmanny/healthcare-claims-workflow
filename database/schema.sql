-- Healthcare Claims Workflow
-- PostgreSQL Schema
--
-- This schema stores:
-- 1. The current state of each claim.
-- 2. The complete workflow history for each claim.
-- 3. Claims waiting for retry processing.
-- 4. Claims requiring manual review.
--
-- The claims table represents current state.
-- The claim_events table represents historical state changes.


-- ============================================================
-- CLAIMS
-- ============================================================

CREATE TABLE IF NOT EXISTS claims (
    claim_id VARCHAR(50) PRIMARY KEY,

    member_id VARCHAR(50),
    provider_id VARCHAR(50),

    diagnosis_code VARCHAR(50),
    procedure_code VARCHAR(50),

    service_date DATE,

    billed_amount NUMERIC(12, 2),
    allowed_amount NUMERIC(12, 2),

    submitted_date DATE,

    current_status VARCHAR(50)
        NOT NULL
        DEFAULT 'RECEIVED',

    created_at TIMESTAMPTZ
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT claims_billed_amount_nonnegative
        CHECK (
            billed_amount IS NULL
            OR billed_amount >= 0
        ),

    CONSTRAINT claims_allowed_amount_nonnegative
        CHECK (
            allowed_amount IS NULL
            OR allowed_amount >= 0
        ),

    CONSTRAINT claims_valid_status
        CHECK (
            current_status IN (
                'RECEIVED',
                'VALIDATING',
                'VALIDATION_FAILED',
                'ELIGIBILITY_CHECK',
                'INELIGIBLE',
                'DUPLICATE_CHECK',
                'DUPLICATE',
                'PRICING',
                'PRICING_RETRY',
                'FRAUD_REVIEW',
                'MANUAL_REVIEW',
                'APPROVED',
                'DENIED',
                'FAILED'
            )
        )
);


-- ============================================================
-- CLAIM EVENTS
-- ============================================================

CREATE TABLE IF NOT EXISTS claim_events (
    event_id BIGSERIAL PRIMARY KEY,

    claim_id VARCHAR(50)
        NOT NULL,

    previous_status VARCHAR(50),

    new_status VARCHAR(50)
        NOT NULL,

    processing_step VARCHAR(100)
        NOT NULL,

    event_reason TEXT,

    retry_attempt INTEGER,

    created_at TIMESTAMPTZ
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT claim_events_claim_fk
        FOREIGN KEY (claim_id)
        REFERENCES claims(claim_id)
        ON DELETE CASCADE,

    CONSTRAINT claim_events_retry_nonnegative
        CHECK (
            retry_attempt IS NULL
            OR retry_attempt >= 0
        )
);


-- Add or refresh Day 8 audit-history constraints.
--
-- These statements also update databases created during earlier
-- project days when claim_events already existed.

ALTER TABLE claim_events
    DROP CONSTRAINT IF EXISTS
        claim_events_previous_status_valid;


ALTER TABLE claim_events
    ADD CONSTRAINT claim_events_previous_status_valid
    CHECK (
        previous_status IS NULL
        OR previous_status IN (
            'RECEIVED',
            'VALIDATING',
            'VALIDATION_FAILED',
            'ELIGIBILITY_CHECK',
            'INELIGIBLE',
            'DUPLICATE_CHECK',
            'DUPLICATE',
            'PRICING',
            'PRICING_RETRY',
            'FRAUD_REVIEW',
            'MANUAL_REVIEW',
            'APPROVED',
            'DENIED',
            'FAILED'
        )
    );


ALTER TABLE claim_events
    DROP CONSTRAINT IF EXISTS
        claim_events_new_status_valid;


ALTER TABLE claim_events
    ADD CONSTRAINT claim_events_new_status_valid
    CHECK (
        new_status IN (
            'RECEIVED',
            'VALIDATING',
            'VALIDATION_FAILED',
            'ELIGIBILITY_CHECK',
            'INELIGIBLE',
            'DUPLICATE_CHECK',
            'DUPLICATE',
            'PRICING',
            'PRICING_RETRY',
            'FRAUD_REVIEW',
            'MANUAL_REVIEW',
            'APPROVED',
            'DENIED',
            'FAILED'
        )
    );


ALTER TABLE claim_events
    DROP CONSTRAINT IF EXISTS
        claim_events_status_changed;


ALTER TABLE claim_events
    ADD CONSTRAINT claim_events_status_changed
    CHECK (
        previous_status IS NULL
        OR previous_status <> new_status
    );


ALTER TABLE claim_events
    DROP CONSTRAINT IF EXISTS
        claim_events_intake_shape_valid;


ALTER TABLE claim_events
    ADD CONSTRAINT claim_events_intake_shape_valid
    CHECK (
        (
            previous_status IS NULL
            AND new_status = 'RECEIVED'
        )
        OR
        (
            previous_status IS NOT NULL
            AND new_status <> 'RECEIVED'
        )
    );


ALTER TABLE claim_events
    DROP CONSTRAINT IF EXISTS
        claim_events_processing_step_not_blank;


ALTER TABLE claim_events
    ADD CONSTRAINT claim_events_processing_step_not_blank
    CHECK (
        BTRIM(processing_step) <> ''
    );


-- ============================================================
-- RETRY QUEUE
-- ============================================================

CREATE TABLE IF NOT EXISTS retry_queue (
    retry_id BIGSERIAL PRIMARY KEY,

    claim_id VARCHAR(50)
        NOT NULL,

    failed_step VARCHAR(100)
        NOT NULL,

    retry_count INTEGER
        NOT NULL
        DEFAULT 0,

    max_retries INTEGER
        NOT NULL
        DEFAULT 3,

    next_retry_time TIMESTAMPTZ,

    retry_status VARCHAR(50)
        NOT NULL
        DEFAULT 'PENDING',

    last_error TEXT,

    created_at TIMESTAMPTZ
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT retry_queue_claim_fk
        FOREIGN KEY (claim_id)
        REFERENCES claims(claim_id)
        ON DELETE CASCADE,

    CONSTRAINT retry_count_nonnegative
        CHECK (
            retry_count >= 0
        ),

    CONSTRAINT max_retries_positive
        CHECK (
            max_retries > 0
        ),

    CONSTRAINT retry_count_within_limit
        CHECK (
            retry_count <= max_retries
        ),

    CONSTRAINT retry_queue_valid_status
        CHECK (
            retry_status IN (
                'PENDING',
                'PROCESSING',
                'SUCCEEDED',
                'EXHAUSTED',
                'CANCELLED'
            )
        )
);


-- ============================================================
-- MANUAL REVIEW QUEUE
-- ============================================================

CREATE TABLE IF NOT EXISTS manual_review_queue (
    review_id BIGSERIAL PRIMARY KEY,

    claim_id VARCHAR(50)
        NOT NULL,

    review_reason TEXT
        NOT NULL,

    review_status VARCHAR(50)
        NOT NULL
        DEFAULT 'PENDING',

    reviewer_notes TEXT,

    created_at TIMESTAMPTZ
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    resolved_at TIMESTAMPTZ,

    CONSTRAINT manual_review_claim_fk
        FOREIGN KEY (claim_id)
        REFERENCES claims(claim_id)
        ON DELETE CASCADE,

    CONSTRAINT manual_review_valid_status
        CHECK (
            review_status IN (
                'PENDING',
                'IN_REVIEW',
                'APPROVED',
                'DENIED',
                'RESOLVED'
            )
        )
);


-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_claims_member_id
    ON claims(member_id);


CREATE INDEX IF NOT EXISTS idx_claims_current_status
    ON claims(current_status);


CREATE INDEX IF NOT EXISTS idx_claims_service_date
    ON claims(service_date);


CREATE INDEX IF NOT EXISTS idx_claim_events_claim_id
    ON claim_events(claim_id);


CREATE INDEX IF NOT EXISTS idx_claim_events_created_at
    ON claim_events(created_at);


CREATE INDEX IF NOT EXISTS idx_claim_events_claim_history
    ON claim_events(
        claim_id,
        created_at,
        event_id
    );


CREATE INDEX IF NOT EXISTS idx_retry_queue_claim_id
    ON retry_queue(claim_id);


CREATE INDEX IF NOT EXISTS idx_retry_queue_status
    ON retry_queue(retry_status);


CREATE INDEX IF NOT EXISTS idx_retry_queue_next_retry_time
    ON retry_queue(next_retry_time);


CREATE INDEX IF NOT EXISTS idx_manual_review_claim_id
    ON manual_review_queue(claim_id);


CREATE INDEX IF NOT EXISTS idx_manual_review_status
    ON manual_review_queue(review_status);


-- ============================================================
-- CLAIM JOURNEY VIEW
-- ============================================================

CREATE OR REPLACE VIEW claim_journey AS
SELECT
    c.claim_id,
    c.current_status,
    c.updated_at AS claim_updated_at,

    e.event_id,
    e.previous_status,
    e.new_status,
    e.processing_step,
    e.event_reason,
    e.retry_attempt,
    e.created_at AS event_created_at

FROM claims AS c

INNER JOIN claim_events AS e
    ON e.claim_id = c.claim_id;