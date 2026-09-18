import { useEffect, useState } from "react";
import { Button, FlatList, Text, TextInput, View } from "react-native";
import type { LearningStatus, Message, SoulmateClient } from "@soulmate/sdk";

import { styles } from "../theme.ts";

const LEARNING_LABELS: Record<LearningStatus, string> = {
  pending: "Learning…",
  retrying: "Model provider busy, retrying…",
  learned: "Learned",
  no_evidence: "Nothing new to learn",
  failed: "Learning failed",
};

interface Props {
  client: SoulmateClient;
  onError: (error: unknown) => void;
}

export function ChatScreen({ client, onError }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    client
      .conversations()
      .then((conversations) => {
        const latest = conversations[0];
        if (latest !== undefined) {
          setConversationId(latest.id);
          setMessages(latest.messages);
        }
      })
      .catch(onError);
  }, [client, onError]);

  const retryLearning = async (messageId: string) => {
    try {
      const learning = await client.retryLearning(messageId);
      setMessages((current) =>
        current.map((message) =>
          message.id === messageId ? { ...message, learning } : message,
        ),
      );
    } catch (caught) {
      onError(caught);
    }
  };

  const send = async () => {
    setPending(true);
    try {
      const response = await client.chat(
        draft.trim(),
        conversationId ?? undefined,
      );
      setConversationId(response.conversation_id);
      setMessages((current) => [...current, response.message]);
      setDraft("");
    } catch (caught) {
      onError(caught);
    } finally {
      setPending(false);
    }
  };

  return (
    <View style={styles.screen}>
      <Text style={styles.title}>Chat</Text>
      <FlatList
        data={messages}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <View style={styles.card}>
            <Text style={styles.hint}>{item.role}</Text>
            <Text>{item.content}</Text>
            {item.learning ? (
              <Text style={styles.hint}>
                {LEARNING_LABELS[item.learning.status]}
              </Text>
            ) : null}
            {item.learning?.status === "failed" ? (
              <Button
                title="Retry learning"
                onPress={() => void retryLearning(item.id)}
              />
            ) : null}
          </View>
        )}
      />
      <TextInput
        style={styles.input}
        value={draft}
        multiline
        accessibilityLabel="Message"
        onChangeText={setDraft}
      />
      <Button
        title={pending ? "Sending…" : "Send"}
        disabled={pending || draft.trim().length === 0}
        onPress={() => void send()}
      />
    </View>
  );
}
