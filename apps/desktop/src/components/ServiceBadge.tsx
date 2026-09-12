import { CircleAlert, CircleCheck, LoaderCircle } from "lucide-react";

import type { ServiceStatus } from "../types.ts";

interface ServiceBadgeProps {
  status: ServiceStatus;
}

export function ServiceBadge({ status }: ServiceBadgeProps) {
  const online = status.state === "running";
  const starting = status.state === "starting";
  const Icon = online ? CircleCheck : starting ? LoaderCircle : CircleAlert;
  return (
    <div
      className={`service-badge service-${status.state}`}
      title={status.message}
    >
      <Icon className={starting ? "spin" : undefined} size={14} />
      <span>
        {online ? "Private & local" : starting ? "Starting" : "Service offline"}
      </span>
    </div>
  );
}
