import { auth } from "@clerk/nextjs/server";
import { put } from "@vercel/blob";
import { NextResponse } from "next/server";
import { z } from "zod";
import { ChatbotError } from "@/lib/errors";

const FileSchema = z.object({
  file: z
    .instanceof(Blob)
    .refine((file) => file.size <= 5 * 1024 * 1024, {
      message: "File size should be less than 5MB",
    })
    .refine((file) => ["image/jpeg", "image/png"].includes(file.type), {
      message: "File type should be JPEG or PNG",
    }),
});

export async function POST(request: Request) {
  const { userId } = await auth();

  if (!userId) {
    return new ChatbotError("unauthorized:api").toResponse();
  }

  if (request.body === null) {
    return new ChatbotError("bad_request:api").toResponse();
  }

  try {
    const formData = await request.formData();
    const file = formData.get("file") as Blob;

    if (!file) {
      return new ChatbotError("bad_request:api").toResponse();
    }

    const validatedFile = FileSchema.safeParse({ file });

    if (!validatedFile.success) {
      return new ChatbotError("bad_request:api").toResponse();
    }

    const filename = (formData.get("file") as File).name;
    const safeName = filename.replace(/[^a-zA-Z0-9._-]/g, "_");
    const fileBuffer = await file.arrayBuffer();

    try {
      const data = await put(`${safeName}`, fileBuffer, {
        access: "public",
      });

      return NextResponse.json(data);
    } catch (_error) {
      return new ChatbotError("bad_request:api").toResponse();
    }
  } catch (_error) {
    return new ChatbotError("bad_request:api").toResponse();
  }
}
