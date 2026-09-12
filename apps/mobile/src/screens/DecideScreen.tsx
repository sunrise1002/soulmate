import { useState } from "react";
import { Button, Text, TextInput, View } from "react-native";
import type {
  Decision,
  DecisionPrediction,
  SoulmateClient,
} from "@soulmate/sdk";

import { styles } from "../theme.ts";

interface Props {
  client: SoulmateClient;
  onError: (error: unknown) => void;
}

export function DecideScreen({ client, onError }: Props) {
  const [question, setQuestion] = useState("");
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  const [decision, setDecision] = useState<Decision | null>(null);
  const [prediction, setPrediction] = useState<DecisionPrediction | null>(null);
  const [pending, setPending] = useState(false);

  const predict = async () => {
    setPending(true);
    try {
      const created = await client.createDecision("general", question.trim(), [
        { label: first.trim(), description: first.trim() },
        { label: second.trim(), description: second.trim() },
      ]);
      setDecision(created);
      setPrediction(await client.predictDecision(created.id));
    } catch (caught) {
      onError(caught);
    } finally {
      setPending(false);
    }
  };

  const resolve = async (optionId: string) => {
    if (decision === null) {
      return;
    }
    try {
      await client.resolveDecision(decision.id, optionId);
      setDecision(null);
      setPrediction(null);
      setQuestion("");
      setFirst("");
      setSecond("");
    } catch (caught) {
      onError(caught);
    }
  };

  return (
    <View style={styles.screen}>
      <Text style={styles.title}>Decide</Text>
      <TextInput
        style={styles.input}
        value={question}
        accessibilityLabel="Question"
        placeholder="What are you deciding?"
        onChangeText={setQuestion}
      />
      <TextInput
        style={styles.input}
        value={first}
        accessibilityLabel="Option 1"
        onChangeText={setFirst}
      />
      <TextInput
        style={styles.input}
        value={second}
        accessibilityLabel="Option 2"
        onChangeText={setSecond}
      />
      <Button
        title={pending ? "Predicting…" : "Predict my choice"}
        disabled={
          pending ||
          question.trim().length === 0 ||
          first.trim().length === 0 ||
          second.trim().length === 0
        }
        onPress={() => void predict()}
      />
      {prediction !== null && (
        <View style={styles.card}>
          <Text style={styles.title}>{prediction.predicted_choice}</Text>
          <Text style={styles.hint}>
            Confidence {(prediction.confidence * 100).toFixed(0)}%
          </Text>
          {prediction.ranking.map((item) => (
            <Button
              key={item.option_id}
              title={`I chose ${item.label}`}
              onPress={() => void resolve(item.option_id)}
            />
          ))}
        </View>
      )}
    </View>
  );
}
