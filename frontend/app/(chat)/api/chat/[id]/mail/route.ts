import { auth } from "@clerk/nextjs/server";
import { ejecutarEnviarMail } from "@/lib/ai/tools/fiscal-tools";
import {
  getChatById,
  getMessagesByChatId,
  markChatMailSent,
} from "@/lib/db/queries";
import { ChatbotError } from "@/lib/errors";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const { userId, orgId } = await auth();
  if (!userId) {
    return new ChatbotError("unauthorized:chat").toResponse();
  }

  const chat = await getChatById({ id });
  if (!chat) {
    return new ChatbotError("not_found:chat").toResponse();
  }

  const isOwner = !!userId && userId === chat.userId && orgId === chat.tenantId;

  if (chat.visibility === "private" && !isOwner) {
    return new ChatbotError("forbidden:chat").toResponse();
  }

  const body = (await request.json().catch(() => null)) as {
    email?: unknown;
  } | null;
  const email = typeof body?.email === "string" ? body.email.trim() : "";

  if (!email.includes("@")) {
    return new ChatbotError(
      "bad_request:api",
      "Valid email required."
    ).toResponse();
  }

  const msgs = await getMessagesByChatId({ id });
  const firstUserMessage = msgs.find((m) => m.role === "user");
  const parts = (firstUserMessage?.parts ?? []) as Array<{
    type: string;
    text?: unknown;
  }>;
  let cuit = "00000000000";
  if (Array.isArray(parts)) {
    for (const part of parts) {
      if (part?.type === "text" && typeof part.text === "string") {
        const match = part.text.match(/^(\d{11})/);
        if (match) {
          cuit = match[1];
          break;
        }
      }
    }
  }

  const result = await ejecutarEnviarMail(cuit, email);
  await markChatMailSent({ chatId: id, email });

  return Response.json({ success: true, ...result });
}
