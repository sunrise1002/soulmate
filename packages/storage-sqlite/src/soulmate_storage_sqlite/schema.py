"""SQLAlchemy schema owned by the SQLite adapter."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProfileRow(Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceRow(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RawEventRow(Base):
    __tablename__ = "raw_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sensitivity: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("ix_raw_events_profile_created", "profile_id", "created_at"),
        Index("ix_raw_events_source", "source_id"),
    )


class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_conversations_profile_updated", "profile_id", "updated_at"),)


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provider_model: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at", "id"),
    )


class DecisionEventRow(Base):
    __tablename__ = "decision_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('open', 'resolved')", name="ck_decision_events_status"),
        Index("ix_decision_events_profile_created", "profile_id", "created_at", "id"),
    )


class DecisionOptionRow(Base):
    __tablename__ = "decision_options"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        ForeignKey("decision_events.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    features_json: Mapped[str] = mapped_column(Text, nullable=False)
    feature_confidence: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "feature_confidence >= 0 AND feature_confidence <= 1",
            name="ck_decision_options_feature_confidence",
        ),
        Index("ix_decision_options_decision", "decision_id", "id"),
    )


class DecisionPredictionRow(Base):
    __tablename__ = "decision_predictions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        ForeignKey("decision_events.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[str] = mapped_column(String, nullable=False)
    ranking_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    important_factors_json: Mapped[str] = mapped_column(Text, nullable=False)
    uncertain_factors_json: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    similar_decision_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    model_snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_predictions_confidence"),
        ForeignKeyConstraint(
            ["profile_id", "model_snapshot_version"],
            ["user_model_snapshots.profile_id", "user_model_snapshots.version"],
            ondelete="RESTRICT",
        ),
        Index("ix_decision_predictions_decision_created", "decision_id", "created_at", "id"),
    )


class DecisionResolutionRow(Base):
    __tablename__ = "decision_resolutions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        ForeignKey("decision_events.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    chosen_option_id: Mapped[str] = mapped_column(
        ForeignKey("decision_options.id", ondelete="RESTRICT"), nullable=False
    )
    source_event_id: Mapped[str] = mapped_column(
        ForeignKey("raw_events.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_decision_resolutions_choice", "chosen_option_id"),)


class DecisionOutcomeRow(Base):
    __tablename__ = "decision_outcomes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        ForeignKey("decision_events.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    satisfaction: Mapped[float] = mapped_column(Float, nullable=False)
    regret: Mapped[bool] = mapped_column(nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_event_id: Mapped[str] = mapped_column(
        ForeignKey("raw_events.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("satisfaction >= 0 AND satisfaction <= 1", name="ck_outcomes_satisfaction"),
        Index("ix_decision_outcomes_profile_created", "profile_id", "created_at", "id"),
    )


class DecisionAdviceRow(Base):
    __tablename__ = "decision_advice"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        ForeignKey("decision_events.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[str] = mapped_column(String, nullable=False)
    behavioral_prediction_id: Mapped[str] = mapped_column(
        ForeignKey("decision_predictions.id", ondelete="CASCADE"), nullable=False
    )
    ranking_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rationale_json: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_outcome_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    model_snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_advice_confidence"),
        ForeignKeyConstraint(
            ["profile_id", "model_snapshot_version"],
            ["user_model_snapshots.profile_id", "user_model_snapshots.version"],
            ondelete="RESTRICT",
        ),
        Index("ix_decision_advice_decision_created", "decision_id", "created_at", "id"),
    )


class ActiveQuestionRow(Base):
    __tablename__ = "active_questions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(String, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    preference_keys_json: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    option_a_label: Mapped[str] = mapped_column(Text, nullable=False)
    option_a_features_json: Mapped[str] = mapped_column(Text, nullable=False)
    option_b_label: Mapped[str] = mapped_column(Text, nullable=False)
    option_b_features_json: Mapped[str] = mapped_column(Text, nullable=False)
    information_gain_score: Mapped[float] = mapped_column(Float, nullable=False)
    model_snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "information_gain_score >= 0 AND information_gain_score <= 1",
            name="ck_active_questions_information_gain",
        ),
        CheckConstraint("status IN ('pending', 'answered')", name="ck_active_questions_status"),
        ForeignKeyConstraint(
            ["profile_id", "model_snapshot_version"],
            ["user_model_snapshots.profile_id", "user_model_snapshots.version"],
            ondelete="RESTRICT",
        ),
        Index("ix_active_questions_profile_status", "profile_id", "status", "created_at"),
    )


class QuestionAnswerRow(Base):
    __tablename__ = "question_answers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    question_id: Mapped[str] = mapped_column(
        ForeignKey("active_questions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    choice: Mapped[str] = mapped_column(String, nullable=False)
    source_event_id: Mapped[str] = mapped_column(
        ForeignKey("raw_events.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (CheckConstraint("choice IN ('a', 'b')", name="ck_question_answers_choice"),)


class EvidenceRow(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String, nullable=False)
    target_key: Mapped[str] = mapped_column(String, nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    strength: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_event_id: Mapped[str] = mapped_column(
        ForeignKey("raw_events.id", ondelete="CASCADE"), nullable=False
    )
    extractor_version: Mapped[str] = mapped_column(String, nullable=False)
    extractor_model: Mapped[str | None] = mapped_column(String, nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "target_type IN ('fact', 'preference', 'goal', 'constraint')",
            name="ck_evidence_target_type",
        ),
        CheckConstraint("strength >= 0 AND strength <= 1", name="ck_evidence_strength_range"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_evidence_confidence_range"),
        Index("ix_evidence_profile_target", "profile_id", "target_key"),
        Index("ix_evidence_source_event", "source_event_id"),
        Index("ix_evidence_source_message", "source_message_id"),
    )


class EvidenceRevisionRow(Base):
    __tablename__ = "evidence_revisions"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class PreferenceRow(Base):
    __tablename__ = "preferences"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String, primary_key=True)
    context_key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_preferences_profile_key", "profile_id", "key"),)


class FactRow(Base):
    __tablename__ = "facts"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String, primary_key=True)
    context_key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_version: Mapped[int] = mapped_column(Integer, nullable=False)


class GoalRow(Base):
    __tablename__ = "goals"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String, primary_key=True)
    context_key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_version: Mapped[int] = mapped_column(Integer, nullable=False)


class ConstraintRow(Base):
    __tablename__ = "constraints"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String, primary_key=True)
    context_key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_version: Mapped[int] = mapped_column(Integer, nullable=False)


class UserModelSnapshotRow(Base):
    __tablename__ = "user_model_snapshots"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    evidence_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    model_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_user_model_snapshots_profile_version", "profile_id", "version"),)


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    actor_type: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_audit_events_created", "created_at"),)


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_jobs_attempts_nonnegative"),
        CheckConstraint("max_attempts > 0", name="ck_jobs_max_attempts_positive"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_jobs_status",
        ),
        Index("ix_jobs_claim", "status", "available_at", "locked_at"),
    )


class SystemMetadataRow(Base):
    __tablename__ = "system_metadata"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PairingTokenRow(Base):
    __tablename__ = "pairing_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Provenance only: the token is claimed before the device row exists, so this
    # column intentionally carries no foreign key.
    device_id: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (Index("ix_pairing_tokens_expires", "expires_at"),)


class PairedDeviceRow(Base):
    __tablename__ = "paired_devices"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    credential_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_paired_devices_profile_created", "profile_id", "created_at", "id"),)
