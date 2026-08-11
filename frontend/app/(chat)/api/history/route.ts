import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { deleteAllChatsByUserId, getChatsByUserId } from "@/lib/db/queries";
import { ChatbotError } from "@/lib/errors";

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;

  const limit = Math.min(
    Math.max(Number.parseInt(searchParams.get("limit") || "10", 10), 1),
    50
  );
  const startingAfter = searchParams.get("starting_after");
  const endingBefore = searchParams.get("ending_before");

  if (startingAfter && endingBefore) {
    return new ChatbotError(
      "bad_request:api",
      "Only one of starting_after or ending_before can be provided."
    ).toResponse();
  }

  const { userId, orgId } = await auth();

  if (!userId) {
    return new ChatbotError("unauthorized:chat").toResponse();
  }

  if (!orgId) {
    return new ChatbotError("forbidden:auth").toResponse();
  }

  const chats = await getChatsByUserId({
    id: userId,
    tenantId: orgId,
    limit,
    startingAfter,
    endingBefore,
  });

  return Response.json(chats);
}

export async function DELETE() {
  const { userId, orgId } = await auth();

  if (!userId) {
    return new ChatbotError("unauthorized:chat").toResponse();
  }

  if (!orgId) {
    return new ChatbotError("forbidden:auth").toResponse();
  }

  const result = await deleteAllChatsByUserId({ userId, tenantId: orgId });

  return Response.json(result, { status: 200 });
}
