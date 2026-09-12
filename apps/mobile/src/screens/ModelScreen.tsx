import { useCallback, useEffect, useState } from "react";
import { Button, FlatList, Text, View } from "react-native";
import type { ModelSummary, Preference, SoulmateClient } from "@soulmate/sdk";

import { styles } from "../theme.ts";

interface Props {
  client: SoulmateClient;
  onError: (error: unknown) => void;
}

export function ModelScreen({ client, onError }: Props) {
  const [summary, setSummary] = useState<ModelSummary | null>(null);
  const [preferences, setPreferences] = useState<Preference[]>([]);

  const load = useCallback(() => {
    Promise.all([client.modelSummary(), client.preferences()])
      .then(([nextSummary, nextPreferences]) => {
        setSummary(nextSummary);
        setPreferences(nextPreferences);
      })
      .catch(onError);
  }, [client, onError]);

  useEffect(load, [load]);

  const correct = async (key: string, value: number) => {
    try {
      await client.correctPreference(key, value);
      load();
    } catch (caught) {
      onError(caught);
    }
  };

  return (
    <View style={styles.screen}>
      <Text style={styles.title}>My Model</Text>
      {summary !== null && (
        <Text style={styles.hint}>
          {summary.preference_count} preferences · evidence revision{" "}
          {summary.evidence_revision}
        </Text>
      )}
      <FlatList
        data={preferences}
        keyExtractor={(item) => item.key}
        renderItem={({ item }) => (
          <View style={styles.card}>
            <Text>{item.key}</Text>
            <Text style={styles.hint}>
              {item.value.toFixed(2)} · uncertainty{" "}
              {item.uncertainty.toFixed(2)}
            </Text>
            <View style={styles.row}>
              <Button
                title="I like this"
                onPress={() => void correct(item.key, 1)}
              />
              <Button
                title="I do not"
                onPress={() => void correct(item.key, -1)}
              />
            </View>
          </View>
        )}
      />
    </View>
  );
}
