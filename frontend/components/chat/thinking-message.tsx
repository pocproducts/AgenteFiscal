"use client";

import { useLanguage } from "@/lib/i18n";
import { Shimmer } from "../ai-elements/shimmer";
import { SparklesIcon } from "./icons";

export const ThinkingMessage = () => {
  const { t } = useLanguage();
  return (
    <div
      className="group/message w-full"
      data-role="assistant"
      data-testid="message-assistant-loading"
    >
      <div className="flex items-start gap-3">
        <div className="flex h-[calc(13px*1.65)] shrink-0 items-center">
          <div className="flex size-7 items-center justify-center rounded-lg bg-muted/60 text-muted-foreground ring-1 ring-border/50">
            <SparklesIcon size={13} />
          </div>
        </div>

        <div className="flex h-[calc(13px*1.65)] items-center text-[13px] leading-[1.65]">
          <Shimmer className="font-medium" duration={1}>
            {t.panel.chat.reasoning.thinking}
          </Shimmer>
        </div>
      </div>
    </div>
  );
};
