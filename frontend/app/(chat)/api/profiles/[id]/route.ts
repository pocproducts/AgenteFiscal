// BFF for a single tenant profile: PATCH / DELETE forwarded to the backend.
// See app/(chat)/api/profiles/route.ts for the list/create counterparts.

import { NextResponse } from "next/server";
import { BackendError } from "@/lib/backend/client";
import {
  deleteProfile,
  updateProfile,
  type BackendProfile,
} from "@/lib/backend/profiles";
import type { Profile, ProfileStatus } from "@/lib/shared/db-types";

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

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const body = (await request.json().catch(() => null)) as {
      name?: unknown;
      cuit?: unknown;
      status?: string;
      config?: unknown;
    } | null;

    // Only forward fields the backend accepts, skipping undefined / empty
    // strings (an unset cuit is a valid "clear the cuit" signal).
    const patch: Record<string, unknown> = {};
    if (body?.name !== undefined) {
      patch.name = typeof body.name === "string" ? body.name.trim() : body.name;
    }
    if (body?.cuit !== undefined) {
      patch.cuit =
        typeof body.cuit === "string" && body.cuit ? body.cuit : null;
    }
    if (body?.status !== undefined) {
      patch.status =
        body.status === "active" || body.status === "inactive"
          ? (body.status as ProfileStatus)
          : body.status;
    }
    if (body?.config !== undefined) {
      patch.config =
        body.config && typeof body.config === "object"
          ? (body.config as Record<string, unknown>)
          : undefined;
      if (patch.config === undefined) {
        delete patch.config;
      }
    }

    if (Object.keys(patch).length === 0) {
      return NextResponse.json(
        { error: { code: "EMPTY_UPDATE", message: "Nothing to update." } },
        { status: 422 }
      );
    }

    const profile = await updateProfile(id, patch);
    return NextResponse.json({ profile: toUiProfile(profile) });
  } catch (err) {
    return errorResponse(err);
  }
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    await deleteProfile(id);
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    return errorResponse(err);
  }
}