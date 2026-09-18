import { useCallback, useEffect, useState } from "react";
import type {
  Conversation,
  LearningStatus,
  Message,
  SoulmateClient,
} from "@soulmate/sdk";

export const LEARNING_POLL_MS = 5000;

const LEARNING_LABELS: Record<LearningStatus, string> = {
  pending: "Learning…",
  retrying: "Model provider busy, retrying…",
  learned: "Learned",
  no_evidence: "Nothing new to learn",
  failed: "Learning failed",
};

function learningActive(messages: Message[]) {
  return messages.some(
    (message) =>
      message.learning?.status === "pending" ||
      message.learning?.status === "retrying",
  );
}

interface Props {
  client: SoulmateClient;
  onAuthError: (error: unknown) => void;
}

export function ChatScreen({ client, onAuthError }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [learningNotice, setLearningNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [retryingId, setRetryingId] = useState<string | null>(null);

  const reload = useCallback(
    (id: string | null) =>
      client
        .conversations()
        .then((conversations: Conversation[]) => {
          const current =
            conversations.find((item) => item.id === id) ?? conversations[0];
          if (current !== undefined) {
            setConversationId(current.id);
            setMessages(current.messages);
          }
        })
        .catch(onAuthError),
    [client, onAuthError],
  );

  useEffect(() => void reload(null), [reload]);

  const polling = learningActive(messages);
  useEffect(() => {
    if (!polling) return;
    const timer = window.setInterval(
      () => void reload(conversationId),
      LEARNING_POLL_MS,
    );
    return () => window.clearInterval(timer);
  }, [polling, conversationId, reload]);

  const retryLearning = async (messageId: string) => {
    setRetryingId(messageId);
    setError(null);
    try {
      const learning = await client.retryLearning(messageId);
      setMessages((current) =>
        current.map((message) =>
          message.id === messageId ? { ...message, learning } : message,
        ),
      );
    } catch (caught) {
      onAuthError(caught);
      setError(
        caught instanceof Error
          ? caught.message
          : "Learning could not be retried.",
      );
    } finally {
      setRetryingId(null);
    }
  };

  const send = async () => {
    setPending(true);
    setError(null);
    setLearningNotice(null);
    try {
      const response = await client.chat(
        draft.trim(),
        conversationId ?? undefined,
      );
      setConversationId(response.conversation_id);
      setMessages((current) => [
        ...current,
        {
          id: response.user_message_id,
          role: "user",
          content: draft.trim(),
          provider_model: null,
          created_at: response.message.created_at,
        },
        response.message,
      ]);
      if (response.learning_status === "pending") {
        setLearningNotice(
          response.learning_error ??
            "The reply was saved. Learning continues in the background.",
        );
      }
      setDraft("");
      await reload(response.conversation_id);
    } catch (caught) {
      onAuthError(caught);
      setError(
        caught instanceof Error
          ? caught.message
          : "The message could not be sent.",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <section className="panel">
      <h2>Chat</h2>
      <ol className="messages">
        {messages.map((message) => (
          <li key={message.id} className={message.role}>
            <span className="role">{message.role}</span>
            <p>{message.content}</p>
            {message.learning ? (
              <p className={`learning ${message.learning.status}`}>
                {LEARNING_LABELS[message.learning.status]}
                {message.learning.status === "failed" && (
                  <button
                    type="button"
                    disabled={retryingId === message.id}
                    onClick={() => void retryLearning(message.id)}
                  >
                    Retry learning
                  </button>
                )}
              </p>
            ) : null}
          </li>
        ))}
      </ol>
      {messages.length === 0 && (
        <p className="hint">Start a conversation to build your model.</p>
      )}
      <textarea
        aria-label="Message"
        rows={3}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
      <button
        type="button"
        disabled={pending || draft.trim().length === 0}
        onClick={() => void send()}
      >
        {pending ? "Sending…" : "Send"}
      </button>
      {error !== null && <p role="alert">{error}</p>}
      {learningNotice !== null && <p role="status">{learningNotice}</p>}
    </section>
  );
}
