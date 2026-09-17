import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "../runtime.ts";
import type {
  KeyAlias,
  KeyAliasList,
  KeyAliasReviewAction,
  KeyAliasStatus,
} from "../types.ts";
import { humanizeKey } from "../utils.ts";

interface DuplicateKeysPanelProps {
  revision: number;
  onChanged: () => void;
}

const SECTIONS: { status: KeyAliasStatus; title: string }[] = [
  { status: "suggested", title: "Possible duplicate keys" },
  { status: "active", title: "Merged keys" },
  { status: "rejected", title: "Kept separate" },
];

function aliasId(alias: KeyAlias): string {
  return `${alias.target_type}:${alias.alias_key}`;
}

function describe(alias: KeyAlias): string {
  const relation = alias.polarity === -1 ? "opposite of" : "same as";
  return `${humanizeKey(alias.alias_key)} → ${relation} ${humanizeKey(alias.canonical_key)}`;
}

export function DuplicateKeysPanel({
  revision,
  onChanged,
}: DuplicateKeysPanelProps) {
  const [list, setList] = useState<KeyAliasList | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setList(await apiRequest<KeyAliasList>("GET", "/v1/key-aliases"));
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Merged keys are unavailable.",
      );
    }
  }, []);

  useEffect(() => void load(), [load, revision]);

  async function change(
    alias: KeyAlias,
    action: KeyAliasReviewAction | "remove",
  ) {
    if (busy) return;
    setBusy(true);
    const target = {
      target_type: alias.target_type,
      alias_key: alias.alias_key,
    };
    try {
      if (action === "remove") {
        await apiRequest("POST", "/v1/key-aliases/remove", target);
      } else {
        await apiRequest("POST", "/v1/key-aliases/review", {
          ...target,
          action,
        });
      }
      await load();
      onChanged();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The key merge could not be changed.",
      );
    } finally {
      setBusy(false);
    }
  }

  function actions(alias: KeyAlias) {
    const canInvert = alias.target_type === "preference";
    const button = (label: string, action: KeyAliasReviewAction | "remove") => (
      <button
        className="secondary-button"
        disabled={busy}
        type="button"
        onClick={() => void change(alias, action)}
      >
        {label}
      </button>
    );
    if (alias.status === "suggested") {
      return (
        <>
          {button("Merge", "approve")}
          {canInvert ? button("Merge as opposite", "invert") : null}
          {button("Keep separate", "reject")}
        </>
      );
    }
    if (alias.status === "active") {
      return (
        <>
          {canInvert ? button("Flip direction", "invert") : null}
          {/* Automatic merges are rejected so they are not proposed again. */}
          {button("Undo", alias.method === "owner" ? "remove" : "reject")}
        </>
      );
    }
    return button("Merge", "approve");
  }

  const aliases = list?.aliases ?? [];
  return (
    <article className="card duplicate-keys" aria-label="Duplicate keys">
      <span className="section-label">Key consistency</span>
      <h2>Duplicate keys</h2>
      {error ? <div className="inline-error">{error}</div> : null}
      {list !== null && !list.enabled ? (
        <p className="muted">
          Key merging is turned off in the configuration, so merges below are
          not applied.
        </p>
      ) : null}
      {list !== null && aliases.length === 0 ? (
        <p className="muted">No duplicate keys have been found.</p>
      ) : null}
      {SECTIONS.map(({ status, title }) => {
        const items = aliases.filter((item) => item.status === status);
        if (items.length === 0) return null;
        return (
          <section key={status}>
            <h3>{title}</h3>
            <ul>
              {items.map((alias) => (
                <li key={aliasId(alias)}>
                  <span>{describe(alias)}</span>
                  {list?.enabled ? (
                    <span className="resolve-actions">{actions(alias)}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </article>
  );
}
