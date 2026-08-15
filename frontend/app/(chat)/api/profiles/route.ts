// BFF for tenant profiles: forwards CRUD to the backend /v1/profiles using the
// authenticated backend client (Clerk JWT never reaches the browser). The
// client hooks (use-profiles.ts) fetch this route via SWR.

import { NextResponse } from "next/server";
import { BackendError } from "@/lib/backend/client";
import {
  createProfile,
  listProfiles,
  type BackendProfile,
} from "@/lib/backend/profiles";
import type { Profile } from "@/lib/shared/db-types";

function toUiProfile(p: BackendProfile): Profile {
  return {
    id: p.id,
    name: p.name,
    cuit: p.cuit,
    status: p.status,
    config: p.config,
    createdAt: p.created_at,
  };
}

function errorResponse(err: unknown) {
  if (err instanceof BackendError) {
    return NextResponse.json(
      {
        error: {
          code: err.code ?? null,
          message: err.detail ?? err.message,
        },
      },
      { status: err.status }
    );
  }
  return NextResponse.json(
    {
      error: {
        code: null,
        message: "Unexpected server error while reaching the profile backend.",
      },
    },
    { status: 500 }
  );
}

export async function GET(request: Request) {
  try {
    const status = new URL(request.url).searchParams.get("status");
    const profiles = await listProfiles(
      status === "active" || status === "inactive" ? status : undefined
    );
    return NextResponse.json({ profiles: profiles.map(toUiProfile) });
  } catch (err) {
    return errorResponse(err);
  }
}

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => null)) as {
      name?: unknown;
      cuit?: unknown;
      config?: unknown;
    } | null;
    const name =
      typeof body?.name === "string" ? body.name.trim() : "";
    if (!name) {
      return NextResponse.json(
        { error: { code: null, message: "Profile name is required" } },
        { status: 422 }
      );
    }
    const profile = await createProfile({
      name,
      cuit: typeof body?.cuit === "string" && body.cuit ? body.cuit : null,
      config:
        body?.config && typeof body.config === "object"
          ? (body.config as Record<string, unknown>)
          : {},
    });
    return NextResponse.json({ profile: toUiProfile(profile) }, { status: 201 });
  } catch (err) {
    return errorResponse(err);
  }
}