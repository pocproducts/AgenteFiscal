"use client";

import { motion } from "framer-motion";
import { useActiveChat } from "@/hooks/use-active-chat";
import { useLanguage } from "@/lib/i18n";
import { MultimodalInput } from "./multimodal-input";

export const Greeting = () => {
  const { t } = useLanguage();
  const greetingDict = t.panel.chat.greeting;

  const {
    chatId,
    messages,
    setMessages,
    sendMessage,
    status,
    stop,
    setCurrentModelId,
    currentModelId,
    input,
    setInput,
    visibilityType,
    isLoading,
  } = useActiveChat();

  return (
    <div className="flex w-full flex-col items-center px-4" key="overview">
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

      <motion.div
        animate={{ opacity: 1, y: 0 }}
        className="mt-8 flex w-full justify-center"
        initial={{ opacity: 0, y: 10 }}
        transition={{ delay: 0.65, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      >
        <MultimodalInput
          attachments={[]} // Not used anymore but kept for component props
          chatId={chatId}
          editingMessage={null}
          input={input}
          isLoading={isLoading}
          messages={messages}
          onCancelEdit={() => {}}
          onModelChange={setCurrentModelId}
          selectedModelId={currentModelId}
          selectedVisibilityType={visibilityType}
          sendMessage={sendMessage}
          setAttachments={() => {}}
          setInput={setInput}
          setMessages={setMessages}
          status={status}
          stop={stop}
        />
      </motion.div>
    </div>
  );
};
