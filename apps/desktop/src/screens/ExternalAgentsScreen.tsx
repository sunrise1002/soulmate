import {
  Bot,
  Check,
  KeyRound,
  RefreshCw,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { SyntheticEvent } from "react";

import { DecisionIoObservationsPanel } from "../components/DecisionIoObservationsPanel.tsx";
import { DecisionIoSourcesPanel } from "../components/DecisionIoSourcesPanel.tsx";
import { EmptyState } from "../components/EmptyState.tsx";
import { apiRequest } from "../runtime.ts";
import type {
  ApiCredential,
  AuditEvent,
  DecisionImpact,
  DelegationPolicy,
  DelegationRequest,
  IssuedCredential,
  IssuedServiceIdentity,
  ServiceIdentity,
} from "../types.ts";
import { formatDate } from "../utils.ts";

const scopeLabels: Record<string, string> = {
  "agent:delegate": "Request delegated actions",
  "decision:predict": "Predict and rank decisions",
  "decision:record": "Record decisions",
  "decision:resolution:record": "Report decision choices",
  "interaction:record": "Report activity",
  "model:summary:read": "Read model summary",
  "outcome:observe": "Report technical and behavioral outcomes",
  "outcome:record": "Report satisfaction for your confirmation",
  "preference:summary:read": "Read preference summary",
};

const defaultScopes = ["decision:predict", "preference:summary:read"];

export function ExternalAgentsScreen() {
  const [identities, setIdentities] = useState<ServiceIdentity[]>([]);
  const [scopes, setScopes] = useState<string[]>([]);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [policies, setPolicies] = useState<DelegationPolicy[]>([]);
  const [delegations, setDelegations] = useState<DelegationRequest[]>([]);
  const [name, setName] = useState("");
  const [selectedScopes, setSelectedScopes] = useState(defaultScopes);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [policyIdentity, setPolicyIdentity] = useState("");
  const [actionType, setActionType] = useState("");
  const [impact, setImpact] = useState<DecisionImpact>("low");
  const [minimumConfidence, setMinimumConfidence] = useState(0.9);
  const [allowAutomatic, setAllowAutomatic] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourcesRevision, setSourcesRevision] = useState(0);

  const load = useCallback(async () => {
    try {
      const [
        availableScopes,
        currentIdentities,
        events,
        currentPolicies,
        currentDelegations,
      ] = await Promise.all([
        apiRequest<string[]>("GET", "/v1/service-identities/scopes"),
        apiRequest<ServiceIdentity[]>("GET", "/v1/service-identities"),
        apiRequest<AuditEvent[]>("GET", "/v1/audit/events"),
        apiRequest<DelegationPolicy[]>("GET", "/v1/delegation-policies"),
        apiRequest<DelegationRequest[]>("GET", "/v1/delegation-requests"),
      ]);
      setScopes(availableScopes);
      setIdentities(currentIdentities);
      setAudit(events);
      setPolicies(currentPolicies);
      setDelegations(currentDelegations);
      setPolicyIdentity((current) => {
        if (currentIdentities.some((item) => item.id === current))
          return current;
        return (
          currentIdentities.find(
            (item) => item.active && item.scopes.includes("agent:delegate"),
          )?.id ?? ""
        );
      });
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "External agent permissions are unavailable.",
      );
    }
  }, []);

  useEffect(() => void load(), [load]);

  function toggleSelected(scope: string) {
    setSelectedScopes((current) =>
      current.includes(scope)
        ? current.filter((item) => item !== scope)
        : [...current, scope],
    );
  }

  async function create(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !name.trim() || selectedScopes.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const issued = await apiRequest<IssuedServiceIdentity>(
        "POST",
        "/v1/service-identities",
        { name, scopes: selectedScopes },
      );
      setRevealedKey(issued.api_key);
      setName("");
      setSelectedScopes(defaultScopes);
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The external identity could not be created.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function updateScopes(identity: ServiceIdentity, scope: string) {
    const next = identity.scopes.includes(scope)
      ? identity.scopes.filter((item) => item !== scope)
      : [...identity.scopes, scope];
    if (next.length === 0 || busy) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest<ServiceIdentity>(
        "POST",
        `/v1/service-identities/${encodeURIComponent(identity.id)}/scopes`,
        { scopes: next },
      );
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Permissions could not be updated.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function issueKey(identityId: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const issued = await apiRequest<IssuedCredential>(
        "POST",
        `/v1/service-identities/${encodeURIComponent(identityId)}/credentials`,
      );
      setRevealedKey(issued.api_key);
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "A new key could not be created.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function revokeKey(identityId: string, credential: ApiCredential) {
    if (busy) return;
    setBusy(true);
    try {
      await apiRequest<ApiCredential>(
        "DELETE",
        `/v1/service-identities/${encodeURIComponent(identityId)}/credentials/${encodeURIComponent(credential.id)}`,
      );
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The key could not be revoked.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function revokeIdentity(identityId: string) {
    if (busy) return;
    setBusy(true);
    try {
      await apiRequest<ServiceIdentity>(
        "DELETE",
        `/v1/service-identities/${encodeURIComponent(identityId)}`,
      );
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The identity could not be revoked.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function savePolicy(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !policyIdentity || !actionType.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest<DelegationPolicy>("POST", "/v1/delegation-policies", {
        service_identity_id: policyIdentity,
        action_type: actionType,
        impact,
        minimum_confidence: minimumConfidence,
        allow_automatic: allowAutomatic,
      });
      setActionType("");
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The delegation policy could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function removePolicy(policyId: string) {
    if (busy) return;
    setBusy(true);
    try {
      await apiRequest<null>(
        "DELETE",
        `/v1/delegation-policies/${encodeURIComponent(policyId)}`,
      );
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The delegation policy could not be removed.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function reviewDelegation(requestId: string, approved: boolean) {
    if (busy) return;
    setBusy(true);
    try {
      await apiRequest<DelegationRequest>(
        "POST",
        `/v1/delegation-requests/${encodeURIComponent(requestId)}/${approved ? "approve" : "reject"}`,
      );
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The delegation request could not be reviewed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="screen agents-screen">
      <header className="screen-header">
        <div>
          <p className="eyebrow">Local intelligence boundary</p>
          <h1>External Agents</h1>
          <p>
            Give each application its own revocable key and only the permissions
            it needs. Raw memories and evidence are never included in these
            scopes.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={busy}
          type="button"
          onClick={() => void load()}
        >
          <RefreshCw size={15} /> Refresh
        </button>
      </header>

      {error ? <div className="inline-error">{error}</div> : null}
      {revealedKey ? (
        <div className="card api-key-reveal">
          <ShieldCheck size={18} />
          <div>
            <strong>Copy this API key now</strong>
            <p>It is shown once. Soulmate stores only its secure hash.</p>
            <code>{revealedKey}</code>
          </div>
          <button
            className="text-button"
            type="button"
            onClick={() => setRevealedKey(null)}
          >
            Hide
          </button>
        </div>
      ) : null}

      <form
        className="card agent-create"
        onSubmit={(event) => void create(event)}
      >
        <div>
          <p className="section-label">New connection</p>
          <h2>Create a service identity</h2>
        </div>
        <label>
          <span>Application name</span>
          <input
            maxLength={200}
            placeholder="OpenClaw"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <div className="scope-grid">
          {scopes.map((scope) => (
            <label className="scope-choice" key={scope}>
              <input
                checked={selectedScopes.includes(scope)}
                type="checkbox"
                onChange={() => toggleSelected(scope)}
              />
              <span>{scopeLabels[scope] ?? scope}</span>
            </label>
          ))}
        </div>
        <button
          className="primary-button"
          disabled={busy || selectedScopes.length === 0}
          type="submit"
        >
          <KeyRound size={15} /> Create identity and key
        </button>
      </form>

      {identities.length ? (
        <div className="agent-list">
          {identities.map((identity) => (
            <article className="card agent-card" key={identity.id}>
              <div className="card-heading">
                <div>
                  <p className="section-label">
                    {identity.active ? "Active" : "Revoked"}
                  </p>
                  <h2>{identity.name}</h2>
                  <p className="muted">
                    Created {formatDate(identity.created_at)}
                  </p>
                </div>
                {identity.active ? (
                  <button
                    className="icon-button danger"
                    aria-label={`Revoke ${identity.name}`}
                    disabled={busy}
                    type="button"
                    onClick={() => void revokeIdentity(identity.id)}
                  >
                    <Trash2 size={15} />
                  </button>
                ) : null}
              </div>
              <div className="scope-grid compact">
                {scopes.map((scope) => (
                  <label className="scope-choice" key={scope}>
                    <input
                      checked={identity.scopes.includes(scope)}
                      disabled={busy || !identity.active}
                      type="checkbox"
                      onChange={() => void updateScopes(identity, scope)}
                    />
                    <span>{scopeLabels[scope] ?? scope}</span>
                  </label>
                ))}
              </div>
              <div className="credential-list">
                {identity.credentials.map((credential) => (
                  <div key={credential.id}>
                    <span>
                      {credential.id.slice(0, 22)} ·{" "}
                      {credential.active ? "active" : "revoked"}
                    </span>
                    {credential.active && identity.active ? (
                      <button
                        className="text-button"
                        disabled={busy}
                        type="button"
                        onClick={() => void revokeKey(identity.id, credential)}
                      >
                        Revoke key
                      </button>
                    ) : null}
                  </div>
                ))}
              </div>
              {identity.active ? (
                <button
                  className="secondary-button"
                  disabled={busy}
                  type="button"
                  onClick={() => void issueKey(identity.id)}
                >
                  <KeyRound size={14} /> Create new key
                </button>
              ) : null}
            </article>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={Bot}
          title="No external agents"
          description="Create a separate, least-privilege identity for each MCP client or application."
        />
      )}

      <form
        className="card agent-create"
        onSubmit={(event) => void savePolicy(event)}
      >
        <div>
          <p className="section-label">Delegated actions</p>
          <h2>Set an action policy</h2>
          <p className="muted">
            Impact is assigned here by the owner. High and safety-critical
            actions always wait for confirmation.
          </p>
        </div>
        <label>
          <span>Agent</span>
          <select
            required
            value={policyIdentity}
            onChange={(event) => setPolicyIdentity(event.target.value)}
          >
            <option value="">Choose an agent</option>
            {identities
              .filter(
                (identity) =>
                  identity.active && identity.scopes.includes("agent:delegate"),
              )
              .map((identity) => (
                <option key={identity.id} value={identity.id}>
                  {identity.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          <span>Action type</span>
          <input
            maxLength={200}
            placeholder="calendar.invitation.respond"
            required
            value={actionType}
            onChange={(event) => setActionType(event.target.value)}
          />
        </label>
        <div className="policy-fields">
          <label>
            <span>Impact</span>
            <select
              value={impact}
              onChange={(event) => {
                const next = event.target.value as DecisionImpact;
                setImpact(next);
                setMinimumConfidence(
                  next === "low" ? 0.9 : next === "medium" ? 0.95 : 1,
                );
                if (next === "high" || next === "safety_critical") {
                  setAllowAutomatic(false);
                }
              }}
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="safety_critical">Safety-critical</option>
            </select>
          </label>
          <label>
            <span>Minimum confidence</span>
            <input
              max={1}
              min={impact === "low" ? 0.9 : impact === "medium" ? 0.95 : 1}
              step={0.01}
              type="number"
              value={minimumConfidence}
              onChange={(event) =>
                setMinimumConfidence(Number(event.target.value))
              }
            />
          </label>
          <label className="scope-choice">
            <input
              checked={allowAutomatic}
              disabled={impact === "high" || impact === "safety_critical"}
              type="checkbox"
              onChange={(event) => setAllowAutomatic(event.target.checked)}
            />
            <span>Allow automatic approval</span>
          </label>
        </div>
        <button
          className="primary-button"
          disabled={busy || !policyIdentity || !actionType.trim()}
          type="submit"
        >
          <ShieldCheck size={15} /> Save policy
        </button>
        {policies.length ? (
          <div className="policy-list">
            {policies.map((policy) => (
              <div key={policy.id}>
                <span>
                  <strong>{policy.action_type}</strong> · {policy.impact} ·{" "}
                  {Math.round(policy.minimum_confidence * 100)}%
                </span>
                <button
                  className="text-button"
                  disabled={busy}
                  type="button"
                  onClick={() => void removePolicy(policy.id)}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        ) : null}
      </form>

      <div className="card audit-card">
        <p className="section-label">Approval workflow</p>
        <h2>Delegation requests</h2>
        {delegations.length ? (
          <ul>
            {delegations.map((delegation) => (
              <li key={delegation.id}>
                <span>
                  <strong>{delegation.action_label}</strong> ·{" "}
                  {delegation.impact} · {delegation.status}
                </span>
                {delegation.status === "pending" ? (
                  <span className="approval-actions">
                    <button
                      className="text-button"
                      disabled={busy}
                      type="button"
                      onClick={() => void reviewDelegation(delegation.id, true)}
                    >
                      <Check size={14} /> Approve
                    </button>
                    <button
                      className="text-button danger"
                      disabled={busy}
                      type="button"
                      onClick={() =>
                        void reviewDelegation(delegation.id, false)
                      }
                    >
                      <X size={14} /> Reject
                    </button>
                  </span>
                ) : (
                  <small>
                    {Math.round(delegation.prediction_confidence * 100)}%
                    confidence
                  </small>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No delegated actions have been requested.</p>
        )}
      </div>

      <DecisionIoSourcesPanel
        identities={identities}
        onChanged={() => {
          setSourcesRevision((value) => value + 1);
          void load();
        }}
      />
      <DecisionIoObservationsPanel
        revision={sourcesRevision}
        onChanged={() => void load()}
      />

      <div className="card audit-card">
        <p className="section-label">Local audit log</p>
        <h2>Recent access</h2>
        {audit.length ? (
          <ul>
            {audit.map((event) => (
              <li key={event.id}>
                <span>{event.action.replaceAll("_", " ")}</span>
                <small>{formatDate(event.created_at)}</small>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No audited access yet.</p>
        )}
      </div>
    </section>
  );
}
