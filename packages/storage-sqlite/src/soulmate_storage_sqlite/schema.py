"""SQLAlchemy schema owned by the SQLite adapter."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    text,
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
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    acquisition_method: Mapped[str] = mapped_column(String, nullable=False)
    consent_mode: Mapped[str] = mapped_column(String, nullable=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_classes_json: Mapped[str] = mapped_column(Text, nullable=False)
    author_scope: Mapped[str] = mapped_column(String, nullable=False)
    raw_retention_policy: Mapped[str] = mapped_column(String, nullable=False)
    adapter_version: Mapped[str | None] = mapped_column(String, nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String, nullable=True)
    policy_profile_version: Mapped[str] = mapped_column(String, nullable=False)
    service_identity_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Migration 0012 adds the provenance columns in place. SQLite cannot add a
    # table check to an existing table without rebuilding it, and rebuilding a
    # foreign-key target risks cascading deletes, so the domain records in
    # soulmate_core.domain.provenance enforce this vocabulary instead.
    __table_args__ = (Index("ix_sources_profile_created", "profile_id", "created_at", "id"),)


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
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    external_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_type: Mapped[str] = mapped_column(String, nullable=False)
    evidence_eligibility: Mapped[str] = mapped_column(String, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # SQLite cannot add a foreign key to an existing table, so migration 0012 adds
    # these references as plain columns. The Decision I/O repository resolves and
    # removes them explicitly instead.
    causation_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    content_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_raw_events_profile_created", "profile_id", "created_at"),
        Index("ix_raw_events_source", "source_id"),
        Index("ix_raw_events_correlation", "profile_id", "correlation_id"),
        Index(
            "uq_raw_events_source_external",
            "source_id",
            "external_event_id",
            unique=True,
            sqlite_where=text("external_event_id IS NOT NULL"),
        ),
    )


class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_conversations_profile_updated", "profile_id", "updated_at"),
        Index("ix_conversations_source", "source_id"),
    )


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
    origin: Mapped[str] = mapped_column(String, nullable=False)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    # Added to an existing table by migration 0012; see RawEventRow above.
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    external_decision_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('open', 'resolved')", name="ck_decision_events_status"),
        Index("ix_decision_events_profile_created", "profile_id", "created_at", "id"),
        Index("ix_decision_events_source", "source_id"),
        Index(
            "uq_decision_events_source_external",
            "source_id",
            "external_decision_id",
            unique=True,
            sqlite_where=text("external_decision_id IS NOT NULL"),
        ),
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
    external_option_id: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index(
            "uq_decision_options_external",
            "decision_id",
            "external_option_id",
            unique=True,
            sqlite_where=text("external_option_id IS NOT NULL"),
        ),
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
    attribution: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("satisfaction >= 0 AND satisfaction <= 1", name="ck_outcomes_satisfaction"),
        Index("ix_decision_outcomes_profile_created", "profile_id", "created_at", "id"),
    )


class ResolutionObservationRow(Base):
    __tablename__ = "resolution_observations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    source_event_id: Mapped[str] = mapped_column(
        ForeignKey("raw_events.id", ondelete="CASCADE"), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    disposition: Mapped[str] = mapped_column(String, nullable=False)
    decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("decision_events.id", ondelete="CASCADE"), nullable=True
    )
    external_decision_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chosen_option_id: Mapped[str | None] = mapped_column(
        ForeignKey("decision_options.id", ondelete="CASCADE"), nullable=True
    )
    external_option_id: Mapped[str | None] = mapped_column(String, nullable=True)
    correlation_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('unmatched', 'pending', 'confirmed', 'rejected')",
            name="ck_resolution_observations_status",
        ),
        CheckConstraint(
            "actor_type IN ('owner', 'agent', 'assistant', 'system', 'third_party', 'unknown')",
            name="ck_resolution_observations_actor_type",
        ),
        CheckConstraint(
            "disposition IN ('accepted', 'modified', 'replaced', 'reverted', 'unknown')",
            name="ck_resolution_observations_disposition",
        ),
        CheckConstraint(
            "decision_id IS NOT NULL OR external_decision_id IS NOT NULL",
            name="ck_resolution_observations_decision_reference",
        ),
        CheckConstraint(
            "(status = 'confirmed') = (confirmed_at IS NOT NULL)",
            name="ck_resolution_observations_confirmation",
        ),
        Index(
            "ix_resolution_observations_profile_status", "profile_id", "status", "created_at", "id"
        ),
        Index("ix_resolution_observations_decision", "decision_id"),
        Index("ix_resolution_observations_source", "source_id"),
        Index("ix_resolution_observations_external", "profile_id", "external_decision_id"),
    )


class OutcomeObservationRow(Base):
    __tablename__ = "outcome_observations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    source_event_id: Mapped[str] = mapped_column(
        ForeignKey("raw_events.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    actor_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("decision_events.id", ondelete="CASCADE"), nullable=True
    )
    external_decision_id: Mapped[str | None] = mapped_column(String, nullable=True)
    technical_status: Mapped[str | None] = mapped_column(String, nullable=True)
    disposition: Mapped[str | None] = mapped_column(String, nullable=True)
    satisfaction: Mapped[float | None] = mapped_column(Float, nullable=True)
    regret: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('technical', 'user_behavior', 'owner_reported')",
            name="ck_outcome_observations_kind",
        ),
        CheckConstraint(
            "status IN ('unmatched', 'pending', 'confirmed', 'rejected')",
            name="ck_outcome_observations_status",
        ),
        CheckConstraint(
            "actor_type IN ('owner', 'agent', 'assistant', 'system', 'third_party', 'unknown')",
            name="ck_outcome_observations_actor_type",
        ),
        CheckConstraint(
            "(kind = 'technical') = (technical_status IS NOT NULL)",
            name="ck_outcome_observations_technical_status",
        ),
        CheckConstraint(
            "(kind = 'user_behavior') = (disposition IS NOT NULL)",
            name="ck_outcome_observations_disposition",
        ),
        CheckConstraint(
            "kind = 'owner_reported' OR (satisfaction IS NULL AND regret IS NULL)",
            name="ck_outcome_observations_wellbeing_scope",
        ),
        CheckConstraint(
            "kind <> 'owner_reported' OR (satisfaction IS NOT NULL AND regret IS NOT NULL)",
            name="ck_outcome_observations_wellbeing_complete",
        ),
        CheckConstraint(
            "satisfaction IS NULL OR (satisfaction >= 0 AND satisfaction <= 1)",
            name="ck_outcome_observations_satisfaction",
        ),
        CheckConstraint(
            "decision_id IS NOT NULL OR external_decision_id IS NOT NULL",
            name="ck_outcome_observations_decision_reference",
        ),
        CheckConstraint(
            "(status = 'confirmed') = (confirmed_at IS NOT NULL)",
            name="ck_outcome_observations_confirmation",
        ),
        Index("ix_outcome_observations_profile_status", "profile_id", "status", "created_at", "id"),
        Index("ix_outcome_observations_decision", "decision_id"),
        Index("ix_outcome_observations_source", "source_id"),
        Index("ix_outcome_observations_external", "profile_id", "external_decision_id"),
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


_TARGET_TYPES = "target_type IN ('fact', 'preference', 'goal', 'constraint')"


class TargetKeyAliasRow(Base):
    __tablename__ = "target_key_aliases"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    target_type: Mapped[str] = mapped_column(String, primary_key=True)
    alias_key: Mapped[str] = mapped_column(String, primary_key=True)
    canonical_key: Mapped[str] = mapped_column(String, nullable=False)
    polarity: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False)
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(_TARGET_TYPES, name="ck_target_key_aliases_target_type"),
        CheckConstraint("polarity IN (1, -1)", name="ck_target_key_aliases_polarity"),
        CheckConstraint(
            "polarity = 1 OR target_type = 'preference'",
            name="ck_target_key_aliases_inversion",
        ),
        CheckConstraint(
            "method IN ('normalized', 'semantic', 'owner')",
            name="ck_target_key_aliases_method",
        ),
        CheckConstraint(
            "status IN ('active', 'suggested', 'rejected')",
            name="ck_target_key_aliases_status",
        ),
        CheckConstraint(
            "similarity IS NULL OR (similarity >= 0 AND similarity <= 1)",
            name="ck_target_key_aliases_similarity",
        ),
        CheckConstraint("alias_key <> canonical_key", name="ck_target_key_aliases_distinct"),
        Index("ix_target_key_aliases_canonical", "profile_id", "target_type", "canonical_key"),
        Index("ix_target_key_aliases_status", "profile_id", "status"),
    )


class TargetKeyCatalogRow(Base):
    """Owner-language label per key; owner-edited labels cannot be derived again."""

    __tablename__ = "target_key_catalog"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    target_type: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases_json: Mapped[str] = mapped_column(Text, nullable=False)
    label_source: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(_TARGET_TYPES, name="ck_target_key_catalog_target_type"),
        CheckConstraint(
            "label_source IN ('extracted', 'owner')",
            name="ck_target_key_catalog_label_source",
        ),
    )


class TargetKeyEmbeddingRow(Base):
    """Derived, rebuildable key vector; excluded from portable exports."""

    __tablename__ = "target_key_embeddings"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    target_type: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    model_id: Mapped[str] = mapped_column(String, primary_key=True)
    text_hash: Mapped[str] = mapped_column(String, nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(_TARGET_TYPES, name="ck_target_key_embeddings_target_type"),
        CheckConstraint("dim > 0", name="ck_target_key_embeddings_dim"),
    )


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


class ServiceIdentityRow(Base):
    __tablename__ = "service_identities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_service_identities_profile_created", "profile_id", "created_at", "id"),
    )


class ServiceIdentityScopeRow(Base):
    __tablename__ = "service_identity_scopes"

    service_identity_id: Mapped[str] = mapped_column(
        ForeignKey("service_identities.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String, primary_key=True)


class ApiCredentialRow(Base):
    __tablename__ = "api_credentials"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    service_identity_id: Mapped[str] = mapped_column(
        ForeignKey("service_identities.id", ondelete="CASCADE"), nullable=False
    )
    secret_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_api_credentials_identity_created",
            "service_identity_id",
            "created_at",
            "id",
        ),
    )


class DelegationPolicyRow(Base):
    __tablename__ = "delegation_policies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    service_identity_id: Mapped[str] = mapped_column(
        ForeignKey("service_identities.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    impact: Mapped[str] = mapped_column(String, nullable=False)
    minimum_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    allow_automatic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "impact IN ('low', 'medium', 'high', 'safety_critical')",
            name="ck_delegation_policies_impact",
        ),
        CheckConstraint(
            "minimum_confidence >= 0 AND minimum_confidence <= 1",
            name="ck_delegation_policies_confidence",
        ),
        Index(
            "ux_delegation_policies_identity_action",
            "service_identity_id",
            "action_type",
            unique=True,
        ),
        Index("ix_delegation_policies_profile", "profile_id", "created_at", "id"),
    )


class DelegationRequestRow(Base):
    __tablename__ = "delegation_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    service_identity_id: Mapped[str] = mapped_column(
        ForeignKey("service_identities.id", ondelete="CASCADE"), nullable=False
    )
    policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("delegation_policies.id", ondelete="SET NULL"), nullable=True
    )
    decision_id: Mapped[str] = mapped_column(String, nullable=False)
    prediction_id: Mapped[str] = mapped_column(String, nullable=False)
    external_request_id: Mapped[str] = mapped_column(String, nullable=False)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    action_label: Mapped[str] = mapped_column(Text, nullable=False)
    impact: Mapped[str] = mapped_column(String, nullable=False)
    predicted_option_id: Mapped[str] = mapped_column(String, nullable=False)
    prediction_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    reason_code: Mapped[str] = mapped_column(String, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "impact IN ('low', 'medium', 'high', 'safety_critical')",
            name="ck_delegation_requests_impact",
        ),
        CheckConstraint(
            "prediction_confidence >= 0 AND prediction_confidence <= 1",
            name="ck_delegation_requests_confidence",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'completed', 'expired')",
            name="ck_delegation_requests_status",
        ),
        Index(
            "ux_delegation_requests_identity_external",
            "service_identity_id",
            "external_request_id",
            unique=True,
        ),
        Index("ix_delegation_requests_profile_status", "profile_id", "status", "requested_at"),
    )


class ConnectorRegistrationRow(Base):
    __tablename__ = "connector_registrations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    connector_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    granted_permissions_json: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_json: Mapped[str] = mapped_column(Text, nullable=False)
    cursor_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sync_status: Mapped[str] = mapped_column(String, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "sync_status IN ('never', 'running', 'succeeded', 'failed')",
            name="ck_connector_registrations_sync_status",
        ),
        Index(
            "ux_connector_registrations_profile_connector",
            "profile_id",
            "connector_id",
            unique=True,
        ),
    )


class ConnectorItemRow(Base):
    __tablename__ = "connector_items"

    registration_id: Mapped[str] = mapped_column(
        ForeignKey("connector_registrations.id", ondelete="CASCADE"), primary_key=True
    )
    external_id: Mapped[str] = mapped_column(String, primary_key=True)
    raw_event_id: Mapped[str] = mapped_column(
        ForeignKey("raw_events.id", ondelete="CASCADE"), nullable=False, unique=True
    )
