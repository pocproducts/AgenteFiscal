"use client";

import type { UseChatHelpers } from "@ai-sdk/react";
import type { UIMessage } from "ai";
import equal from "fast-deep-equal";
import { ArrowUpIcon, UserIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  type ChangeEvent,
  type Dispatch,
  memo,
  type SetStateAction,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useLocalStorage, useWindowSize } from "usehooks-ts";
import { toast } from "@/components/chat/toast";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useProfiles } from "@/hooks/use-profiles";
import { applyProfileCuitToInput } from "@/lib/cuit";
import { useLanguage } from "@/lib/i18n";
import type { Attachment, ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PromptInput } from "../ai-elements/prompt-input";
import { Button } from "../ui/button";
import {
  type SlashCommand,
  SlashCommandMenu,
  slashCommands,
} from "./slash-commands";
import type { VisibilityType } from "./visibility-selector";

function PureMultimodalInput({
  chatId,
  input,
  setInput,
  status,
  stop: _stop,
  attachments,
  setAttachments,
  messages,
  setMessages: _setMessages,
  sendMessage,
  className,
  selectedVisibilityType: _selectedVisibilityType,
  selectedModelId: _selectedModelId,
  onModelChange: _onModelChange,
  editingMessage: _editingMessage,
  onCancelEdit: _onCancelEdit,
  isLoading: _isLoading,
}: {
  chatId: string;
  input: string;
  setInput: Dispatch<SetStateAction<string>>;
  status: UseChatHelpers<ChatMessage>["status"];
  stop: () => void;
  attachments: Attachment[];
  setAttachments: Dispatch<SetStateAction<Attachment[]>>;
  messages: UIMessage[];
  setMessages: UseChatHelpers<ChatMessage>["setMessages"];
  sendMessage:
    | UseChatHelpers<ChatMessage>["sendMessage"]
    | (() => Promise<void>);
  className?: string;
  selectedVisibilityType: VisibilityType;
  selectedModelId: string;
  onModelChange?: (modelId: string) => void;
  editingMessage?: ChatMessage | null;
  onCancelEdit?: () => void;
  isLoading?: boolean;
}) {
  const _router = useRouter();
  const { t } = useLanguage();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { width } = useWindowSize();
  const hasAutoFocused = useRef(false);
  useEffect(() => {
    if (!hasAutoFocused.current && width) {
      const timer = setTimeout(() => {
        textareaRef.current?.focus();
        hasAutoFocused.current = true;
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [width]);

  const [localStorageInput, setLocalStorageInput] = useLocalStorage(
    "input",
    ""
  );

  const { profiles, activeProfileId, setActiveProfileId } = useProfiles();

  // Selecting a profile completes the CUIT part of the input with the profile's
  // CUIT (when it has one), so the user never has to retype it (e.g. selecting
  // "Gruppo Muratore" fills "30716395541 /…").
  const handleProfileChange = (value: string) => {
    setActiveProfileId(value);
    const profile = profiles.find((p) => p.id === value);
    if (profile?.cuit) {
      setInput((prev) => applyProfileCuitToInput(prev ?? "", profile.cuit));
    }
  };

  useEffect(() => {
    if (textareaRef.current) {
      const domValue = textareaRef.current.value;
      const finalValue = domValue || localStorageInput || "";
      setInput(finalValue);
    }
  }, [localStorageInput, setInput]);

  useEffect(() => {
    setLocalStorageInput(input);
  }, [input, setLocalStorageInput]);

  const _handleInput = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = event.target.value;
    setInput(val);

    if (val.startsWith("/") && !val.includes(" ")) {
      setSlashOpen(true);
      setSlashQuery(val.slice(1));
      setSlashIndex(0);
    } else {
      setSlashOpen(false);
    }
  };

  const handleSlashSelect = (cmd: SlashCommand) => {
    setSlashOpen(false);
    const lastSlashIndex = input.lastIndexOf("/");
    const prefix =
      lastSlashIndex === -1 ? input : input.slice(0, lastSlashIndex);
    setInput(`${prefix.trim()} /${cmd.name} `);
  };

  const _fileInputRef = useRef<HTMLInputElement>(null);
  const [_uploadQueue, setUploadQueue] = useState<string[]>([]);
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashQuery, setSlashQuery] = useState("");
  const [slashIndex, setSlashIndex] = useState(0);

  const submitForm = useCallback(() => {
    window.history.pushState(
      {},
      "",
      `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/chat/${chatId}`
    );

    if (attachments.length === 0) {
      sendMessage({
        role: "user",
        content: input,
      } as any);
    } else {
      sendMessage({
        role: "user",
        parts: [
          ...attachments.map((attachment) => ({
            type: "file" as const,
            url: attachment.url,
            name: attachment.name,
            mediaType: attachment.contentType,
          })),
          {
            type: "text",
            text: input,
          },
        ],
      } as any);
    }

    setAttachments([]);
    setLocalStorageInput("");
    setInput("");

    if (width && width > 768) {
      textareaRef.current?.focus();
    }
  }, [
    input,
    setInput,
    attachments,
    sendMessage,
    setAttachments,
    setLocalStorageInput,
    width,
    chatId,
  ]);

  const uploadFile = useCallback(
    async (file: File) => {
      const formData = new FormData();
      formData.append("file", file);

      try {
        const response = await fetch(
          `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/files/upload`,
          {
            method: "POST",
            body: formData,
          }
        );

        if (response.ok) {
          const data = await response.json();
          const { url, pathname, contentType } = data;

          return {
            url,
            name: pathname,
            contentType,
          };
        }
        const { error } = await response.json();
        toast({ description: error, type: "error" });
      } catch (_error) {
        toast({
          description: t.panel.chat.upload.failedToUpload,
          type: "error",
        });
      }
    },
    [t.panel.chat.upload.failedToUpload]
  );

  const _handleFileChange = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files || []);

      setUploadQueue(files.map((file) => file.name));

      try {
        const uploadPromises = files.map((file) => uploadFile(file));
        const uploadedAttachments = await Promise.all(uploadPromises);
        const successfullyUploadedAttachments = uploadedAttachments.filter(
          (attachment) => attachment !== undefined
        );

        setAttachments((currentAttachments) => [
          ...currentAttachments,
          ...successfullyUploadedAttachments,
        ]);
      } catch (_error) {
        toast({ description: t.panel.chat.upload.failedFiles, type: "error" });
      } finally {
        setUploadQueue([]);
      }
    },
    [setAttachments, uploadFile, t.panel.chat.upload.failedFiles]
  );

  const handlePaste = useCallback(
    async (event: ClipboardEvent) => {
      const items = event.clipboardData?.items;
      if (!items) {
        return;
      }

      const imageItems = Array.from(items).filter((item) =>
        item.type.startsWith("image/")
      );

      if (imageItems.length === 0) {
        return;
      }

      event.preventDefault();

      setUploadQueue((prev) => [...prev, t.panel.chat.upload.pastedImage]);

      try {
        const uploadPromises = imageItems
          .map((item) => item.getAsFile())
          .filter((file): file is File => file !== null)
          .map((file) => uploadFile(file));

        const uploadedAttachments = await Promise.all(uploadPromises);
        const successfullyUploadedAttachments = uploadedAttachments.filter(
          (attachment) =>
            attachment !== undefined &&
            attachment.url !== undefined &&
            attachment.contentType !== undefined
        );

        setAttachments((curr) => [
          ...curr,
          ...(successfullyUploadedAttachments as Attachment[]),
        ]);
      } catch (_error) {
        toast({ description: t.panel.chat.upload.failedPasted, type: "error" });
      } finally {
        setUploadQueue([]);
      }
    },
    [
      setAttachments,
      uploadFile,
      t.panel.chat.upload.pastedImage,
      t.panel.chat.upload.failedPasted,
    ]
  );

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }

    textarea.addEventListener("paste", handlePaste);
    return () => textarea.removeEventListener("paste", handlePaste);
  }, [handlePaste]);

  if (messages.length > 0) {
    return null;
  }

  return (
    <div
      className={cn(
        "mx-auto flex w-full max-w-[1020px] flex-col items-center gap-4 px-4",
        className
      )}
    >
      <PromptInput
        className="w-full"
        onSubmit={() => {
          const hasSlash = input.includes("/");
          if (
            input.length >= 11 &&
            hasSlash &&
            (status === "ready" || status === "error")
          ) {
            submitForm();
          }
        }}
      >
        <div className="relative flex w-full items-center gap-2 rounded-2xl border border-border/40 bg-card/50 p-1.5 shadow-sm transition-all focus-within:border-border/80 focus-within:ring-1 focus-within:ring-ring/20">
          <input
            autoComplete="off"
            className="flex-1 bg-transparent px-4 py-2 text-[15px] font-medium outline-none placeholder:text-muted-foreground/40"
            data-testid="multimodal-input"
            onChange={(e) => {
              const value = e.target.value;
              setInput(value);

              const lastSlashIndex = value.lastIndexOf("/");
              if (lastSlashIndex === -1) {
                setSlashOpen(false);
              } else {
                const query = value.slice(lastSlashIndex + 1);
                setSlashQuery(query);
                setSlashOpen(true);
              }
            }}
            onKeyDown={(e) => {
              if (slashOpen) {
                const filtered = slashCommands.filter((cmd) => {
                  const alreadySelected = input
                    .toLowerCase()
                    .includes(cmd.name.toLowerCase());
                  const matchesQuery = cmd.name
                    .toLowerCase()
                    .startsWith(slashQuery.toLowerCase());
                  return !alreadySelected && matchesQuery;
                });
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setSlashIndex((i) => Math.min(i + 1, filtered.length - 1));
                  return;
                }
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setSlashIndex((i) => Math.max(i - 1, 0));
                  return;
                }
                if (e.key === "Enter" || e.key === "Tab") {
                  e.preventDefault();
                  if (filtered[slashIndex]) {
                    handleSlashSelect(filtered[slashIndex]);
                  }
                  return;
                }
                if (e.key === "Escape") {
                  e.preventDefault();
                  setSlashOpen(false);
                  return;
                }
              }

              if (e.key === "Enter") {
                e.preventDefault();
                const hasSlash = input.includes("/");
                if (
                  input.length >= 11 &&
                  hasSlash &&
                  (status === "ready" || status === "error")
                ) {
                  submitForm();
                }
              }
            }}
            placeholder="N° de CUIT /Elegir herramienta..."
            type="text"
            value={input}
          />

          {slashOpen && (
            <SlashCommandMenu
              context={input}
              onClose={() => setSlashOpen(false)}
              onSelect={handleSlashSelect}
              query={slashQuery}
              selectedIndex={slashIndex}
            />
          )}

          <Button
            className={cn(
              "size-9 shrink-0 flex items-center justify-center rounded-xl transition-all duration-200",
              input.length >= 11 && input.includes("/")
                ? "bg-foreground text-background hover:opacity-85 shadow-md"
                : "bg-muted text-muted-foreground/30 cursor-not-allowed"
            )}
            data-testid="send-button"
            disabled={
              input.length < 11 ||
              !input.includes("/") ||
              status === "submitted"
            }
            onClick={(e) => {
              e.preventDefault();
              submitForm();
            }}
            type="submit"
          >
            {status === "submitted" ? (
              <div className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            ) : (
              <ArrowUpIcon className="size-4" />
            )}
          </Button>
        </div>
      </PromptInput>

      {/* Profile Selector */}
      <div className="flex items-center gap-2 mt-1">
        <UserIcon className="h-3.5 w-3.5 text-muted-foreground/50" />
        <span className="text-xs text-muted-foreground/60">
          {t.panel.chat.profile.label}
        </span>
        {profiles.length > 0 ? (
          <Select onValueChange={handleProfileChange} value={activeProfileId}>
            <SelectTrigger className="h-7 border-none bg-transparent px-2 text-xs text-muted-foreground hover:text-foreground shadow-none focus:ring-0 gap-1 rounded-lg">
              <SelectValue
                placeholder={t.panel.chat.profile.selectPlaceholder}
              />
            </SelectTrigger>
            <SelectContent className="rounded-xl">
              {profiles.map((p) => (
                <SelectItem className="text-xs" key={p.id} value={p.id}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <span className="text-xs text-muted-foreground/50 italic">
            {t.panel.chat.profile.empty}
          </span>
        )}
      </div>
    </div>
  );
}

export const MultimodalInput = memo(
  PureMultimodalInput,
  (prevProps, nextProps) => {
    if (prevProps.input !== nextProps.input) {
      return false;
    }
    if (prevProps.status !== nextProps.status) {
      return false;
    }
    if (!equal(prevProps.attachments, nextProps.attachments)) {
      return false;
    }
    if (prevProps.selectedVisibilityType !== nextProps.selectedVisibilityType) {
      return false;
    }
    if (prevProps.selectedModelId !== nextProps.selectedModelId) {
      return false;
    }
    if (prevProps.editingMessage !== nextProps.editingMessage) {
      return false;
    }
    if (prevProps.isLoading !== nextProps.isLoading) {
      return false;
    }
    if (prevProps.messages.length !== nextProps.messages.length) {
      return false;
    }

    return true;
  }
);
