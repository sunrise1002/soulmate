import { useCallback, useEffect, useState } from "react";
import type { KeyLabel, SoulmateClient } from "@soulmate/sdk";

interface Props {
  client: SoulmateClient;
  /** Preference keys the model already holds; only those can be named. */
  keys: string[];
  onChanged: () => void;
}

const ALIAS_LIMIT = 5;

function splitAliases(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item !== "")
    .slice(0, ALIAS_LIMIT);
}

/** Owner-only naming of target keys; the model embeds the owner's wording too. */
export function KeyLabels({ client, keys, onChanged }: Props) {
  const [labels, setLabels] = useState<KeyLabel[]>([]);
  const [selected, setSelected] = useState("");
  const [label, setLabel] = useState("");
  const [aliases, setAliases] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(() => {
    client
      .keyLabels()
      .then((list) => setLabels(list.labels))
      .catch(() => setStatus("Key names are unavailable."));
  }, [client]);

  useEffect(load, [load]);

  const current = keys.includes(selected) ? selected : (keys[0] ?? "");

  const choose = (key: string) => {
    setSelected(key);
    const stored = labels.find(
      (item) => item.key === key && item.target_type === "preference",
    );
    setLabel(stored?.label ?? "");
    setAliases((stored?.aliases ?? []).join(", "));
    setStatus(null);
  };

  const save = async () => {
    if (current === "") return;
    try {
      await client.setKeyLabel(
        "preference",
        current,
        label.trim() === "" ? null : label.trim(),
        splitAliases(aliases),
      );
      setStatus("Saved your name for this key.");
      load();
      onChanged();
    } catch (caught) {
      setStatus(
        caught instanceof Error && caught.message
          ? caught.message
          : "The name could not be saved.",
      );
    }
  };

  const clear = async () => {
    if (current === "") return;
    try {
      await client.removeKeyLabel({ target_type: "preference", key: current });
      setLabel("");
      setAliases("");
      setStatus("Removed your name for this key.");
      load();
      onChanged();
    } catch (caught) {
      setStatus(
        caught instanceof Error && caught.message
          ? caught.message
          : "The name could not be removed.",
      );
    }
  };

  if (keys.length === 0) {
    return null;
  }

  return (
    <div className="prediction">
      <h3>Your names for keys</h3>
      <p className="hint">
        Write a key&apos;s name in the language you use. Soulmate then matches
        your messages to that key by your own wording.
      </p>
      <label>
        Key
        <select
          value={current}
          onChange={(event) => choose(event.target.value)}
        >
          {keys.map((key) => (
            <option key={key} value={key}>
              {key}
            </option>
          ))}
        </select>
      </label>
      <label>
        Name
        <input
          maxLength={200}
          placeholder="giao diện tối"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
        />
      </label>
      <label>
        Other wordings, separated by commas
        <input
          placeholder="nền tối, dark mode"
          value={aliases}
          onChange={(event) => setAliases(event.target.value)}
        />
      </label>
      <button type="button" onClick={() => void save()}>
        Save name
      </button>
      <button type="button" onClick={() => void clear()}>
        Remove name
      </button>
      {status !== null && <p role="status">{status}</p>}
    </div>
  );
}
