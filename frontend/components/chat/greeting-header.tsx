"use client";

import { motion } from "framer-motion";
import { useLanguage } from "@/lib/i18n";

/**
 * Shared title/subtitle copy for the chat empty state and the Agentes tab
 * (AgentComposer) — both read the same `t.panel.chat.greeting` dict keys.
 * `animated` keeps each caller's existing visual treatment: the chat empty
 * state fades/slides in, AgentComposer's card renders it statically.
 */
export const GreetingHeader = ({ animated = true }: { animated?: boolean }) => {
  const { t } = useLanguage();
  const greetingDict = t.panel.chat.greeting;

  if (!animated) {
    return (
      <div>
        <h2 className="font-semibold text-2xl tracking-tight text-foreground">
          {greetingDict.title}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          {greetingDict.subtitle}
        </p>
      </div>
    );
  }

  return (
    <>
      <motion.div
        animate={{ opacity: 1, y: 0 }}
        className="text-center font-semibold text-2xl tracking-tight text-foreground md:text-3xl"
        initial={{ opacity: 0, y: 10 }}
        transition={{ delay: 0.35, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      >
        {greetingDict.title}
      </motion.div>
      <motion.div
        animate={{ opacity: 1, y: 0 }}
        className="mt-3 text-center text-muted-foreground/80 text-sm"
        initial={{ opacity: 0, y: 10 }}
        transition={{ delay: 0.5, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      >
        {greetingDict.subtitle}
      </motion.div>
    </>
  );
};
