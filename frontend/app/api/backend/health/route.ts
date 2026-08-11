import { NextResponse } from "next/server";

import { BackendError, callBackend } from "@/lib/backend/client";

// BFF proof route for the migration: forwards the user's Clerk JWT to the
// Python backend (fiscal_agent) and returns its UnifiedResponse unchanged.
export const runtime = "nodejs";

interface BackendService {
  name: string;
  status: string;
  last_check: string;
  latency_ms: number | null;
  error: string | null;
  version: string | null;
}

interface BackendHealth {
  status: string;
  result: {
    status: "healthy" | "degraded" | "down";
    services: BackendService[];
    timestamp: string;
  } | null;
}

export async function GET() {
  try {
    const data = await callBackend<BackendHealth>("/v1/health");
    return NextResponse.json(data);
  } catch (err) {
    if (err instanceof BackendError) {
      return NextResponse.json(
        { status: "error", error: { code: err.code, message: err.message } },
        { status: err.status }
      );
    }
    throw err;
  }
}
