import { useEffect, useState } from "react";
import { FlatList, Text, View } from "react-native";
import type { DecisionHistoryItem, SoulmateClient } from "@soulmate/sdk";

import { styles } from "../theme.ts";

interface Props {
  client: SoulmateClient;
  onError: (error: unknown) => void;
}

export function HistoryScreen({ client, onError }: Props) {
  const [items, setItems] = useState<DecisionHistoryItem[]>([]);

  useEffect(() => {
    client.decisionHistory().then(setItems).catch(onError);
  }, [client, onError]);

  return (
    <View style={styles.screen}>
      <Text style={styles.title}>History</Text>
      <FlatList
        data={items}
        keyExtractor={(item) => item.decision.id}
        renderItem={({ item }) => (
          <View style={styles.card}>
            <Text>{item.decision.question}</Text>
            <Text style={styles.hint}>
              {item.decision.domain} · {item.decision.status}
            </Text>
            {item.prediction !== null && (
              <Text style={styles.hint}>
                Predicted {item.prediction.predicted_choice}
              </Text>
            )}
            {item.advice !== null && (
              <Text style={styles.hint}>
                Advised {item.advice.recommended_choice}
              </Text>
            )}
            {item.outcome !== null && (
              <Text style={styles.hint}>
                Satisfaction {(item.outcome.satisfaction * 100).toFixed(0)}%
                {item.outcome.regret ? " · regret" : ""}
              </Text>
            )}
          </View>
        )}
      />
    </View>
  );
}
