import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, type Session } from "@soulmate/sdk";

import {
  clearConnection,
  createClient,
  loadConnection,
  saveConnection,
  type StoredConnection,
} from "./connection.ts";
import { ChatScreen } from "./screens/ChatScreen.tsx";
import { ConnectScreen } from "./screens/ConnectScreen.tsx";
import { DecideScreen } from "./screens/DecideScreen.tsx";
import { HistoryScreen } from "./screens/HistoryScreen.tsx";
import { ModelScreen } from "./screens/ModelScreen.tsx";

type Tab = "chat" | "decide" | "model" | "history";

const TABS: { id: Tab; label: string }[] = [
  { id: "chat", label: "Chat" },
  { id: "decide", label: "Decide" },
  { id: "model", label: "My Model" },
  { id: "history", label: "History" },
];

export interface AppProps {
  origin: string;
  storage: Storage;
}

export function App({ origin, storage }: AppProps) {
  const [connection, setConnection] = useState<StoredConnection | null>(() =>
    loadConnection(storage),
  );
  const [session, setSession] = useState<Session | null>(null);
  const [checked, setChecked] = useState(false);
  const [tab, setTab] = useState<Tab>("chat");

  const client = useMemo(
    () => createClient(origin, connection?.credential),
    [origin, connection?.credential],
  );

  useEffect(() => {
    let active = true;
    client
      .session()
      .then((next) => {
        if (active) {
          setSession(next);
        }
      })
      .catch(() => {
        if (active) {
          setSession(null);
        }
      })
      .finally(() => {
        if (active) {
          setChecked(true);
        }
      });
    return () => {
      active = false;
    };
  }, [client]);

  /** Drop a credential the owner revoked so the device can pair again. */
  const handleAuthError = useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.requiresPairing) {
        clearConnection(storage);
        setConnection(null);
        setSession(null);
      }
    },
    [storage],
  );

  const connect = (next: StoredConnection) => {
    saveConnection(storage, next);
    setConnection(next);
  };

  const disconnect = () => {
    clearConnection(storage);
    setConnection(null);
    setSession(null);
  };

  if (!checked) {
    return <main className="app">Loading…</main>;
  }

  if (session === null) {
    return (
      <main className="app">
        <h1>Soulmate</h1>
        <ConnectScreen client={client} onConnected={connect} />
      </main>
    );
  }

  return (
    <main className="app">
      <header>
        <h1>Soulmate</h1>
        <p className="hint">
          {session.actor === "owner"
            ? "Connected on this computer"
            : `Paired as ${session.device_name ?? "this device"}`}
          {session.actor === "device" && (
            <button type="button" onClick={disconnect}>
              Forget this device
            </button>
          )}
        </p>
      </header>
      <nav>
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-current={tab === item.id}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      {tab === "chat" && (
        <ChatScreen client={client} onAuthError={handleAuthError} />
      )}
      {tab === "decide" && (
        <DecideScreen client={client} onAuthError={handleAuthError} />
      )}
      {tab === "model" && (
        <ModelScreen
          client={client}
          isOwner={session.actor === "owner"}
          onAuthError={handleAuthError}
        />
      )}
      {tab === "history" && (
        <HistoryScreen client={client} onAuthError={handleAuthError} />
      )}
    </main>
  );
}
