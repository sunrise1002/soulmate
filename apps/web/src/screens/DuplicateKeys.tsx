import { useCallback, useEffect, useState } from "react";
import type {
  KeyAlias,
  KeyAliasList,
  KeyAliasReviewAction,
  SoulmateClient,
} from "@soulmate/sdk";

interface Props {
  client: SoulmateClient;
  onChanged: () => void;
}

const TITLES: Record<KeyAlias["status"], string> = {
  suggested: "Possible duplicate keys",
  active: "Merged keys",
  rejected: "Kept separate",
};

type Change = KeyAliasReviewAction | "remove";

/** Owner-only review of merged target keys; never render it for paired devices. */
export function DuplicateKeys({ client, onChanged }: Props) {
  const [list, setList] = useState<KeyAliasList | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(() => {
    client
      .keyAliases()
      .then(setList)
      .catch(() => setStatus("Merged keys are unavailable."));
  }, [client]);

  useEffect(load, [load]);

  const change = async (alias: KeyAlias, action: Change) => {
    try {
      if (action === "remove") {
        await client.removeKeyAlias(alias);
      } else {
        await client.reviewKeyAlias(alias, action);
      }
      setStatus(null);
      load();
      onChanged();
    } catch (caught) {
      setStatus(
        caught instanceof Error && caught.message
          ? caught.message
          : "The key merge could not be changed.",
      );
    }
  };

  const actions = (alias: KeyAlias): [string, Change][] => {
    const invertible = alias.target_type === "preference";
    if (alias.status === "suggested") {
      return [
        ["Merge", "approve"],
        ...(invertible
          ? [["Merge as opposite", "invert"] as [string, Change]]
          : []),
        ["Keep separate", "reject"],
      ];
    }
    if (alias.status === "active") {
      // Automatic merges are rejected so they are not proposed again.
      return [
        ...(invertible
          ? [["Flip direction", "invert"] as [string, Change]]
          : []),
        ["Undo", alias.method === "owner" ? "remove" : "reject"],
      ];
    }
    return [["Merge", "approve"]];
  };

  if (list === null) {
    return status === null ? null : <p role="alert">{status}</p>;
  }
  return (
    <div className="prediction">
      <h3>Duplicate keys</h3>
      {!list.enabled && (
        <p className="hint">
          Key merging is turned off in the configuration, so merges below are
          not applied.
        </p>
      )}
      {list.aliases.length === 0 && (
        <p className="hint">No duplicate keys have been found.</p>
      )}
      <ul className="preferences">
        {list.aliases.map((alias) => (
          <li key={`${alias.target_type}:${alias.alias_key}`}>
            <span className="hint">{TITLES[alias.status]}</span>
            <span className="key">{alias.alias_key}</span>
            <span>
              {alias.polarity === -1 ? "opposite of" : "same as"}{" "}
              <span className="key">{alias.canonical_key}</span>
            </span>
            {list.enabled &&
              actions(alias).map(([label, action]) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => void change(alias, action)}
                >
                  {label}
                </button>
              ))}
          </li>
        ))}
      </ul>
      {status !== null && <p role="alert">{status}</p>}
    </div>
  );
}
