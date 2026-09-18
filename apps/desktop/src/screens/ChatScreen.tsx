import { ArrowUp, MessageCircleMore, Plus, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { SyntheticEvent } from "react";

import { EmptyState } from "../components/EmptyState.tsx";
import {
  LearningStatus,
  isLearningActive,
} from "../components/LearningStatus.tsx";
import { apiRequest } from "../runtime.ts";
import type {
  ChatResponse,
  Conversation,
  Message,
  MessageLearning,
} from "../types.ts";
import { formatDate } from "../utils.ts";

export const LEARNING_POLL_MS = 5000;

function learnedCount(conversations: Conversation[]) {
  return conversations
    .flatMap((item) => item.messages)
    .filter((message) => message.learning?.status === "learned").length;
}

interface ChatScreenProps {
  onModelChanged: () => void;
}

export function ChatScreen({ onModelChanged }: ChatScreenProps) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [learningNotice, setLearningNotice] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const learned = useRef<number | null>(null);

  const loadConversations = useCallback(async () => {
    try {
      const items = await apiRequest<Conversation[]>(
        "GET",
        "/v1/conversations",
      );
      setConversations(items);
      setActiveId((current) => current ?? items[0]?.id ?? null);
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Conversation history is unavailable.",
      );
    }
  }, []);

  useEffect(() => void loadConversations(), [loadConversations]);

  const active = useMemo(
    () => conversations.find((item) => item.id === activeId) ?? null,
    [activeId, conversations],
  );
  const learningActive = conversations.some((item) =>
    item.messages.some((message) => isLearningActive(message.learning)),
  );

  useEffect(() => {
    if (!learningActive) return;
    const timer = window.setInterval(
      () => void loadConversations(),
      LEARNING_POLL_MS,
    );
    return () => window.clearInterval(timer);
  }, [learningActive, loadConversations]);

  useEffect(() => {
    // Background learning changes the model after the reply, so tell the shell.
    const count = learnedCount(conversations);
    if (learned.current !== null && count > learned.current) onModelChanged();
    learned.current = count;
  }, [conversations, onModelChanged]);

  async function retryLearning(messageId: string) {
    setRetryingId(messageId);
    setError(null);
    try {
      const learning = await apiRequest<MessageLearning>(
        "POST",
        `/v1/messages/${encodeURIComponent(messageId)}/learning/retry`,
      );
      setConversations((items) =>
        items.map((item) => ({
          ...item,
          messages: item.messages.map((message) =>
            message.id === messageId ? { ...message, learning } : message,
          ),
        })),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Learning could not be retried.",
      );
    } finally {
      setRetryingId(null);
    }
  }

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || sending) return;
    setSending(true);
    setError(null);
    setLearningNotice(null);
    const optimistic: Message = {
      id: "pending-user",
      role: "user",
      content,
      provider_model: null,
      created_at: new Date().toISOString(),
    };
    if (active !== null) {
      setConversations((items) =>
        items.map((item) =>
          item.id === active.id
            ? { ...item, messages: [...item.messages, optimistic] }
            : item,
        ),
      );
    }
    setDraft("");
    try {
      const result = await apiRequest<ChatResponse>("POST", "/v1/chat", {
        content,
        conversation_id: activeId,
      });
      await loadConversations();
      setActiveId(result.conversation_id);
      if (result.snapshot_version !== null) onModelChanged();
      if (result.learning_status === "pending") {
        setLearningNotice(
          result.learning_error ??
            "The reply was saved. Learning continues privately in the background.",
        );
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The message could not be sent.",
      );
      setDraft(content);
      await loadConversations();
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="screen chat-screen">
      <header className="screen-header">
        <div>
          <p className="eyebrow">A quiet place to think</p>
          <h1>Chat</h1>
        </div>
        <button
          className="secondary-button"
          type="button"
          onClick={() => setActiveId(null)}
        >
          <Plus size={16} /> New conversation
        </button>
      </header>
      <div className="chat-layout">
        <aside className="conversation-list">
          <span className="section-label">Recent</span>
          {conversations.map((conversation) => (
            <button
              className={
                conversation.id === activeId
                  ? "conversation active"
                  : "conversation"
              }
              key={conversation.id}
              type="button"
              onClick={() => setActiveId(conversation.id)}
            >
              <strong>
                {conversation.messages[0]?.content ?? "New conversation"}
              </strong>
              <span>{formatDate(conversation.updated_at)}</span>
            </button>
          ))}
        </aside>
        <div className="chat-panel">
          <div className="message-stream" aria-live="polite">
            {active?.messages.length ? (
              active.messages.map((message) => (
                <article className={`message ${message.role}`} key={message.id}>
                  <div className="message-avatar">
                    {message.role === "assistant" ? (
                      <Sparkles size={15} />
                    ) : (
                      "You"
                    )}
                  </div>
                  <div>
                    <span>
                      {message.role === "assistant" ? "Soulmate" : "You"}
                    </span>
                    <p>{message.content}</p>
                    {message.learning ? (
                      <LearningStatus
                        learning={message.learning}
                        retrying={retryingId === message.id}
                        onRetry={(id) => void retryLearning(id)}
                      />
                    ) : null}
                  </div>
                </article>
              ))
            ) : (
              <EmptyState
                icon={MessageCircleMore}
                title="Start with what matters today"
                description="Share a thought, preference, or decision. Soulmate keeps the useful parts in your private model."
              />
            )}
            {sending ? <div className="thinking">Thinking locally…</div> : null}
          </div>
          {error ? <div className="inline-error">{error}</div> : null}
          {learningNotice ? (
            <div className="inline-notice">{learningNotice}</div>
          ) : null}
          <form className="composer" onSubmit={(event) => void submit(event)}>
            <textarea
              aria-label="Message"
              maxLength={50000}
              placeholder="Tell Soulmate what's on your mind…"
              rows={2}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <button
              aria-label="Send message"
              disabled={!draft.trim() || sending}
              type="submit"
            >
              <ArrowUp size={18} />
            </button>
          </form>
        </div>
      </div>
    </section>
  );
}
