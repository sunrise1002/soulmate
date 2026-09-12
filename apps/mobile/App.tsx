import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Text, View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import * as SecureStore from "expo-secure-store";
import { ApiError, type DeviceConnection } from "@soulmate/sdk";

import { createPinnedClient, verifyPinnedService } from "./src/pinning.ts";
import { ChatScreen } from "./src/screens/ChatScreen.tsx";
import { ConnectScreen } from "./src/screens/ConnectScreen.tsx";
import { DecideScreen } from "./src/screens/DecideScreen.tsx";
import { HistoryScreen } from "./src/screens/HistoryScreen.tsx";
import { ModelScreen } from "./src/screens/ModelScreen.tsx";
import {
  clearConnection,
  loadConnection,
  saveConnection,
} from "./src/storage.ts";
import { styles } from "./src/theme.ts";

type Tab = "chat" | "decide" | "model" | "history";

const TABS: { id: Tab; label: string }[] = [
  { id: "chat", label: "Chat" },
  { id: "decide", label: "Decide" },
  { id: "model", label: "My Model" },
  { id: "history", label: "History" },
];

export function App() {
  const [connection, setConnection] = useState<DeviceConnection | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [tab, setTab] = useState<Tab>("chat");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadConnection(SecureStore)
      .then(setConnection)
      .catch(() => setConnection(null))
      .finally(() => setLoaded(true));
  }, []);

  const client = useMemo(
    () => (connection === null ? null : createPinnedClient(connection)),
    [connection],
  );

  useEffect(() => {
    if (client === null || connection === null) {
      return;
    }
    verifyPinnedService(client, connection).catch((caught: unknown) => {
      setError(
        caught instanceof Error
          ? caught.message
          : "The service could not be verified.",
      );
    });
  }, [client, connection]);

  /** Forget a credential the owner revoked so the phone can pair again. */
  const handleError = useCallback((caught: unknown) => {
    if (caught instanceof ApiError && caught.requiresPairing) {
      void clearConnection(SecureStore);
      setConnection(null);
      setError(
        "This device is no longer paired. Scan a new code on your computer.",
      );
      return;
    }
    setError(caught instanceof Error ? caught.message : "The request failed.");
  }, []);

  const paired = async (next: DeviceConnection) => {
    await saveConnection(SecureStore, next);
    setConnection(next);
    setError(null);
  };

  const forget = async () => {
    await clearConnection(SecureStore);
    setConnection(null);
  };

  if (!loaded) {
    return (
      <SafeAreaProvider>
        <SafeAreaView style={styles.screen}>
          <Text>Loading…</Text>
        </SafeAreaView>
      </SafeAreaProvider>
    );
  }

  if (connection === null || client === null) {
    return (
      <SafeAreaProvider>
        <SafeAreaView style={{ flex: 1 }}>
          <StatusBar style="auto" />
          <ConnectScreen
            deviceName="Phone"
            onPaired={(next) => void paired(next)}
          />
          {error !== null && (
            <Text style={[styles.hint, styles.error]}>{error}</Text>
          )}
        </SafeAreaView>
      </SafeAreaProvider>
    );
  }

  return (
    <SafeAreaProvider>
      <SafeAreaView style={{ flex: 1 }}>
        <StatusBar style="auto" />
        <View style={styles.tabs}>
          {TABS.map((item) => (
            <Button
              key={item.id}
              title={item.label}
              onPress={() => setTab(item.id)}
            />
          ))}
        </View>
        {tab === "chat" && <ChatScreen client={client} onError={handleError} />}
        {tab === "decide" && (
          <DecideScreen client={client} onError={handleError} />
        )}
        {tab === "model" && (
          <ModelScreen client={client} onError={handleError} />
        )}
        {tab === "history" && (
          <HistoryScreen client={client} onError={handleError} />
        )}
        <View style={styles.tabs}>
          <Text style={styles.hint}>Paired with {connection.serviceUrl}</Text>
          <Button title="Forget this device" onPress={() => void forget()} />
        </View>
        {error !== null && (
          <Text style={[styles.hint, styles.error]}>{error}</Text>
        )}
      </SafeAreaView>
    </SafeAreaProvider>
  );
}
