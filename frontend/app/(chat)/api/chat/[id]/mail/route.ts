import { auth } from "@clerk/nextjs/server";
import {
  BackendError,
  callBackend,
} from "@/lib/backend/client";
import { getChatById, markChatMailSent } from "@/lib/db/queries";
import { ChatbotError, type ErrorCode } from "@/lib/errors";
import { tenantKey } from "@/lib/tenant";

function backendErrorToCode(err: BackendError): ErrorCode {
  if (err.status === 404) {
    return "not_found:chat";
  }
  if (err.status === 400 || err.status === 422) {
    return "bad_request:api";
  }
  return "offline:chat";
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const { userId, orgId } = await auth();
  const tenant = tenantKey(orgId, userId);

  if (!userId || !tenant) {
    return new ChatbotError("unauthorized:chat").toResponse();
  }

  const chat = await getChatById({ id });
  if (!chat) {
    return new ChatbotError("not_found:chat").toResponse();
  }

  const isOwner = !!userId && userId === chat.userId && tenant === chat.tenantId;

  if (chat.visibility === "private" && !isOwner) {
    return new ChatbotError("forbidden:chat").toResponse();
  }

  const body = (await request.json().catch(() => null)) as {
    email?: unknown;
    pdfFile?: unknown;
  } | null;
  const email = typeof body?.email === "string" ? body.email.trim() : "";
  const pdfFile =
    typeof body?.pdfFile === "string" && body.pdfFile.trim()
      ? body.pdfFile.trim()
      : "";

  if (!email.includes("@")) {
    return new ChatbotError(
      "bad_request:api",
      "Valid email required."
    ).toResponse();
  }

  if (!pdfFile) {
    return new ChatbotError(
      "bad_request:api",
      "No hay reporte disponible para enviar."
    ).toResponse();
  }

  // Real send: forward to the Python backend, which resolves the PDF, validates
  // the recipient and delivers via ResendEmailSender. Errors keep the input
  // visible (idle) so the user can fix the address and retry.
  try {
    await callBackend<{ sent: boolean; email: string }>(
      "/v1/chat/reports/send",
      {
        method: "POST",
        body: { email_address: email, pdf_path: pdfFile },
        timeoutMs: 60_000,
      }
    );
  } catch (err) {
    if (err instanceof BackendError) {
      return new ChatbotError(
        backendErrorToCode(err),
        err.detail ?? err.message
      ).toResponse();
    }
    return new ChatbotError("offline:chat").toResponse();
  }

  await markChatMailSent({ chatId: id, email });

  return Response.json({ success: true, sent: true, email });
}