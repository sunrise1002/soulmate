import { useCallback, useEffect, useState } from "react";
import type { SyntheticEvent } from "react";

import { apiRequest } from "../runtime.ts";
import type { KeyLabel, KeyLabelList } from "../types.ts";

interface KeyLabelEditorProps {
  targetKey: string;
  onChanged: () => void;
}

const ALIAS_LIMIT = 5;

/** Name one key in the owner's own words; the model embeds that name with the key. */
export function KeyLabelEditor({ targetKey, onChanged }: KeyLabelEditorProps) {
  const [stored, setStored] = useState<KeyLabel | null>(null);
  const [label, setLabel] = useState("");
  const [aliases, setAliases] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await apiRequest<KeyLabelList>("GET", "/v1/key-labels");
      const current =
        list.labels.find(
          (item) => item.key === targetKey && item.target_type === "preference",
        ) ?? null;
      setStored(current);
      setLabel(current?.label ?? "");
      setAliases((current?.aliases ?? []).join(", "));
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "The name is unavailable.",
      );
    }
  }, [targetKey]);

  useEffect(() => void load(), [load]);

  async function save(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      await apiRequest<KeyLabel>("POST", "/v1/key-labels", {
        target_type: "preference",
        key: targetKey,
        label: label.trim() === "" ? null : label.trim(),
        aliases: aliases
          .split(",")
          .map((value) => value.trim())
          .filter((value) => value !== "")
          .slice(0, ALIAS_LIMIT),
      });
      await load();
      onChanged();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "The name was not saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    if (busy) return;
    setBusy(true);
    try {
      await apiRequest("POST", "/v1/key-labels/remove", {
        target_type: "preference",
        key: targetKey,
      });
      await load();
      onChanged();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "The name was not removed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="key-label-editor" onSubmit={(event) => void save(event)}>
      <span className="section-label">Your name for this key</span>
      <p className="muted">
        Write it in the language you use. Soulmate matches your messages to this
        key by that wording too.
      </p>
      {error ? <div className="inline-error">{error}</div> : null}
      <label>
        <span>Name</span>
        <input
          maxLength={200}
          placeholder="giao diện tối"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
        />
      </label>
      <label>
        <span>Other wordings, separated by commas</span>
        <input
          placeholder="nền tối, dark mode"
          value={aliases}
          onChange={(event) => setAliases(event.target.value)}
        />
      </label>
      <div className="resolve-actions">
        <button className="secondary-button" disabled={busy} type="submit">
          Save name
        </button>
        {stored !== null ? (
          <button
            className="secondary-button"
            disabled={busy}
            type="button"
            onClick={() => void clear()}
          >
            Remove name
          </button>
        ) : null}
      </div>
      {stored?.source === "extracted" ? (
        <small className="muted">
          Soulmate suggested this name while reading a message. Saving it makes
          it yours.
        </small>
      ) : null}
    </form>
  );
}
