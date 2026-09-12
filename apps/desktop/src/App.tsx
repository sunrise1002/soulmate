import {
  BrainCircuit,
  Bot,
  Clock3,
  MessageCircleMore,
  Settings as SettingsIcon,
  Smartphone,
  Sparkles,
  Split,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ServiceBadge } from "./components/ServiceBadge.tsx";
import { ChatScreen } from "./screens/ChatScreen.tsx";
import { DecideScreen } from "./screens/DecideScreen.tsx";
import { DevicesScreen } from "./screens/DevicesScreen.tsx";
import { ExternalAgentsScreen } from "./screens/ExternalAgentsScreen.tsx";
import { HistoryScreen } from "./screens/HistoryScreen.tsx";
import { ModelScreen } from "./screens/ModelScreen.tsx";
import { SettingsScreen } from "./screens/SettingsScreen.tsx";
import { getServiceStatus } from "./runtime.ts";
import type { ServiceStatus } from "./types.ts";

type Screen =
  "chat" | "decide" | "model" | "history" | "devices" | "agents" | "settings";

const navigation: {
  id: Screen;
  label: string;
  icon: typeof MessageCircleMore;
}[] = [
  { id: "chat", label: "Chat", icon: MessageCircleMore },
  { id: "decide", label: "Decide", icon: Split },
  { id: "model", label: "My Model", icon: BrainCircuit },
  { id: "history", label: "History", icon: Clock3 },
  { id: "devices", label: "Devices", icon: Smartphone },
  { id: "agents", label: "External Agents", icon: Bot },
  { id: "settings", label: "Settings", icon: SettingsIcon },
];

const initialStatus: ServiceStatus = {
  state: "starting",
  pid: null,
  message: "Starting the private local service.",
};

export function App() {
  const [screen, setScreen] = useState<Screen>("chat");
  const [serviceStatus, setServiceStatus] = useState(initialStatus);
  const [modelRevision, setModelRevision] = useState(0);

  const refreshServiceStatus = useCallback(async () => {
    try {
      setServiceStatus(await getServiceStatus());
    } catch {
      setServiceStatus({
        state: "failed",
        pid: null,
        message: "The desktop runtime could not inspect the local service.",
      });
    }
  }, []);

  useEffect(() => {
    void refreshServiceStatus();
    const interval = window.setInterval(
      () => void refreshServiceStatus(),
      2500,
    );
    return () => window.clearInterval(interval);
  }, [refreshServiceStatus]);

  const renderScreen = () => {
    switch (screen) {
      case "chat":
        return (
          <ChatScreen
            onModelChanged={() => setModelRevision((value) => value + 1)}
          />
        );
      case "decide":
        return (
          <DecideScreen
            onDecisionSaved={() => setModelRevision((value) => value + 1)}
          />
        );
      case "model":
        return (
          <ModelScreen
            revision={modelRevision}
            onModelChanged={() => setModelRevision((value) => value + 1)}
          />
        );
      case "history":
        return <HistoryScreen />;
      case "devices":
        return <DevicesScreen onServiceChanged={refreshServiceStatus} />;
      case "agents":
        return <ExternalAgentsScreen />;
      case "settings":
        return (
          <SettingsScreen
            serviceStatus={serviceStatus}
            onServiceChanged={refreshServiceStatus}
          />
        );
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="stars" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div className="brand">
          <div className="brand-mark">
            <Sparkles size={20} strokeWidth={1.8} />
          </div>
          <div>
            <strong>Soulmate</strong>
            <span>Personal intelligence</span>
          </div>
        </div>
        <nav aria-label="Main navigation">
          {navigation.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={screen === item.id ? "nav-item active" : "nav-item"}
                type="button"
                onClick={() => setScreen(item.id)}
              >
                <Icon size={18} strokeWidth={1.8} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <ServiceBadge status={serviceStatus} />
          <p>Your model stays on this device.</p>
        </div>
      </aside>
      <main className="main-content">
        <div key={`${screen}-${serviceStatus.state}`}>{renderScreen()}</div>
      </main>
    </div>
  );
}
