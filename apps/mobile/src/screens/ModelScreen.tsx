import { useCallback, useEffect, useState } from "react";
import { Button, FlatList, Text, View } from "react-native";
import type {
  ActiveQuestion,
  ModelSummary,
  Preference,
  SoulmateClient,
} from "@soulmate/sdk";

import { styles } from "../theme.ts";

interface Props {
  client: SoulmateClient;
  onError: (error: unknown) => void;
}

export function ModelScreen({ client, onError }: Props) {
  const [summary, setSummary] = useState<ModelSummary | null>(null);
  const [preferences, setPreferences] = useState<Preference[]>([]);
  const [question, setQuestion] = useState<ActiveQuestion | null>(null);

  const load = useCallback(() => {
    Promise.all([
      client.modelSummary(),
      client.preferences(),
      client.activeQuestions(),
    ])
      .then(([nextSummary, nextPreferences, questions]) => {
        setSummary(nextSummary);
        setPreferences(nextPreferences);
        setQuestion(
          questions.find((item) => item.status === "pending") ?? null,
        );
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

  const generateQuestion = async () => {
    try {
      const generated = await client.generateActiveQuestions(1);
      setQuestion(generated[0] ?? null);
    } catch (caught) {
      onError(caught);
    }
  };

  const answerQuestion = async (choice: "a" | "b") => {
    if (question === null) return;
    try {
      await client.answerActiveQuestion(question.id, choice);
      setQuestion(null);
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
      <View style={styles.card}>
        <Text>Clarify uncertain trade-offs</Text>
        {question === null ? (
          <Button
            title="Ask me a question"
            onPress={() => void generateQuestion()}
          />
        ) : (
          <View>
            <Text style={styles.hint}>{question.prompt}</Text>
            <Button
              title={question.option_a_label}
              onPress={() => void answerQuestion("a")}
            />
            <Button
              title={question.option_b_label}
              onPress={() => void answerQuestion("b")}
            />
          </View>
        )}
      </View>
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
