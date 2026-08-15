import { auth } from "@clerk/nextjs/server";
import { getChatById, getMessagesByChatId } from "@/lib/db/queries";
import { ChatbotError } from "@/lib/errors";
import { convertToUIMessages } from "@/lib/utils";
import { tenantKey } from "@/lib/tenant";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const chatId = searchParams.get("chatId");

  if (!chatId) {
    return new ChatbotError(
      "bad_request:api",
      "Parameter chatId is required."
    ).toResponse();
  }

  const { userId, orgId } = await auth();
  const tenant = tenantKey(orgId, userId);

  const [chat, messages] = await Promise.all([
    getChatById({ id: chatId }),
    getMessagesByChatId({ id: chatId }),
  ]);

  if (!chat) {
    return new ChatbotError("not_found:chat").toResponse();
  }

  const isOwner = !!userId && userId === chat.userId && tenant === chat.tenantId;

  if (chat.visibility === "private" && !isOwner) {
    return new ChatbotError("forbidden:chat").toResponse();
  }

  const isReadonly = !isOwner;

  return Response.json({
    messages: convertToUIMessages(messages),
    visibility: chat.visibility,
    userId: chat.userId,
    isReadonly,
    activity: chat.agentActivity ?? [],
  });
}
