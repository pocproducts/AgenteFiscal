import equal from "fast-deep-equal";
import { memo } from "react";
import { toast } from "sonner";
import { useSWRConfig } from "swr";
import { useCopyToClipboard } from "usehooks-ts";
import type { Vote } from "@/lib/db/schema";
import { useLanguage } from "@/lib/i18n";
import type { ChatMessage } from "@/lib/types";
import {
  MessageAction as Action,
  MessageActions as Actions,
} from "../ai-elements/message";
import { CopyIcon, PencilEditIcon, ThumbDownIcon, ThumbUpIcon } from "./icons";

export function PureMessageActions({
  chatId,
  message,
  vote,
  isLoading,
  onEdit,
}: {
  chatId: string;
  message: ChatMessage;
  vote: Vote | undefined;
  isLoading: boolean;
  onEdit?: () => void;
}) {
  const { mutate } = useSWRConfig();
  const [_, copyToClipboard] = useCopyToClipboard();
  const { t } = useLanguage();
  const ma = t.panel.chat.messageActions;

  if (isLoading) {
    return null;
  }

  const textFromParts = message.parts
    ?.filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("\n")
    .trim();

  const handleCopy = async () => {
    if (!textFromParts) {
      toast.error(ma.noTextToCopy);
      return;
    }

    await copyToClipboard(textFromParts);
    toast.success(ma.copied);
  };

  if (message.role === "user") {
    return (
      <Actions className="-mr-0.5 justify-end opacity-0 transition-opacity duration-150 group-hover/message:opacity-100">
        <div className="flex items-center gap-0.5">
          {onEdit && (
            <Action
              className="size-7 text-muted-foreground/50 hover:text-foreground"
              data-testid="message-edit-button"
              onClick={onEdit}
              tooltip={ma.edit}
            >
              <PencilEditIcon />
            </Action>
          )}
          <Action
            className="size-7 text-muted-foreground/50 hover:text-foreground"
            onClick={handleCopy}
            tooltip={ma.copyTooltip}
          >
            <CopyIcon />
          </Action>
        </div>
      </Actions>
    );
  }

  return (
    <Actions className="-ml-0.5 opacity-0 transition-opacity duration-150 group-hover/message:opacity-100">
      <Action
        className="text-muted-foreground/50 hover:text-foreground"
        onClick={handleCopy}
        tooltip={ma.copyTooltip}
      >
        <CopyIcon />
      </Action>

      <Action
        className="text-muted-foreground/50 hover:text-foreground"
        data-testid="message-upvote"
        disabled={vote?.isUpvoted}
        onClick={() => {
          const upvote = fetch(
            `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/vote`,
            {
              method: "PATCH",
              body: JSON.stringify({
                chatId,
                messageId: message.id,
                type: "up",
              }),
            }
          );

          toast.promise(upvote, {
            loading: ma.upvotingLoading,
            success: () => {
              mutate<Vote[]>(
                `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/vote?chatId=${chatId}`,
                (currentVotes) => {
                  if (!currentVotes) {
                    return [];
                  }

                  const votesWithoutCurrent = currentVotes.filter(
                    (currentVote) => currentVote.messageId !== message.id
                  );

                  return [
                    ...votesWithoutCurrent,
                    {
                      chatId,
                      messageId: message.id,
                      isUpvoted: true,
                    },
                  ];
                },
                { revalidate: false }
              );

              return ma.upvoted;
            },
            error: ma.upvoteError,
          });
        }}
        tooltip={ma.upvoteTooltip}
      >
        <ThumbUpIcon />
      </Action>

      <Action
        className="text-muted-foreground/50 hover:text-foreground"
        data-testid="message-downvote"
        disabled={vote && !vote.isUpvoted}
        onClick={() => {
          const downvote = fetch(
            `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/vote`,
            {
              method: "PATCH",
              body: JSON.stringify({
                chatId,
                messageId: message.id,
                type: "down",
              }),
            }
          );

          toast.promise(downvote, {
            loading: ma.downvotingLoading,
            success: () => {
              mutate<Vote[]>(
                `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/vote?chatId=${chatId}`,
                (currentVotes) => {
                  if (!currentVotes) {
                    return [];
                  }

                  const votesWithoutCurrent = currentVotes.filter(
                    (currentVote) => currentVote.messageId !== message.id
                  );

                  return [
                    ...votesWithoutCurrent,
                    {
                      chatId,
                      messageId: message.id,
                      isUpvoted: false,
                    },
                  ];
                },
                { revalidate: false }
              );

              return ma.downvoted;
            },
            error: ma.downvoteError,
          });
        }}
        tooltip={ma.downvoteTooltip}
      >
        <ThumbDownIcon />
      </Action>
    </Actions>
  );
}

export const MessageActions = memo(
  PureMessageActions,
  (prevProps, nextProps) => {
    if (!equal(prevProps.vote, nextProps.vote)) {
      return false;
    }
    if (prevProps.isLoading !== nextProps.isLoading) {
      return false;
    }

    return true;
  }
);
