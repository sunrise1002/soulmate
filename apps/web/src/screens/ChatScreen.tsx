import { useEffect, useState } from "react";
import type { Conversation, Message, SoulmateClient } from "@soulmate/sdk";

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

  useEffect(() => {
    client
      .conversations()
      .then((conversations: Conversation[]) => {
        const latest = conversations[0];
        if (latest !== undefined) {
          setConversationId(latest.id);
          setMessages(latest.messages);
        }
      })
      .catch(onAuthError);
  }, [client, onAuthError]);

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
